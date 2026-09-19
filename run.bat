@echo off
echo Starting Docker Compose services...
docker-compose up -d

echo.
echo Starting FastAPI application...
.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --reload
