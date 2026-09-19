from __future__ import annotations

import json
import logging
import re
from langchain_openai import ChatOpenAI
from app.pipeline.state import PipelineState
from app.prompts.seo_prompts import SEO_SYSTEM, SEO_USER
from app.config import settings

logger = logging.getLogger(__name__)

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3, api_key=settings.openai_api_key)


def _make_slug(title: str) -> str:
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug[:80]


async def seo_agent(state: PipelineState) -> dict:
    """Generate SEO metadata from the blog draft."""
    run_id = state["run_id"]
    logger.info(f"[seo] run_id={run_id}")

    messages = [
        {"role": "system", "content": SEO_SYSTEM},
        {"role": "user",   "content": SEO_USER.format(
            topic=state["topic"],
            draft=state["draft"][:3000],
        )},
    ]

    try:
        response = await llm.ainvoke(messages)
        text = response.content.strip()

        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        data = json.loads(text)

        seo_title = data.get("title", state["topic"])[:60]
        seo_slug = _make_slug(data.get("slug", state["topic"]))
        meta_description = data.get("meta_description", "")[:155]
        focus_keywords = data.get("keywords", [])[:5]
        faq_section = data.get("faq_markdown", "")

        usage = response.response_metadata.get("token_usage", {})
        agent_cost = {
            "agent": "seo",
            "model": "gpt-4o-mini",
            "tokens_in": usage.get("prompt_tokens", 0),
            "tokens_out": usage.get("completion_tokens", 0),
            "cost": (usage.get("prompt_tokens", 0) * 0.00000015 +
                     usage.get("completion_tokens", 0) * 0.0000006),
        }

        logger.info(f"[seo] title='{seo_title}' slug='{seo_slug}'")
        return {
            "seo_title": seo_title,
            "seo_slug": seo_slug,
            "meta_description": meta_description,
            "focus_keywords": focus_keywords,
            "faq_section": faq_section,
            "agent_costs": state.get("agent_costs", []) + [agent_cost],
        }

    except Exception as e:
        logger.error(f"[seo] Failed: {e} — using defaults")
        return {
            "seo_title": state["topic"][:60],
            "seo_slug": _make_slug(state["topic"]),
            "meta_description": f"A comprehensive guide to {state['topic']} for developers.",
            "focus_keywords": [state["topic"]],
            "faq_section": "",
        }
