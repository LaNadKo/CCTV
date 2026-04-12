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
set GPU_PACKAGES=
set CPU_PACKAGES=onnxruntime==1.15.1 mmdeploy-runtime==1.3.1
where nvidia-smi >nul 2>&1
if %errorlevel%==0 (
    for /f "tokens=*" %%g in ('nvidia-smi --query-gpu=name --format=csv,noheader 2^>nul') do set GPU_NAME=%%g
    echo GPU:    !GPU_NAME!
    echo         Installing CUDA runtimes for ONNX/MMDeploy
    set GPU_PACKAGES=onnxruntime-gpu==1.15.1 mmdeploy-runtime-gpu==1.3.1 nvidia-cuda-runtime-cu11==11.8.89 nvidia-cublas-cu11==11.11.3.6 nvidia-cudnn-cu11==8.9.5.29 nvidia-cuda-nvrtc-cu11==11.8.89 nvidia-cufft-cu11==10.9.0.58 nvidia-curand-cu11==10.3.0.86
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
echo [2/3] Installing dependencies...

:: ── Install dependencies ──
pip install -r "%~dp0requirements.txt" -q
if defined GPU_PACKAGES (
    echo [3/3] Installing GPU runtimes...
    pip uninstall -y onnxruntime mmdeploy-runtime >nul 2>&1
    pip install %GPU_PACKAGES% -q
    python "%~dp0prepare_gpu_runtime.py"
) else (
    echo [3/3] Installing CPU runtimes...
    pip uninstall -y onnxruntime-gpu mmdeploy-runtime-gpu >nul 2>&1
    pip install %CPU_PACKAGES% -q
)

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
