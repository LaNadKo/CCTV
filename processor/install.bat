@echo off
chcp 65001 >nul
title CCTV Processor — Installer
setlocal enabledelayedexpansion

echo === CCTV Processor — Installer ===
echo.

:: ── Check Python ──
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set PY_VERSION=%%v
echo Python: %PY_VERSION%

:: ── Check GPU ──
set TORCH_INDEX=https://download.pytorch.org/whl/cpu
where nvidia-smi >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=*" %%g in ('nvidia-smi --query-gpu=name --format=csv,noheader 2^>nul') do set GPU_NAME=%%g
    echo GPU:    !GPU_NAME!
    echo         Installing CUDA-enabled PyTorch
    set TORCH_INDEX=https://download.pytorch.org/whl/cu124
) else (
    echo GPU:    not detected ^(CPU mode^)
)
echo.

:: ── Create venv ──
echo [1/3] Creating virtual environment...
python -m venv "%~dp0venv"
call "%~dp0venv\Scripts\activate.bat"
pip install --upgrade pip -q

:: ── Install PyTorch ──
echo [2/3] Installing PyTorch (this may take a few minutes)...
pip install torch torchvision --index-url %TORCH_INDEX% -q

:: ── Install dependencies ──
echo [3/3] Installing dependencies...
pip install -r "%~dp0requirements.txt" -q

echo.
echo === Installation complete ===
echo.

:: ── Create .env if not exists ──
if not exist "%~dp0.env" (
    copy "%~dp0.env.example" "%~dp0.env" >nul
    echo Created .env from template.
    echo.

    set /p BACKEND_URL="Server URL (e.g. https://cctv.example.com): "
    set /p API_KEY_VAL="API key: "
    for /f "tokens=*" %%h in ('hostname') do set DEFAULT_NAME=%%h
    set PROC_NAME=!DEFAULT_NAME!
    set /p PROC_NAME="Processor name [!DEFAULT_NAME!]: "

    :: Write .env
    (
        echo BACKEND_URL=!BACKEND_URL!
        echo API_KEY=!API_KEY_VAL!
        echo PROCESSOR_NAME=!PROC_NAME!
        echo MAX_WORKERS=4
        echo POLL_INTERVAL=10
        echo HEARTBEAT_INTERVAL=30
    ) > "%~dp0.env"

    echo.
)

:: ── Create run.bat ──
(
    echo @echo off
    echo call "%%~dp0venv\Scripts\activate.bat"
    echo cd /d "%%~dp0.."
    echo python -m processor.main
    echo pause
) > "%~dp0run.bat"

:: ── Create run-gui.bat ──
(
    echo @echo off
    echo call "%%~dp0venv\Scripts\activate.bat"
    echo cd /d "%%~dp0"
    echo python launcher.py
) > "%~dp0run-gui.bat"

echo.
echo ── Run manually ──
echo   %~dp0run.bat
echo.
echo ── Run with GUI ──
echo   %~dp0run-gui.bat
echo.
echo ── Auto-start on Windows ──
echo   1. Press Win+R, type: shell:startup
echo   2. Create shortcut to: %~dp0run.bat
echo.
pause
