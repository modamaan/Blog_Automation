from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from app.pipeline.state import PipelineState
from app.db.connection import AsyncSessionLocal
from app.db.models import PipelineRun, AgentCost
from app.tools.telegram_client import send_success_summary
from app.config import settings

logger = logging.getLogger(__name__)


async def analytics_agent(state: PipelineState) -> dict:
    """Write run results to DB and send Telegram success/failure summary."""
    run_id = state["run_id"]
    logger.info(f"[analytics] run_id={run_id}")

    approval = state.get("approval_status", "pending")
    blog_url = state.get("blog_post_url")
    now = datetime.now(timezone.utc)

    # Calculate totals
    total_tokens = sum(
        c.get("tokens_in", 0) + c.get("tokens_out", 0)
        for c in state.get("agent_costs", [])
    )
    total_cost = sum(c.get("cost", 0.0) for c in state.get("agent_costs", []))

    # Determine final status
    if approval == "approved" and blog_url:
        status = "completed"
    elif approval == "approved" and not blog_url:
        status = "publisher_error"   # publisher ran but failed silently
    elif approval == "rejected":
        status = "rejected"
    elif state.get("errors"):
        status = "failed"
    else:
        status = "completed"

    try:
        async with AsyncSessionLocal() as session:
            # Update pipeline_runs row
            result = await session.execute(
                select(PipelineRun).where(PipelineRun.id == run_id)
            )
            run = result.scalar_one_or_none()
            if run:
                run.status = status
                run.approval_status = approval
                run.blog_post_url = blog_url
                run.seo_title = state.get("seo_title")
                run.seo_slug = state.get("seo_slug")
                run.total_tokens_used = total_tokens
                run.estimated_cost_usd = total_cost
                run.completed_at = now
                run.rejection_reason = state.get("rejection_reason")

                # Insert per-agent costs
                for c in state.get("agent_costs", []):
                    session.add(AgentCost(
                        run_id=run_id,
                        agent_name=c.get("agent", "unknown"),
                        model=c.get("model", "unknown"),
                        tokens_in=c.get("tokens_in", 0),
                        tokens_out=c.get("tokens_out", 0),
                        cost_usd=c.get("cost", 0.0),
                    ))

                await session.commit()
                logger.info(f"[analytics] DB updated — status={status} cost=${total_cost:.4f}")

    except Exception as e:
        logger.error(f"[analytics] DB write failed: {e}")

    # Telegram summary
    if status == "completed" and blog_url:
        await send_success_summary(
            settings.telegram_chat_id,
            state.get("seo_title", state.get("topic", "")),
            blog_url,
            total_cost,
        )
    elif status == "publisher_error":
        from app.tools.telegram_client import send_text
        errors_str = "\n".join(state.get("errors", ["Unknown publisher error"]))
        await send_text(
            settings.telegram_chat_id,
            f"🚨 *Publisher failed* — post was approved but couldn't be uploaded!\n`{run_id}`\n\n```\n{errors_str[:400]}\n```",
        )
    elif status == "rejected":
        from app.tools.telegram_client import send_text
        await send_text(
            settings.telegram_chat_id,
            f"❌ *Run rejected*\n`{run_id}`\nReason: {state.get('rejection_reason', 'No reason given')}",
        )

    return {
        "published_at": now.isoformat() if status == "completed" else None,
        "total_tokens_used": total_tokens,
        "estimated_cost_usd": total_cost,
    }
