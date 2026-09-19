import logging
from app.pipeline.state import PipelineState
from app.tools.telegram_client import send_media_group
from app.config import settings

logger = logging.getLogger(__name__)

async def instagram_delivery_node(state: PipelineState) -> dict:
    """Send the generated Instagram Carousel and caption to Telegram."""
    run_id = state["run_id"]
    logger.info(f"[instagram_delivery] run_id={run_id}")

    images = state.get("carousel_image_paths", [])
    caption = state.get("insta_caption", "")

    if not images:
        logger.warning(f"[instagram_delivery] No carousel images to send for run_id={run_id}")
        return {}

    try:
        # We prefix the caption so the user knows what this is
        msg = f"📱 <b>Instagram Ready!</b>\n\n{caption}"
        await send_media_group(settings.telegram_chat_id, images, caption=msg)
        logger.info(f"[instagram_delivery] Successfully delivered {len(images)} slides to Telegram")
    except Exception as e:
        logger.error(f"[instagram_delivery] Failed to send to Telegram: {e}")

    return {}
