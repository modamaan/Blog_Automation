# DevBlog Autonomous Pipeline

This repository contains the backend for an autonomous blog content generation pipeline. Powered by FastAPI and LangGraph, it features a series of intelligent AI agents that work together to find trending topics, research, write, fact-check, optimize for SEO, generate social media posts, and publish the final blog post.

It also integrates with Telegram for a Human-in-the-Loop (HITL) review process and uses n8n for workflow automation.

## 🚀 Tech Stack

- **Framework**: FastAPI (for the REST API)
- **Agent Orchestration**: LangGraph (for stateful multi-agent workflows)
- **Database**: PostgreSQL (for storing pipeline runs and states)
- **Checkpointer**: Redis (for LangGraph state persistence)
- **Automation**: n8n (for triggering pipelines and handling webhook callbacks)
- **Containerization**: Docker Compose
- **LLM**: OpenAI GPT models
- **Human-in-the-Loop**: Telegram Bot API

## 🤖 The Agents (LangGraph Workflow)

The pipeline is organized as a directed graph where data flows seamlessly from one specialized agent to another.

1. **Trend Agent**: Identifies currently trending topics relevant to the blog's niche.
2. **Research Agent**: Gathers structured notes, key facts, and references based on the chosen topic.
3. **Planner Agent**: Generates a comprehensive blog outline and selects a suitable genre (e.g., Tutorial, Tech News).
4. **Writer Agent**: Writes the initial Markdown draft based on the research and outline.
5. **Fact Checker Agent**: Reviews the draft for accuracy. If it fails, the Writer Agent is prompted to retry (up to 2 times).
6. **SEO Agent**: Generates an SEO-optimized title, URL slug, meta description, focus keywords, and an FAQ section.
7. **Image Choice Node**: Temporarily pauses the pipeline, waiting for the user to select an image format preference (e.g., carousel or screenshot).
8. **Social Agent**: Crafts tailored social media content (Twitter threads, Instagram captions, and visual assets).
9. **Telegram Delivery Node**: Sends the finalized draft and assets to a designated Telegram chat for human review, pausing the graph execution.
10. **Publisher Agent**: Automatically publishes the blog post to the Next.js DevBlog via REST API if the human reviewer approves.
11. **Analytics Agent**: Logs token usage, estimates costs, and records the final status of the pipeline run.

## ⚙️ How Automation Works

The entire pipeline can run fully autonomously or semi-autonomously using **n8n** and **Telegram**.

- **n8n Workflows**: Included in the `n8n/workflows` directory is `blog_pipeline.json` which can be imported into your local n8n instance. This workflow can be configured to run on a cron schedule (e.g., every morning) to automatically trigger a new blog generation run by hitting the FastAPI `/pipeline` endpoint.
- **Human-in-the-Loop (Telegram)**: Once the draft is ready, it is sent to your Telegram. You can approve or reject the post directly from the Telegram chat. 
  - If approved, the pipeline resumes and the Publisher Agent pushes the post to your live site.
  - If rejected, the pipeline logs the rejection and terminates cleanly.

## 🛠️ Setup & Installation

### 1. Environment Variables

Copy the `.env.example` file to `.env`:

```bash
cp .env.example .env
```

Fill in your configuration details:
- `OPENAI_API_KEY`: Your OpenAI API key.
- `DEVBLOG_BASE_URL` & `DEVBLOG_API_SECRET_KEY`: Connection details to your frontend blog.
- `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID`: To receive drafts for approval.

### 2. Start Infrastructure

Start the required services (PostgreSQL, Redis, and n8n) using Docker Compose:

```bash
docker-compose up -d
```

### 3. Run the FastAPI Server

A convenience script `run.ps1` (for Windows) or `run.bat` is provided. Alternatively, start the server manually:

```bash
# Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn app.main:app --host 0.0.0.0 --reload
```
or simply run:
```powershell
.\run.ps1
```

The API will be available at `http://localhost:8000`. You can view the Swagger documentation at `http://localhost:8000/docs`.

## 📂 Project Structure

- `/app`
  - `main.py`: FastAPI application entrypoint.
  - `config.py`: Environment variable validation and settings.
  - `/pipeline`: LangGraph implementation.
    - `graph.py`: Defines the flow and routing of the agents.
    - `state.py`: Defines the `PipelineState` passed between agents.
    - `/nodes`: Contains the logic for each individual agent (e.g., `trend_agent.py`, `writer_agent.py`).
  - `/routers`: API endpoints for triggering the pipeline and handling Telegram callbacks.
  - `/db`: Database connection and models.
- `/n8n`: Contains exportable workflows for automation.
- `docker-compose.yml`: Infrastructure orchestration.
