@echo off
chcp 65001 >nul
echo === Zapusk PostgreSQL v Docker ===
docker compose up -d db
echo.
echo DB running on localhost:5432
echo Waiting for readiness...
timeout /t 5 /nobreak >nul
echo Done!
pause
