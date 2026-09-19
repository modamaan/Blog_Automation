# Implementation Plan: Migration to n8n + ngrok

## Overview
We are reverting the Telegram trigger architecture back to an n8n-based webhook approach. This eliminates the custom polling script (`telegram_poller.py`), which frequently left phantom Python processes running in the background on Windows and caused `409 Conflict` errors. Using n8n and ngrok provides a robust, visual webhook pipeline.

## Architecture Decisions
- **n8n as entrypoint:** n8n will receive Telegram messages via webhook using ngrok.
- **FastAPI as backend:** n8n will forward the YouTube URLs to our existing FastAPI `/pipeline/run` endpoint.
- **ngrok for local dev:** ngrok will expose n8n to the internet so Telegram can push updates to it.

## Task List

### Phase 1: Foundation (Cleanup & Config)
- [ ] Task 1: Clean up `app/main.py`
  - Acceptance: `poll_telegram_updates` is no longer imported or run at startup.
  - Verify: Build/startup succeeds without error.
  - Files: `app/main.py`
- [ ] Task 2: Delete Poller Script
  - Acceptance: `app/tools/telegram_poller.py` is completely removed.
  - Verify: File is deleted.
  - Files: `app/tools/telegram_poller.py`
- [ ] Task 3: Restore n8n in Docker Compose
  - Acceptance: `n8n` is uncommented in `docker-compose.yml`.
  - Verify: `docker-compose config` is valid.
  - Files: `docker-compose.yml`
- [ ] Task 4: Restore n8n in Run Scripts
  - Acceptance: `run.ps1` and `run.bat` run `docker-compose up -d` without restricting it to only postgres and redis.
  - Verify: Scripts execute correctly.
  - Files: `run.ps1`, `run.bat`

### Phase 2: n8n Configuration & Handoff
- [ ] Task 5: User Handoff for n8n Setup
  - Acceptance: Provide the user with a JSON workflow file to import into n8n and instructions on starting ngrok.
  - Verify: User confirms n8n is receiving webhooks.

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| ngrok timeout | Med | Use static ngrok domain if available, or update n8n Telegram node when ngrok restarts. |

## Open Questions
- None. Proceeding to implementation upon review!
