Write-Host "Starting Docker Compose services..." -ForegroundColor Green
docker-compose up -d

Write-Host "`nStarting FastAPI application..." -ForegroundColor Green
.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --reload
