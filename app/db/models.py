from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Float, Integer, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.connection import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PipelineRun(Base):
    """One row per pipeline execution."""
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    topic: Mapped[str | None] = mapped_column(String(512), nullable=True)
    topic_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Lifecycle
    status: Mapped[str] = mapped_column(String(32), default="running")
    # "running" | "awaiting_approval" | "approved" | "rejected" | "completed" | "failed"

    approval_status: Mapped[str] = mapped_column(String(32), default="pending")
    # "pending" | "approved" | "rejected"

    image_choice_status: Mapped[str] = mapped_column(String(32), default="pending")
    # "pending" | "completed"

    image_format_choice: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # "carousel" | "screenshot"

    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Output
    blog_post_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    seo_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    seo_slug: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Financials
    total_tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    costs: Mapped[list["AgentCost"]] = relationship("AgentCost", back_populates="run", cascade="all, delete-orphan")


class AgentCost(Base):
    """Per-agent token and cost tracking."""
    __tablename__ = "agent_costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("pipeline_runs.id", ondelete="CASCADE"))
    agent_name: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped["PipelineRun"] = relationship("PipelineRun", back_populates="costs")
