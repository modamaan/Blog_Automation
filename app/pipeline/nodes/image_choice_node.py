from __future__ import annotations

import logging
from app.pipeline.state import PipelineState
from app.tools import telegram_client
from app.config import settings

logger = logging.getLogger(__name__)

async def image_choice_node(state: PipelineState) -> dict:
    """
    Sends a Telegram message asking the user to choose the image format
    (Carousel vs Screenshot). Sets image_choice_status = "pending".
    The graph will pause after this node until the webhook sets it to "completed".
    """
    run_id = state["run_id"]
    topic = state.get("topic", "Unknown topic")
    logger.info(f"[image_choice] run_id={run_id} — sending format selection buttons")

    try:
        await telegram_client.send_image_choice_buttons(
            settings.telegram_chat_id, 
            run_id, 
            topic
        )
    except Exception as e:
        logger.error(f"[image_choice] Delivery failed: {e}")
        return {
            "image_choice_status": "pending",
            "errors": state.get("errors", []) + [f"Telegram format choice delivery error: {e}"],
        }

    return {
        "image_choice_status": "pending",
    }
