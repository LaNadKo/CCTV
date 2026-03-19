@echo off
chcp 65001 >nul
echo Stopping FFmpeg processes...
taskkill /FI "WINDOWTITLE eq Webcam1-FFmpeg*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Webcam2-FFmpeg*" /F >nul 2>&1
taskkill /IM ffmpeg.exe /F >nul 2>&1

echo Stopping Docker services...
docker compose down

echo All stopped.
pause
