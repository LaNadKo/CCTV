@echo off
chcp 65001 >nul
echo ========================================
echo   CCTV Console - Full Startup
echo ========================================
echo.

echo [1/3] Starting Docker services (DB, Backend, Frontend, Processor, MediaMTX)...
docker compose up -d --build
if errorlevel 1 (
    echo ERROR: Docker compose failed. Is Docker Desktop running?
    pause
    exit /b 1
)

echo.
echo [2/3] Waiting for MediaMTX to start...
timeout /t 5 /nobreak >nul

echo.
echo [3/3] Starting webcam streams via FFmpeg...
echo.

echo Starting webcam 1 (USB2.0 HD UVC WebCam)...
start "Webcam1-FFmpeg" cmd /c "ffmpeg -f dshow -i video="USB2.0 HD UVC WebCam" -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p -f rtsp rtsp://localhost:8554/webcam"

echo Starting webcam 2 (USB Video Device)...
start "Webcam2-FFmpeg" cmd /c "ffmpeg -f dshow -i video="USB Video Device" -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p -f rtsp rtsp://localhost:8554/webcam2"

echo.
echo ========================================
echo   All services started!
echo.
echo   Frontend:  http://localhost:5173
echo   Backend:   http://localhost:8000
echo   MediaMTX:  rtsp://localhost:8554
echo.
echo   Webcam RTSP URLs (use in camera settings):
echo     rtsp://host.docker.internal:8554/webcam
echo     rtsp://host.docker.internal:8554/webcam2
echo.
echo   To stop: docker compose down
echo   FFmpeg windows can be closed manually (Ctrl+C)
echo ========================================
pause
