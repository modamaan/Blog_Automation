from __future__ import annotations

import logging
import re

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.pipeline.state import PipelineState
from app.config import settings
from app.tools.telegram_client import send_error_alert

logger = logging.getLogger(__name__)


def _draft_to_html(markdown: str) -> str:
    """
    Convert Markdown to simple HTML suitable for devblog.blog's content_html field.
    Handles: headings, bold, italic, code blocks, inline code, lists, paragraphs.
    """
    html = markdown

    # Fenced code blocks
    html = re.sub(
        r"```(\w+)?\n(.*?)```",
        lambda m: f'<pre><code class="language-{m.group(1) or ""}">{m.group(2)}</code></pre>',
        html,
        flags=re.DOTALL,
    )

    # Headings
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)

    # Images — must run before inline code (backticks)
    html = re.sub(
        r"!\[([^\]]*)\]\(([^)]+)\)",
        r'<img src="\2" alt="\1" style="width:100%;height:auto;display:block;margin:2rem auto;border-radius:8px;box-shadow:0 2px 12px rgba(0,0,0,0.12)">',
        html,
    )

    # Bold and italic
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)
    html = re.sub(r"`(.+?)`", r"<code>\1</code>", html)

    # Unordered lists
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"(<li>.*</li>\n?)+", r"<ul>\g<0></ul>", html, flags=re.DOTALL)

    # Blockquotes
    html = re.sub(
        r"^>\s+(.+)$", r"<blockquote>\1</blockquote>", html, flags=re.MULTILINE
    )

    # Paragraphs (blank-line separated)
    paragraphs = re.split(r"\n\n+", html)
    parts = []

    BLOCK_ELEMENTS = (
        "<h1",
        "<h2",
        "<h3",
        "<h4",
        "<h5",
        "<h6",
        "<ul",
        "<ol",
        "<li",
        "<pre",
        "<blockquote",
        "<img",
        "<p",
        "<div",
    )

    for p in paragraphs:
        p = p.strip()
        if p and not p.startswith(BLOCK_ELEMENTS):
            p = f"<p>{p}</p>"
        parts.append(p)

    return "\n".join(parts)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def _post_to_devblog(
    title: str,
    content_html: str,
    content_text: str,
    faq: str,
    banner_image: str | None = None,
) -> dict:
    """Call the devblog POST /api/posts endpoint."""
    # Append FAQ section to HTML if present
    full_html = content_html
    if faq:
        full_html += "\n\n" + _draft_to_html(faq)

    payload: dict = {
        "title": title,
        "content_html": full_html,
        "content_text": content_text,
        "publish": True,
    }
    if banner_image:
        payload["banner_image"] = banner_image

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            settings.devblog_posts_url,
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.devblog_api_secret_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
        )
        resp.raise_for_status()
        return resp.json()


def _draft_to_text(markdown: str) -> str:
    """Strip markdown to produce clean plain text for the excerpt."""
    text = markdown
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)  # Code blocks
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)             # Images
    text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)  # Headings
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)            # Bold
    text = re.sub(r"\*(.*?)\*", r"\1", text)                # Italic
    text = re.sub(r"_(.*?)_", r"\1", text)                  # Italic
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)   # Links
    text = re.sub(r"`(.*?)`", r"\1", text)                  # Inline code
    text = text.replace("\n", " ")                          # Newlines to spaces
    return re.sub(r"\s+", " ", text).strip()


async def publisher_agent(state: PipelineState) -> dict:
    """Publish the approved blog post to devblog.blog via REST API."""
    run_id = state["run_id"]
    logger.info(f"[publisher] run_id={run_id} — publishing to devblog.blog")

    title = state.get("seo_title") or state.get("topic", "Untitled")
    draft = state.get("draft", "")
    faq = state.get("faq_section", "")
    banner_image = state.get("youtube_thumbnail_url")  # None for non-YT topics

    content_html = _draft_to_html(draft)
    content_text = _draft_to_text(draft)

    try:
        result = await _post_to_devblog(
            title, content_html, content_text, faq, banner_image
        )
        post = result.get("post", {})
        post_id = str(post.get("id", ""))
        post_url = f"{settings.devblog_base_url}/{post.get('slug', '')}"

        logger.info(f"[publisher] Published: {post_url}")
        return {
            "blog_post_id": post_id,
            "blog_post_url": post_url,
        }

    except httpx.HTTPStatusError as e:
        error_msg = f"API Error {e.response.status_code}: {e.response.text}"
        logger.error(f"[publisher] {error_msg}")
        await send_error_alert(
            settings.telegram_chat_id,
            run_id,
            f"Publisher failed with status code {e.response.status_code}:\n\n{e.response.text[:500]}",
        )
        return {
            "blog_post_id": None,
            "blog_post_url": None,
            "errors": state.get("errors", []) + [error_msg],
        }
    except Exception as e:
        logger.error(f"[publisher] Failed to publish: {e}")
        await send_error_alert(
            settings.telegram_chat_id,
            run_id,
            f"Publisher failed: {e}",
        )
        return {
            "blog_post_id": None,
            "blog_post_url": None,
            "errors": state.get("errors", []) + [f"Publisher error: {e}"],
        }
