from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.db.connection import AsyncSessionLocal
from app.db.models import PipelineRun

logger = logging.getLogger(__name__)
router = APIRouter()


class CallbackRequest(BaseModel):
    action: str  # "approve" | "reject"
    reason: str | None = None


@router.post("/callback/{run_id}")
async def telegram_callback(run_id: str, body: CallbackRequest, background_tasks: BackgroundTasks):
    """
    Called by n8n when the user taps an inline button in Telegram.
    Writes the decision to PostgreSQL, then resumes the LangGraph graph.
    """
    if body.action not in ("approve", "reject", "carousel", "screenshot"):
        raise HTTPException(
            status_code=400, detail="action must be 'approve', 'reject', 'carousel', or 'screenshot'"
        )

    # Load DB run and validate
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PipelineRun).where(PipelineRun.id == run_id)
        )
        run = result.scalar_one_or_none()

    if not run:
        raise HTTPException(status_code=404, detail=f"run_id {run_id} not found")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PipelineRun).where(PipelineRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        if run:
            if body.action in ("approve", "reject"):
                run.approval_status = "approved" if body.action == "approve" else "rejected"
                run.rejection_reason = body.reason if body.action == "reject" else None
            elif body.action in ("carousel", "screenshot"):
                run.image_choice_status = "completed"
                run.image_format_choice = body.action
            await session.commit()

    logger.info(f"[callback] action={body.action} written to DB for run_id={run_id}")

    # ── Resume graph ───────────────────────────────────────────────────────────
    if body.action in ("carousel", "screenshot"):
        from app.tools import telegram_client
        from app.config import settings
        format_name = "DevBlog Screenshot" if body.action == "screenshot" else "Carousel"
        await telegram_client.send_text(settings.telegram_chat_id, f"⚙️ Generating {format_name}... This will take about 30 seconds!")
        
    await _resume_graph(run_id, background_tasks)
    return {"status": "resumed", "action": body.action}

async def _resume_graph(run_id: str, background_tasks: BackgroundTasks) -> None:
    """Resume the interrupted LangGraph from its Redis checkpoint."""
    from app.pipeline.graph import get_compiled_graph
    from app.config import settings
    import redis.asyncio as redis
    from langgraph.checkpoint.redis import AsyncRedisSaver

    redis_client = redis.Redis.from_url(settings.redis_url)
    checkpointer = AsyncRedisSaver(redis_client=redis_client)
    await checkpointer.asetup()

    # Compile WITH interrupt so the graph respects subsequent pause points
    graph = get_compiled_graph(checkpointer=checkpointer, interrupt=True)
    config = {"configurable": {"thread_id": run_id}}

    pre_state = await graph.aget_state(config)
    logger.info(
        f"[callback] Resuming run_id={run_id} "
        f"state.next={pre_state.next} "
        f"approval_status={pre_state.values.get('approval_status')}"
    )

    # Schedule graph continuation via FastAPI BackgroundTasks (lifecycle-managed)
    background_tasks.add_task(_continue_graph, graph, config)


async def _continue_graph(graph, config: dict) -> None:
    """Continue graph execution (called as FastAPI background task)."""
    thread_id = config["configurable"]["thread_id"]
    try:
        start_state = await graph.aget_state(config)
        logger.info(
            f"[callback] GRAPH RESUME thread_id={thread_id} "
            f"next={start_state.next} "
            f"approval_status={start_state.values.get('approval_status')}"
        )

        result = await graph.ainvoke(None, config=config)
        logger.info(
            f"[callback] Graph completed for thread_id={thread_id} "
            f"blog_url={result.get('blog_post_url')} "
            f"approval={result.get('approval_status')}"
        )
    except Exception as e:
        logger.error(f"[callback] Graph continuation failed: {e}", exc_info=True)
