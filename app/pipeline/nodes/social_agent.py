from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from langchain_openai import ChatOpenAI

from app.pipeline.state import PipelineState, TweetDict
from app.prompts.social_prompts import SOCIAL_SYSTEM, SOCIAL_USER
from app.config import settings

logger = logging.getLogger(__name__)

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.5, api_key=settings.openai_api_key)

TMP_DIR = Path(__file__).parent.parent.parent.parent / "tmp"


async def _generate_tweets(state: PipelineState) -> tuple[list[TweetDict], str]:
    """Ask GPT-4o-mini to produce 5 tweets and an IG caption."""
    messages = [
        {"role": "system", "content": SOCIAL_SYSTEM},
        {"role": "user",   "content": SOCIAL_USER.format(
            topic=state["topic"],
            seo_title=state["seo_title"],
            draft=state["draft"][:4000],
        )},
    ]
    response = await llm.ainvoke(messages)
    text = response.content.strip()

    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]

    data = json.loads(text)
    raw_tweets = data.get("tweets", [])

    valid: list[TweetDict] = []
    for i, t in enumerate(raw_tweets[:5]):
        valid.append(TweetDict(
            num=i + 1,
            text=t.get("text", "")[:280],
        ))

    caption = data.get("insta_caption", "")
    return valid, caption


async def _render_tweets(tweets: list[TweetDict], run_id: str) -> list[str]:
    """
    Render each tweet to a 1080x1080 PNG using a separate Python subprocess.
    Returns list of absolute paths to generated PNG files.
    """
    import subprocess
    import json
    import sys
    
    script_path = Path(__file__).parent / "render_script.py"
    payload = json.dumps({"tweets": tweets, "run_id": run_id})
    
    proc = subprocess.run(
        [sys.executable, str(script_path)],
        input=payload,
        text=True,
        capture_output=True,
        timeout=60
    )
    
    if proc.returncode != 0:
        raise RuntimeError(f"Render script failed:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")
        
    result = {}
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                result = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    if not result:
        raise RuntimeError(f"No JSON found in output:\n{proc.stdout}")

    if result.get("status") == "error":
        raise RuntimeError(f"Playwright error inside script: {result.get('message')}")
        
    paths = result.get("paths", [])
    for path in paths:
        logger.info(f"[social] Rendered tweet screenshot → {Path(path).name}")
        
    return paths


async def social_agent(state: PipelineState) -> dict:
    """Generate tweet thread, then render to PNG screenshots."""
    run_id = state["run_id"]
    logger.info(f"[social] run_id={run_id}")

    caption = ""
    try:
        tweets, caption = await _generate_tweets(state)
        logger.info(f"[social] Generated {len(tweets)} tweets and caption")
    except Exception as e:
        logger.error(f"[social] Tweet generation failed: {e}")
        tweets = []

    paths: list[str] = []
    
    format_choice = state.get("image_format_choice", "carousel")

    if format_choice == "carousel":
        if tweets:
            try:
                paths = await _render_tweets(tweets, run_id)
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                logger.error(f"[social] Render failed: {tb} — will deliver text only to Telegram")
                errors = state.get("errors", []) + [f"Tweet render failed: {e}"]
                state["errors"] = errors
    elif format_choice == "screenshot":
        try:
            import datetime
            import subprocess
            import sys
            
            script_path = Path(__file__).parent / "render_script.py"
            now = datetime.datetime.now()
            payload = json.dumps({
                "type": "devblog_screenshot",
                "run_id": run_id,
                "seo_title": state.get("seo_title", "Untitled Post"),
                "date": f"{now.strftime('%b')} {now.day}, {now.year}",
                "thumbnail_url": state.get("youtube_thumbnail_url", ""),
                "views": 0,
                "read_time": max(1, len(state.get("draft", "").split()) // 200),
            })
            
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                input=payload,
                text=True,
                capture_output=True,
                timeout=60
            )
            
            if proc.returncode == 0:
                for line in reversed(proc.stdout.splitlines()):
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            result = json.loads(line)
                            paths = result.get("paths", [])
                            break
                        except json.JSONDecodeError:
                            continue
            else:
                logger.error(f"[social] Devblog render script failed: {proc.stderr}")
        except Exception as e:
            logger.error(f"[social] Devblog screenshot render failed: {e}")

    return {
        "tweets": tweets,
        "carousel_image_paths": paths,
        "insta_caption": caption,
        "errors": state.get("errors", []),
    }
