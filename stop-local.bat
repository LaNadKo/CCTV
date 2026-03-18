@echo off
chcp 65001 >nul
echo Stopping all services...
taskkill /FI "WINDOWTITLE eq CCTV-Backend*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq CCTV-Frontend*" /F >nul 2>&1
taskkill /IM ffmpeg.exe /F >nul 2>&1
docker compose stop db mediamtx
echo Done.
pause
