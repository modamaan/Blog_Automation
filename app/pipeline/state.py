from __future__ import annotations

from typing import TypedDict


class TweetDict(TypedDict):
    num: int
    text: str          # <= 280 chars


class ReferenceDict(TypedDict):
    url: str
    title: str
    snippet: str


class PipelineState(TypedDict):
    # ── Run identity ─────────────────────────────────────────────────────────
    run_id: str
    triggered_at: str
    topic_override: str | None        # Set via /pipeline/run body

    # ── Trend Agent ──────────────────────────────────────────────────────────
    topic: str
    topic_score: int                  # 0–100
    topic_sources: list[str]          # URLs showing it trending

    # ── Research Agent ───────────────────────────────────────────────────────
    research_notes: str               # Structured Markdown
    key_facts: list[str]              # Bullet-point facts
    references: list[ReferenceDict]   # [{url, title, snippet}]

    # ── Planner Agent ────────────────────────────────────────────────────────
    outline: list[str]                # ["## Introduction", ...]
    genre: str                        # "Tutorial" | "SaaS Story" | "Tech News" | "Tool Review"

    # ── Writer Agent ─────────────────────────────────────────────────────────
    draft: str                        # Full Markdown blog post
    word_count: int
    writer_retries: int               # Fact-check retry counter

    # ── Fact Checker ─────────────────────────────────────────────────────────
    fact_check_passed: bool
    fact_issues: list[str]

    # ── SEO Agent ────────────────────────────────────────────────────────────
    seo_title: str
    seo_slug: str
    meta_description: str
    focus_keywords: list[str]
    faq_section: str

    # ── Social Agent (Twitter / Instagram Screenshots) ───────────────
    tweets: list[TweetDict]
    carousel_image_paths: list[str]   # 1080x1080 screenshots of tweets
    insta_caption: str

    # ── YouTube images (populated when topic_override is a YT URL) ───────────
    youtube_thumbnail_url: str | None  # maxresdefault.jpg — used as blog banner
    youtube_still_urls: list[str]      # [1.jpg, 2.jpg, 3.jpg] — embedded in body

    # ── Telegram delivery ────────────────────────────────────────────────────
    telegram_message_ids: list[int]
    image_choice_status: str          # "pending" | "completed"
    image_format_choice: str | None   # "carousel" | "screenshot"
    approval_status: str              # "pending" | "approved" | "rejected"
    rejection_reason: str | None

    # ── Publisher ────────────────────────────────────────────────────────────
    blog_post_id: str | None
    blog_post_url: str | None

    # ── Analytics ────────────────────────────────────────────────────────────
    published_at: str | None
    total_tokens_used: int
    estimated_cost_usd: float
    agent_costs: list[dict]           # [{agent, model, tokens_in, tokens_out, cost}]
    errors: list[str]


def initial_state(run_id: str, topic_override: str | None = None) -> PipelineState:
    """Return a fully initialised state with safe defaults."""
    from datetime import datetime, timezone
    return PipelineState(
        run_id=run_id,
        triggered_at=datetime.now(timezone.utc).isoformat(),
        topic_override=topic_override,
        topic="",
        topic_score=0,
        topic_sources=[],
        research_notes="",
        key_facts=[],
        references=[],
        outline=[],
        draft="",
        word_count=0,
        writer_retries=0,
        fact_check_passed=False,
        fact_issues=[],
        seo_title="",
        seo_slug="",
        meta_description="",
        focus_keywords=[],
        faq_section="",
        slides=[],
        carousel_image_paths=[],
        insta_caption="",
        youtube_thumbnail_url=None,
        youtube_still_urls=[],
        telegram_message_ids=[],
        approval_status="pending",
        rejection_reason=None,
        blog_post_id=None,
        blog_post_url=None,
        published_at=None,
        total_tokens_used=0,
        estimated_cost_usd=0.0,
        agent_costs=[],
        errors=[],
    )
