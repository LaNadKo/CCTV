@echo off
chcp 65001 >nul
echo === Starting all services in Docker ===
echo.
echo Building and starting containers...
docker compose up --build -d
echo.
echo === Done! ===
echo Backend:  http://localhost:8000
echo Swagger:  http://localhost:8000/docs
echo Frontend: http://localhost:5173
echo.
echo To stop: docker compose down
pause
