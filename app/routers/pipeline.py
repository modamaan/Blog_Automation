from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.pipeline.state import initial_state
from app.db.connection import AsyncSessionLocal
from app.db.models import PipelineRun

logger = logging.getLogger(__name__)
router = APIRouter()


class RunRequest(BaseModel):
    topic: str | None = None     # None → trend agent picks automatically


async def _run_pipeline(run_id: str, topic_override: str | None) -> None:
    """Background task: runs the full LangGraph pipeline."""
    from app.pipeline.graph import get_compiled_graph
    from app.config import settings
    from app.tools.telegram_client import send_error_alert

    logger.info(f"[pipeline] Starting run_id={run_id} topic_override={topic_override}")

    state = initial_state(run_id, topic_override)

    try:
        import redis.asyncio as redis
        from langgraph.checkpoint.redis import AsyncRedisSaver
        redis_client = redis.Redis.from_url(settings.redis_url)
        checkpointer = AsyncRedisSaver(redis_client=redis_client)
        await checkpointer.asetup()

        graph = get_compiled_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": run_id}}

        # Run until interrupt (telegram_delivery sets approval_status=pending)
        # The graph stops before "publisher" due to interrupt_before=["publisher"]
        result = await graph.ainvoke(state, config=config)

        # Check if graph actually paused or if it finished early (aborted)
        current_state = await graph.aget_state(config)
        is_finished = len(current_state.next) == 0

        # Update DB status
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select
            res = await session.execute(select(PipelineRun).where(PipelineRun.id == run_id))
            run = res.scalar_one_or_none()
            if run:
                run.topic = result.get("topic", "")
                run.topic_score = result.get("topic_score", 0)

                if is_finished:
                    logger.info(f"[pipeline] Graph finished early (aborted) — run_id={run_id}")
                    run.status = "failed"
                else:
                    logger.info(f"[pipeline] Graph paused — run_id={run_id} awaiting Telegram approval")
                    run.status = "awaiting_approval"

                await session.commit()

    except Exception as e:
        logger.error(f"[pipeline] Fatal error run_id={run_id}: {e}", exc_info=True)
        await send_error_alert(settings.telegram_chat_id, run_id, str(e))

        async with AsyncSessionLocal() as session:
            from sqlalchemy import select
            res = await session.execute(select(PipelineRun).where(PipelineRun.id == run_id))
            run = res.scalar_one_or_none()
            if run:
                run.status = "failed"
                await session.commit()


@router.post("/run")
async def run_pipeline(body: RunRequest, background_tasks: BackgroundTasks):
    """
    Trigger the pipeline. Returns {run_id} immediately.
    The pipeline runs in the background and pauses at Telegram approval.
    """
    from datetime import timedelta
    from sqlalchemy import select, desc

    query_topic = body.topic or "auto"

    async with AsyncSessionLocal() as session:
        # Deduplication check: if the same topic was requested in the last 60 seconds, ignore duplicate.
        sixty_secs_ago = datetime.now(timezone.utc) - timedelta(seconds=60)
        
        result = await session.execute(
            select(PipelineRun)
            .where(PipelineRun.topic == query_topic)
            .where(PipelineRun.created_at >= sixty_secs_ago)
            .order_by(desc(PipelineRun.created_at))
            .limit(1)
        )
        recent_run = result.scalar_one_or_none()
        
        if recent_run:
            logger.warning(f"[pipeline] Deduplicated request for topic '{query_topic}'. Returning existing run_id={recent_run.id}")
            return {"run_id": recent_run.id, "status": "running", "message": "deduplicated"}

        # Create new run
        run_id = str(uuid.uuid4())
        session.add(PipelineRun(
            id=run_id,
            topic=query_topic,
            status="running",
            created_at=datetime.now(timezone.utc),
        ))
        await session.commit()

    background_tasks.add_task(_run_pipeline, run_id, body.topic)
    logger.info(f"[pipeline] Queued run_id={run_id}")

    return {"run_id": run_id, "status": "running"}


@router.get("/runs")
async def list_runs():
    """List recent pipeline runs."""
    from sqlalchemy import select, desc
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(20)
        )
        runs = result.scalars().all()
        return {"runs": [
            {
                "run_id": r.id,
                "topic": r.topic,
                "status": r.status,
                "approval_status": r.approval_status,
                "blog_post_url": r.blog_post_url,
                "cost_usd": r.estimated_cost_usd,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in runs
        ]}
