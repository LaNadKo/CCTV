@echo off
chcp 65001 >nul
echo ==========================================
echo   CCTV - Local Development Startup
echo ==========================================
echo.

:: ─── 1. PostgreSQL via Docker (lightweight) ───
echo [1/4] Starting PostgreSQL...
docker compose up -d db mediamtx
if errorlevel 1 (
    echo ERROR: Docker failed. Is Docker Desktop running?
    pause
    exit /b 1
)

:: Wait for DB to be ready
echo Waiting for PostgreSQL...
timeout /t 5 /nobreak >nul

:: ─── 2. Run migrations ───
echo [2/4] Running database migrations...
alembic upgrade head

:: ─── 3. Start Backend ───
echo [3/4] Starting Backend (port 8000)...
start "CCTV-Backend" cmd /k "cd /d %~dp0 && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

:: Wait a bit for backend
timeout /t 3 /nobreak >nul

:: ─── 4. Start Frontend ───
echo [4/4] Starting Frontend (port 5173)...
start "CCTV-Frontend" cmd /k "cd /d %~dp0\frontend && npm run dev"

echo.
echo ==========================================
echo   Ready!
echo.
echo   Frontend:  http://localhost:5173
echo   Backend:   http://localhost:8000
echo   DB:        localhost:5432
echo   MediaMTX:  rtsp://localhost:8554
echo.
echo   To stream webcams, run in a separate terminal:
echo   ffmpeg -f dshow -i video="USB2.0 HD UVC WebCam" -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p -f rtsp rtsp://localhost:8554/webcam
echo ==========================================
pause
