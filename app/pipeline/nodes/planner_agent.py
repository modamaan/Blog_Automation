from __future__ import annotations

import logging
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from app.pipeline.state import PipelineState
from app.prompts.planner_prompts import PLANNER_SYSTEM, PLANNER_USER
from app.config import settings

logger = logging.getLogger(__name__)

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3, api_key=settings.openai_api_key)

class PlannerOutput(BaseModel):
    genre: str = Field(description="One of: 'Tutorial', 'SaaS Story', 'Tech News', 'Tool Review'")
    outline: list[str] = Field(description="List of 5-7 markdown headings starting with ##")


async def planner_agent(state: PipelineState) -> dict:
    """Generate a structured blog outline from research notes."""
    run_id = state["run_id"]
    logger.info(f"[planner] run_id={run_id}")

    messages = [
        {"role": "system", "content": PLANNER_SYSTEM},
        {"role": "user",   "content": PLANNER_USER.format(
            topic=state["topic"],
            research=state["research_notes"][:3000],  # keep prompt lean
        )},
    ]

    try:
        structured_llm = llm.with_structured_output(PlannerOutput)
        response: PlannerOutput = await structured_llm.ainvoke(messages)

        # Fallback tracking costs (with_structured_output often hides raw token usage, but we can do a rough estimate or skip for now)
        # We will assume a fixed small cost or grab if possible. Since with_structured_output doesn't return response_metadata easily, we'll log a static tiny cost.
        agent_cost = {
            "agent": "planner",
            "model": "gpt-4o-mini",
            "tokens_in": len(state["research_notes"]) // 4,
            "tokens_out": 200,
            "cost": 0.0,
        }

        logger.info(f"[planner] Decided genre: {response.genre} | Sections: {len(response.outline)}")
        return {
            "outline": response.outline,
            "genre": response.genre,
            "agent_costs": state.get("agent_costs", []) + [agent_cost],
        }

    except Exception as e:
        logger.error(f"[planner] Failed: {e} — using fallback")
        return {
            "outline": ["## Introduction", "## Deep Dive", "## Conclusion"],
            "genre": "Tech News",
        }
