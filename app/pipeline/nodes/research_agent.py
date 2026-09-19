from __future__ import annotations

import json
import logging
import asyncio
import re

from youtube_transcript_api import YouTubeTranscriptApi

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.pipeline.state import PipelineState, ReferenceDict
from app.prompts.research_prompts import RESEARCH_SYSTEM, RESEARCH_USER
from app.config import settings
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

llm = ChatOpenAI(
    model="gpt-4o",
    temperature=0.3,
    api_key=settings.openai_api_key,
)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
async def _web_search(query: str) -> list[dict]:
    """
    Search the web using DuckDuckGo Instant Answer API (no key required).
    Falls back gracefully if the API returns no results.
    """
    results = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_redirect": 1, "no_html": 1},
            )
            data = resp.json()

            # Abstract result
            if data.get("AbstractText"):
                results.append({
                    "url": data.get("AbstractURL", ""),
                    "title": data.get("Heading", query),
                    "snippet": data["AbstractText"][:400],
                })

            # Related topics
            for topic in data.get("RelatedTopics", [])[:3]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append({
                        "url": topic.get("FirstURL", ""),
                        "title": topic.get("Text", "")[:80],
                        "snippet": topic.get("Text", "")[:400],
                    })
    except Exception as e:
        logger.warning(f"[research] Search failed for '{query}': {e}")

    return results


async def _gather_references(topic: str) -> list[ReferenceDict]:
    """Run 5 targeted searches for the topic in parallel."""
    queries = [
        f"{topic} official documentation",
        f"{topic} GitHub repository",
        f"{topic} tutorial guide 2025",
        f"{topic} benchmarks comparison",
        f"{topic} hacker news discussion",
    ]
    search_results = await asyncio.gather(
        *[_web_search(q) for q in queries],
        return_exceptions=True,
    )

    references: list[ReferenceDict] = []
    seen_urls: set[str] = set()

    for batch in search_results:
        if isinstance(batch, list):
            for ref in batch:
                url = ref.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    references.append(ReferenceDict(
                        url=url,
                        title=ref.get("title", ""),
                        snippet=ref.get("snippet", ""),
                    ))

    return references[:12]   # cap at 12 references


async def research_agent(state: PipelineState) -> dict:
    """
    Gathers web references for the topic, then uses GPT-4o to produce
    structured Markdown research notes and a list of key facts.
    """
    run_id = state["run_id"]
    topic = state["topic"]
    logger.info(f"[research] run_id={run_id} topic='{topic}'")

    youtube_thumbnail_url: str | None = None
    youtube_still_urls: list[str] = []

    if "youtube.com" in topic or "youtu.be" in topic:
        match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", topic)
        if match:
            video_id = match.group(1)

            # Build YouTube image URLs (public CDN, no API key required)
            youtube_thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
            youtube_still_urls = [
                f"https://img.youtube.com/vi/{video_id}/sd1.jpg",
                f"https://img.youtube.com/vi/{video_id}/sd2.jpg",
                f"https://img.youtube.com/vi/{video_id}/sd3.jpg",
            ]
            logger.info(f"[research] YouTube images: thumbnail + {len(youtube_still_urls)} stills for video_id={video_id}")

            try:
                transcript_obj = YouTubeTranscriptApi().fetch(video_id)
                transcript_text = " ".join([t.text for t in transcript_obj])
                references = [{
                    "url": topic,
                    "title": "YouTube Video Transcript",
                    "snippet": transcript_text[:15000]
                }]
                logger.info(f"[research] Extracted YouTube transcript: {len(transcript_text)} chars")
            except Exception as e:
                logger.error(f"[research] Failed to extract transcript: {e}")
                references = await _gather_references(topic)
        else:
            references = await _gather_references(topic)
    else:
        references = await _gather_references(topic)

    logger.info(f"[research] Collected {len(references)} references")

    # Format references for the prompt
    refs_text = "\n\n".join(
        f"[{i+1}] {r['title']}\n{r['url']}\n{r['snippet']}"
        for i, r in enumerate(references)
    )

    messages = [
        {"role": "system", "content": RESEARCH_SYSTEM},
        {"role": "user",   "content": RESEARCH_USER.format(topic=topic, references=refs_text)},
    ]

    response = await llm.ainvoke(messages)
    raw = response.content

    # Parse structured output
    notes = raw
    key_facts: list[str] = []

    # Extract key facts section if present
    if "## Key Facts" in raw:
        parts = raw.split("## Key Facts")
        notes = parts[0].strip()
        facts_section = parts[1].strip()
        for line in facts_section.split("\n"):
            line = line.strip().lstrip("- •").strip()
            if line:
                key_facts.append(line)

    # Track cost
    usage = response.response_metadata.get("token_usage", {})
    agent_cost = {
        "agent": "research",
        "model": "gpt-4o",
        "tokens_in": usage.get("prompt_tokens", 0),
        "tokens_out": usage.get("completion_tokens", 0),
        "cost": (usage.get("prompt_tokens", 0) * 0.0000025 +
                 usage.get("completion_tokens", 0) * 0.000010),
    }

    logger.info(f"[research] Notes: {len(notes)} chars, {len(key_facts)} facts")

    return {
        "research_notes": notes,
        "key_facts": key_facts,
        "references": references,
        "youtube_thumbnail_url": youtube_thumbnail_url,
        "youtube_still_urls": youtube_still_urls,
        "agent_costs": state.get("agent_costs", []) + [agent_cost],
    }
