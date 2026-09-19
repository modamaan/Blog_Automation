from __future__ import annotations

"""
LangGraph StateGraph — DevBlog Autonomous Pipeline

Flow:
  trend → research → planner → writer → fact_check
  ↓ (pass)                               ↓ (retry ≤2)
  seo → carousel → telegram_delivery  ←──┘
  [INTERRUPT — wait for human approval]
  ↓ (approve)          ↓ (reject)
  publisher          analytics (rejected)
  ↓
  analytics (completed)
"""

import logging
from langgraph.graph import StateGraph, START, END

from app.pipeline.state import PipelineState
from app.config import settings

# ─── Import agent nodes ───────────────────────────────────────────────────────
from app.pipeline.nodes.trend_agent import trend_agent
from app.pipeline.nodes.research_agent import research_agent
from app.pipeline.nodes.planner_agent import planner_agent
from app.pipeline.nodes.writer_agent import writer_agent
from app.pipeline.nodes.fact_checker_agent import fact_checker_agent
from app.pipeline.nodes.seo_agent import seo_agent
from app.pipeline.nodes.image_choice_node import image_choice_node
from app.pipeline.nodes.social_agent import social_agent
from app.pipeline.nodes.telegram_delivery_node import telegram_delivery_node
from app.pipeline.nodes.instagram_delivery_node import instagram_delivery_node
from app.pipeline.nodes.publisher_agent import publisher_agent
from app.pipeline.nodes.analytics_agent import analytics_agent

logger = logging.getLogger(__name__)


# ─── Routing functions ────────────────────────────────────────────────────────

def route_after_fact_check(state: PipelineState) -> str:
    """Retry writer up to 2 times; proceed to SEO if passed."""
    if state["fact_check_passed"]:
        return "seo"
    if state.get("writer_retries", 0) < 2:
        logger.warning(f"[graph] Fact check failed — retrying writer (attempt {state['writer_retries'] + 1})")
        return "writer"
    logger.error("[graph] Fact check failed after 2 retries — aborting")
    return "analytics_failed"


def route_after_image_choice(state: PipelineState) -> str:
    """Pause until user selects an image format."""
    status = state.get("image_choice_status", "pending")
    if status == "completed":
        return "social"
    return END  # Interruptedd or timed-out


def route_after_approval(state: PipelineState) -> str:
    """Route based on human Telegram decision."""
    status = state.get("approval_status", "pending")
    if status == "approved":
        return "publisher"
    return "analytics"   # rejected or timed-out


# ─── Build the graph ─────────────────────────────────────────────────────────

async def image_choice_resume(state: PipelineState) -> dict:
    """
    Read the image format choice from PostgreSQL.
    """
    from app.db.connection import AsyncSessionLocal
    from app.db.models import PipelineRun
    from sqlalchemy import select

    run_id = state["run_id"]
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PipelineRun).where(PipelineRun.id == run_id)
        )
        run = result.scalar_one_or_none()

    if run and run.image_choice_status in ("completed", "pending"):
        logger.info(f"[image_choice_resume] run_id={run_id} status={run.image_choice_status}")
        return {
            "image_choice_status": run.image_choice_status,
            "image_format_choice": run.image_format_choice,
        }

    return {"image_choice_status": "pending"}


async def human_approval(state: PipelineState) -> dict:
    """
    Read the human approval decision from PostgreSQL.

    The /telegram/callback endpoint writes the decision to the DB before
    resuming the graph.  We read it here instead of relying on
    aupdate_state(), which does not reliably persist state in the
    AsyncRedisSaver checkpointer.
    """
    from app.db.connection import AsyncSessionLocal
    from app.db.models import PipelineRun
    from sqlalchemy import select

    run_id = state["run_id"]
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PipelineRun).where(PipelineRun.id == run_id)
        )
        run = result.scalar_one_or_none()

    if run and run.approval_status in ("approved", "rejected"):
        logger.info(f"[human_approval] run_id={run_id} decision={run.approval_status}")
        return {
            "approval_status": run.approval_status,
            "rejection_reason": run.rejection_reason,
        }

    # Safety fallback: treat unknown as rejected so the run closes cleanly
    logger.warning(f"[human_approval] run_id={run_id} — no DB decision, defaulting to rejected")
    return {"approval_status": "rejected", "rejection_reason": "Approval decision not found in DB"}


def build_graph() -> StateGraph:
    builder = StateGraph(PipelineState)

    # Register nodes
    builder.add_node("trend",             trend_agent)
    builder.add_node("research",          research_agent)
    builder.add_node("planner",           planner_agent)
    builder.add_node("writer",            writer_agent)
    builder.add_node("fact_check",        fact_checker_agent)
    builder.add_node("seo",               seo_agent)
    builder.add_node("image_choice",      image_choice_node)
    builder.add_node("image_choice_resume", image_choice_resume)
    builder.add_node("social",            social_agent)
    builder.add_node("telegram",          telegram_delivery_node)
    builder.add_node("human_approval",    human_approval)
    builder.add_node("publisher",         publisher_agent)
    builder.add_node("analytics",         analytics_agent)

    # Sequential edges
    builder.add_edge(START,           "trend")
    builder.add_edge("trend",         "research")
    builder.add_edge("research",      "planner")
    builder.add_edge("planner",       "writer")
    builder.add_edge("writer",        "fact_check")

    # Conditional: fact check pass/retry/abort
    builder.add_conditional_edges(
        "fact_check",
        route_after_fact_check,
        {
            "seo":              "seo",
            "writer":           "writer",
            "analytics_failed": "analytics",
        },
    )

    builder.add_edge("seo", "image_choice")
    builder.add_edge("image_choice", "image_choice_resume")

    builder.add_conditional_edges(
        "image_choice_resume",
        route_after_image_choice,
        {
            "social": "social",
            END: END,
        }
    )

    builder.add_edge("social", "telegram")
    builder.add_edge("telegram", "human_approval")

    # ── INTERRUPT HERE — graph pauses until /pipeline/callback is called ──
    # telegram_delivery sets approval_status="pending" and returns
    # The graph resumes when the caller invokes graph.invoke() again with
    # the updated state (approval_status set to "approved" or "rejected")
    builder.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {
            "publisher": "publisher",
            "analytics": "analytics",
        },
    )

    builder.add_edge("publisher", "analytics")
    builder.add_edge("analytics", END)

    return builder


def get_compiled_graph(checkpointer=None, interrupt: bool = True):
    """Return a compiled graph, optionally with a Redis checkpointer."""
    builder = build_graph()
    if checkpointer:
        return builder.compile(
            checkpointer=checkpointer,
            interrupt_before=["image_choice_resume", "human_approval"] if interrupt else [],
        )
    return builder.compile()
