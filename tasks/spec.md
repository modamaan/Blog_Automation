# Spec: n8n + ngrok Webhook Architecture

## Objective
Migrate the Telegram trigger mechanism from the custom Python-based polling script (`telegram_poller.py`) back to **n8n** using **ngrok** to expose local webhooks. This will provide a visual, robust workflow that handles Telegram updates instantly via push (webhooks) rather than pull (polling), avoiding Windows background process conflicts and improving debuggability.

## Assumptions I'm Making:
1. You are okay with keeping an `ngrok` terminal running alongside your Docker containers during development.
2. We will completely remove `telegram_poller.py` to prevent any future conflicts.
3. n8n will be the sole entry point for Telegram messages, and it will forward the YouTube URLs to our existing FastAPI pipeline (`http://host.docker.internal:8000/pipeline/run`).
**→ Correct me now if any of these are wrong!**

## Tech Stack
- **n8n** (Running in Docker)
- **ngrok** (Running locally to expose port 5678)
- **FastAPI** (Existing backend for AI logic)
- **Telegram Bot API** (Configured via webhook)

## Commands
- Run infrastructure: `docker-compose up -d postgres redis n8n`
- Run backend: `.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --reload`
- Expose n8n: `ngrok http 5678`

## Project Structure Changes
- `[DELETE]` `app/tools/telegram_poller.py` (Obsolete)
- `[MODIFY]` `docker-compose.yml` (Uncomment and restore `n8n`)
- `[MODIFY]` `run.ps1` / `run.bat` (Update to include `n8n` in startup)

## Verification / Success Criteria
- Sending a YouTube URL to the bot in Telegram triggers the n8n workflow instantly.
- n8n successfully parses the text and makes an HTTP POST request to our FastAPI backend.
- The FastAPI backend receives the request and generates the blog post.

## Open Questions
1. **ngrok account:** Do you already have ngrok installed on your machine and authenticated with your account? (ngrok requires a free account to use).
2. **n8n workflow:** Are you comfortable importing a small JSON workflow file into n8n to set up the Telegram node and the HTTP node that connects to FastAPI?
