from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.pipeline.state import PipelineState
from app.prompts.trend_prompts import TREND_SCORE_SYSTEM, TREND_SCORE_USER
from app.config import settings
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.2,
    api_key=settings.openai_api_key,
)

# ─── Fallback topics if all scrapers fail ────────────────────────────────────
FALLBACK_TOPICS = [
    "LangGraph multi-agent workflows in 2025",
    "Next.js 15 App Router performance tips",
    "Vector databases compared: Pinecone vs Weaviate vs Chroma",
    "Building production RAG systems with LlamaIndex",
    "Edge computing with Cloudflare Workers and AI",
]


# ─── Scrapers ────────────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def _fetch_github_trending() -> list[dict]:
    """Fetch GitHub trending repos (past 24h, any language)."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://github-trending-api.de/repositories",
            params={"since": "daily"},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        repos = resp.json()
        return [
            {
                "source": "github_trending",
                "title": r.get("name", ""),
                "description": r.get("description", ""),
                "stars_today": r.get("currentPeriodStars", 0),
                "url": r.get("url", ""),
                "language": r.get("language", ""),
            }
            for r in repos[:20]
        ]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def _fetch_hackernews() -> list[dict]:
    """Fetch top 15 HN stories."""
    async with httpx.AsyncClient(timeout=15) as client:
        ids_resp = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
        ids_resp.raise_for_status()
        story_ids = ids_resp.json()[:15]

        stories = []
        for sid in story_ids:
            try:
                s = await client.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
                data = s.json()
                if data.get("type") == "story":
                    stories.append({
                        "source": "hacker_news",
                        "title": data.get("title", ""),
                        "url": data.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                        "score": data.get("score", 0),
                    })
            except Exception:
                continue
        return stories


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def _fetch_reddit() -> list[dict]:
    """Fetch hot posts from developer subreddits."""
    subreddits = ["programming", "webdev", "MachineLearning", "artificial"]
    posts = []
    async with httpx.AsyncClient(
        timeout=15,
        headers={"User-Agent": "devblog-pipeline/1.0"},
    ) as client:
        for sub in subreddits:
            try:
                resp = await client.get(
                    f"https://www.reddit.com/r/{sub}/hot.json",
                    params={"limit": 5},
                )
                resp.raise_for_status()
                for child in resp.json()["data"]["children"]:
                    d = child["data"]
                    posts.append({
                        "source": f"reddit/{sub}",
                        "title": d.get("title", ""),
                        "url": f"https://reddit.com{d.get('permalink', '')}",
                        "score": d.get("score", 0),
                    })
            except Exception as e:
                logger.warning(f"Reddit {sub} scrape failed: {e}")
    return posts


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def _fetch_youtube_trending() -> list[dict]:
    """Scrape YouTube trending tech videos via search (no API key required)."""
    queries = ["ai programming 2025", "web development tutorial 2025", "llm tools developers"]
    results = []
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for q in queries:
            try:
                resp = await client.get(
                    "https://www.youtube.com/results",
                    params={"search_query": q, "sp": "CAMSAhAB"},  # sort by view count
                )
                # Extract video titles from the response (basic scrape)
                import re
                titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]{10,100})"', resp.text)
                for title in titles[:3]:
                    results.append({
                        "source": "youtube_trending",
                        "title": title,
                        "url": "https://youtube.com",
                        "score": 0,
                    })
            except Exception as e:
                logger.warning(f"YouTube scrape failed for '{q}': {e}")
    return results


# ─── Scoring via LLM ─────────────────────────────────────────────────────────

async def _score_topics(raw_items: list[dict]) -> tuple[str, int, list[str]]:
    """Ask GPT-4o-mini to pick and score the best topic for a dev blog post."""
    summary = json.dumps(raw_items[:40], indent=2)   # cap context size
    messages = [
        {"role": "system", "content": TREND_SCORE_SYSTEM},
        {"role": "user",   "content": TREND_SCORE_USER.format(items=summary)},
    ]
    response = await llm.ainvoke(messages)

    # Parse JSON from LLM response
    text = response.content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    data = json.loads(text)

    return (
        data["topic"],
        int(data["score"]),
        data.get("sources", []),
    )


# ─── Agent entry point ───────────────────────────────────────────────────────

async def trend_agent(state: PipelineState) -> dict:
    """
    Collects trending topics from GitHub, HN, Reddit, YouTube.
    Scores them with GPT-4o-mini and returns the best one.
    Falls back to a curated list if all scrapers fail.
    """
    run_id = state["run_id"]
    logger.info(f"[trend] run_id={run_id} — starting trend collection")

    # If a topic was manually specified, skip scraping
    if state.get("topic_override"):
        logger.info(f"[trend] Using override topic: {state['topic_override']}")
        return {
            "topic": state["topic_override"],
            "topic_score": 100,
            "topic_sources": ["manual override"],
        }

    # Scrape all sources concurrently
    import asyncio
    results = await asyncio.gather(
        _fetch_github_trending(),
        _fetch_hackernews(),
        _fetch_reddit(),
        _fetch_youtube_trending(),
        return_exceptions=True,
    )

    all_items: list[dict] = []
    for r in results:
        if isinstance(r, list):
            all_items.extend(r)
        else:
            logger.warning(f"[trend] Scraper returned exception: {r}")

    if not all_items:
        logger.warning("[trend] All scrapers failed — using fallback topic list")
        import random
        fallback = random.choice(FALLBACK_TOPICS)
        return {
            "topic": fallback,
            "topic_score": 50,
            "topic_sources": ["fallback"],
        }

    try:
        topic, score, sources = await _score_topics(all_items)
        logger.info(f"[trend] Selected topic: '{topic}' (score={score})")
        return {
            "topic": topic,
            "topic_score": score,
            "topic_sources": sources,
        }
    except Exception as e:
        logger.error(f"[trend] LLM scoring failed: {e}")
        import random
        fallback = random.choice(FALLBACK_TOPICS)
        return {
            "topic": fallback,
            "topic_score": 50,
            "topic_sources": ["fallback_after_llm_error"],
        }
