from __future__ import annotations

import logging
from app.pipeline.state import PipelineState
from app.tools import telegram_client
from app.config import settings

logger = logging.getLogger(__name__)

CHAT_ID = settings.telegram_chat_id


def _format_preview(state: PipelineState) -> str:
    """Format the blog preview message for Telegram."""
    draft = state.get("draft", "")
    preview = draft[:1800] + ("..." if len(draft) > 1800 else "")

    return (
        f"📊 *SEO Preview*\n"
        f"Title: `{state.get('seo_title', '')}`\n"
        f"Slug: `{state.get('seo_slug', '')}`\n"
        f"Meta: _{state.get('meta_description', '')}_\n"
        f"Keywords: {', '.join(state.get('focus_keywords', []))}\n\n"
        f"📝 *Blog Draft Preview*\n\n"
        f"{preview}"
    )


async def telegram_delivery_node(state: PipelineState) -> dict:
    """
    Sends the blog preview + carousel slides to Telegram, then
    sends approval buttons. Sets approval_status = "pending".

    The graph pauses at interrupt_before=["publisher"] — it will NOT proceed
    until the /pipeline/callback endpoint is called with approval or rejection.
    """
    run_id = state["run_id"]
    topic = state.get("topic", "Unknown topic")
    logger.info(f"[telegram] run_id={run_id} — sending preview")

    message_ids: list[int] = []

    try:
        # Message 1: SEO summary + draft preview
        preview_text = _format_preview(state)
        msg_id = await telegram_client.send_text(CHAT_ID, preview_text)
        message_ids.append(msg_id)
        logger.info(f"[telegram] Sent preview message id={msg_id}")

        # Message 2: Twitter screenshots
        image_paths = state.get("carousel_image_paths", [])
        if image_paths:
            if len(image_paths) == 1:
                logger.info(f"[telegram] Sending 1 screenshot...")
                msg_id = await telegram_client.send_photo(CHAT_ID, image_paths[0])
                message_ids.append(msg_id)
                logger.info(f"[telegram] Sent screenshot msg_id={msg_id}")
            else:
                logger.info(f"[telegram] Sending {len(image_paths)} tweet screenshots...")
                msg_ids = await telegram_client.send_media_group(CHAT_ID, image_paths)
                message_ids.extend(msg_ids)
                logger.info(f"[telegram] Sent tweet screenshots msg_ids={msg_ids}")
        # Message 3: Instagram Caption
        caption = state.get("insta_caption", "")
        if caption:
            msg_id = await telegram_client.send_text(CHAT_ID, f"📸 *Instagram Caption (Copy-Paste)*\n\n{caption}")
            message_ids.append(msg_id)
            logger.info(f"[telegram] Sent insta caption msg_id={msg_id}")

        # Final message: approval buttons
        btn_id = await telegram_client.send_approval_buttons(CHAT_ID, run_id, topic)
        message_ids.append(btn_id)
        logger.info(f"[telegram] Sent approval buttons — waiting for human response")

    except Exception as e:
        logger.error(f"[telegram] Delivery failed: {e}")
        # Even on failure, set pending so the graph doesn't immediately proceed
        return {
            "telegram_message_ids": message_ids,
            "approval_status": "pending",
            "errors": state.get("errors", []) + [f"Telegram delivery error: {e}"],
        }

    return {
        "telegram_message_ids": message_ids,
        "approval_status": "pending",
    }
