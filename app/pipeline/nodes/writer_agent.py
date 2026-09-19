from __future__ import annotations

import logging
from langchain_openai import ChatOpenAI
from app.pipeline.state import PipelineState
from app.prompts.writer_prompts import WRITER_SYSTEM, WRITER_USER
from app.config import settings

logger = logging.getLogger(__name__)

llm = ChatOpenAI(model="gpt-4o", temperature=0.7, api_key=settings.openai_api_key)


async def writer_agent(state: PipelineState) -> dict:
    """Write the full Markdown blog post from outline + research notes."""
    run_id = state["run_id"]
    retries = state.get("writer_retries", 0)
    logger.info(f"[writer] run_id={run_id} attempt={retries + 1}")

    # Include previous fact-check issues if this is a retry
    fact_issues_text = ""
    if state.get("fact_issues"):
        fact_issues_text = (
            "\n\nPREVIOUS FACT-CHECK ISSUES TO FIX:\n"
            + "\n".join(f"- {issue}" for issue in state["fact_issues"])
        )

    images_text = ""

    messages = [
        {"role": "system", "content": WRITER_SYSTEM.format(genre=state.get("genre", "Tutorial"))},
        {"role": "user",   "content": WRITER_USER.format(
            topic=state["topic"],
            genre=state.get("genre", "Tutorial"),
            outline="\n".join(state["outline"]),
            research=state["research_notes"],
            key_facts="\n".join(f"- {f}" for f in state.get("key_facts", [])),
            fact_issues=fact_issues_text,
            images=images_text,
        )},
    ]

    response = await llm.ainvoke(messages)
    draft = response.content.strip()

    usage = response.response_metadata.get("token_usage", {})
    agent_cost = {
        "agent": "writer",
        "model": "gpt-4o",
        "tokens_in": usage.get("prompt_tokens", 0),
        "tokens_out": usage.get("completion_tokens", 0),
        "cost": (usage.get("prompt_tokens", 0) * 0.0000025 +
                 usage.get("completion_tokens", 0) * 0.000010),
    }

    word_count = len(draft.split())
    logger.info(f"[writer] Draft: {word_count} words")

    return {
        "draft": draft,
        "word_count": word_count,
        "writer_retries": retries + 1,
        "fact_check_passed": False,   # reset for fact checker
        "fact_issues": [],
        "agent_costs": state.get("agent_costs", []) + [agent_cost],
    }
