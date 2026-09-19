from __future__ import annotations

import logging
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{settings.telegram_bot_token}"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
async def send_text(chat_id: str, text: str, parse_mode: str = "Markdown") -> int:
    """Send a text message. Returns message_id."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
        )
        resp.raise_for_status()
        return resp.json()["result"]["message_id"]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
async def send_photo(chat_id: str, image_path: str, caption: str = "") -> int:
    """Send a photo file. Returns message_id."""
    async with httpx.AsyncClient(timeout=60) as client:
        with open(image_path, "rb") as f:
            resp = await client.post(
                f"{TELEGRAM_API}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "Markdown"},
                files={"photo": (Path(image_path).name, f, "image/png")},
            )
        resp.raise_for_status()
        return resp.json()["result"]["message_id"]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
async def send_approval_buttons(chat_id: str, run_id: str, topic: str) -> int:
    """Send the Approve/Reject inline keyboard. Returns message_id."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": f"📝 <b>Blog post ready for review</b>\n\n<b>Topic:</b> {topic}\n\nApprove to publish to devblog.blog",
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [[
                        {
                            "text": "✅ Approve & Publish",
                            "callback_data": f"approve:{run_id}",
                        },
                        {
                            "text": "❌ Reject",
                            "callback_data": f"reject:{run_id}",
                        },
                    ]]
                },
            },
        )
        resp.raise_for_status()
        return resp.json()["result"]["message_id"]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
async def send_image_choice_buttons(chat_id: str, run_id: str, topic: str) -> int:
    """Send the format choice inline keyboard. Returns message_id."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": f"🎨 <b>Choose Instagram Format</b>\n\n<b>Topic:</b> {topic}\n\nSelect the visual style you want to generate:",
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [[
                        {
                            "text": "🎠 Twitter Carousel",
                            "callback_data": f"carousel:{run_id}",
                        },
                        {
                            "text": "🖥️ DevBlog Screenshot",
                            "callback_data": f"screenshot:{run_id}",
                        },
                    ]]
                },
            },
        )
        resp.raise_for_status()
        return resp.json()["result"]["message_id"]



async def send_error_alert(chat_id: str, run_id: str, error: str) -> None:
    """Send an error notification (best-effort, no retry)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{TELEGRAM_API}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": f"🚨 *Pipeline Error*\n\n`run_id`: `{run_id}`\n\n```\n{error[:500]}\n```",
                    "parse_mode": "Markdown",
                },
            )
    except Exception as e:
        logger.error(f"Failed to send Telegram error alert: {e}")


async def send_success_summary(chat_id: str, topic: str, url: str, cost: float) -> None:
    """Send a success summary after publish."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{TELEGRAM_API}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": (
                        f"✅ <b>Published!</b>\n\n"
                        f"📌 <b>{topic}</b>\n"
                        f"🔗 {url}\n"
                        f"💰 Cost: ${cost:.3f}"
                    ),
                    "parse_mode": "HTML",
                },
            )
    except Exception as e:
        logger.error(f"Failed to send success summary: {e}")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
async def send_media_group(chat_id: str, image_paths: list[str], caption: str = "") -> list[int]:
    """Send multiple photos as an album (MediaGroup). Returns list of message_ids."""
    if not image_paths:
        return []

    media = []
    files = {}

    for i, path in enumerate(image_paths[:10]):  # Telegram limit is 10
        attach_name = f"photo{i}"
        media_item = {"type": "photo", "media": f"attach://{attach_name}"}
        # Add caption to the first image in the group
        if i == 0 and caption:
            media_item["caption"] = caption[:1024]
            media_item["parse_mode"] = "HTML"
        media.append(media_item)
        
        # We must keep the file descriptors open during the request
        files[attach_name] = (Path(path).name, open(path, "rb"), "image/png")

    try:
        import json
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{TELEGRAM_API}/sendMediaGroup",
                data={"chat_id": chat_id, "media": json.dumps(media)},
                files=files,
            )
            resp.raise_for_status()
            
            # The API returns an array of Message objects
            return [msg["message_id"] for msg in resp.json()["result"]]
    finally:
        # Close all opened files
        for file_tuple in files.values():
            file_tuple[1].close()
