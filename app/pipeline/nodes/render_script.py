import asyncio
import json
import sys
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

TMP_DIR = Path(__file__).parent.parent.parent.parent / "tmp"
TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "carousel" / "templates"

async def _render_tweets(tweets: list, run_id: str) -> list[str]:
    from playwright.async_api import async_playwright

    out_dir = TMP_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    paths = []

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        # Use a square viewport for Twitter threads on IG
        page = await browser.new_page(viewport={"width": 1080, "height": 1080})

        try:
            template = env.get_template("tweet_screenshot.html")
        except Exception as e:
            raise RuntimeError(f"Could not load tweet_screenshot.html: {e}")

        for tweet in tweets:
            html = template.render(
                text=tweet["text"],
                tweet_num=tweet["num"],
                total_tweets=len(tweets),
            )

            html_path = out_dir / f"tweet_{tweet['num']}.html"
            html_path.write_text(html, encoding="utf-8")

            await page.goto(f"file:///{html_path.as_posix()}")
            await page.wait_for_load_state("networkidle")

            png_path = out_dir / f"tweet_{tweet['num']}.png"
            await page.screenshot(path=str(png_path), clip={"x": 0, "y": 0, "width": 1080, "height": 1080})
            paths.append(str(png_path))

        await browser.close()
    return paths

async def _render_devblog_screenshot(payload: dict, run_id: str) -> list[str]:
    from playwright.async_api import async_playwright

    out_dir = TMP_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    paths = []

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        # User requested 1080x1350 portrait format
        page = await browser.new_page(viewport={"width": 1080, "height": 1350})

        try:
            template = env.get_template("devblog_mockup.html")
        except Exception as e:
            raise RuntimeError(f"Could not load devblog_mockup.html: {e}")

        html = template.render(
            seo_title=payload.get("seo_title", ""),
            date=payload.get("date", ""),
            thumbnail_url=payload.get("thumbnail_url", ""),
            views=payload.get("views", 0),
            read_time=payload.get("read_time", 3),
        )

        html_path = out_dir / f"devblog_screenshot.html"
        html_path.write_text(html, encoding="utf-8")

        await page.goto(f"file:///{html_path.as_posix()}")
        await page.wait_for_load_state("networkidle")

        png_path = out_dir / f"devblog_screenshot.png"
        await page.screenshot(path=str(png_path), clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
        paths.append(str(png_path))

        await browser.close()
    return paths


def main():
    # Read JSON payload from stdin
    input_data = sys.stdin.read()
    payload = json.loads(input_data)
    run_id = payload.get("run_id", "default_run")
    render_type = payload.get("type", "carousel")

    try:
        if render_type == "carousel":
            tweets = payload.get("tweets", [])
            paths = asyncio.run(_render_tweets(tweets, run_id))
        elif render_type == "devblog_screenshot":
            paths = asyncio.run(_render_devblog_screenshot(payload, run_id))
        else:
            raise ValueError(f"Unknown render type: {render_type}")

        print(json.dumps({"status": "success", "paths": paths}))
    except Exception as e:
        import traceback
        print(json.dumps({"status": "error", "message": traceback.format_exc()}))

if __name__ == "__main__":
    main()
