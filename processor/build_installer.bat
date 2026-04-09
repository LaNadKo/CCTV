@echo off
echo ============================================
echo   CCTV Processor - Full Build + Installer
echo ============================================
echo.

cd /d "%~dp0"

echo [1/3] Installing dependencies...
set GPU_PACKAGES=
where nvidia-smi >nul 2>&1
if %errorlevel%==0 (
    echo Detected NVIDIA GPU. Installing CUDA runtimes for ONNX/MMDeploy...
    set GPU_PACKAGES=onnxruntime-gpu==1.15.1 mmdeploy-runtime-gpu==1.3.1 nvidia-cuda-runtime-cu11==11.8.89 nvidia-cublas-cu11==11.11.3.6 nvidia-cudnn-cu11==8.9.5.29 nvidia-cuda-nvrtc-cu11==11.8.89 nvidia-cufft-cu11==10.9.0.58 nvidia-curand-cu11==10.3.0.86
) else (
    echo NVIDIA GPU not detected. Building CPU-only runtime...
)

pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
if defined GPU_PACKAGES (
    echo [1.5/3] Installing GPU runtimes...
    pip install %GPU_PACKAGES% --quiet
    if errorlevel 1 (
        echo ERROR: Failed to install GPU runtimes
        pause
        exit /b 1
    )
    python prepare_gpu_runtime.py
    if errorlevel 1 (
        echo ERROR: Failed to prepare MMDeploy GPU runtime
        pause
        exit /b 1
    )
)

echo [2/3] Building with PyInstaller...
python build_exe.py
if errorlevel 1 (
    echo ERROR: PyInstaller build failed
    pause
    exit /b 1
)

echo [3/3] Building installer with Inno Setup...
where iscc >nul 2>&1
if errorlevel 1 (
    echo Inno Setup not found in PATH. Trying default locations...
    if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
    ) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
        "C:\Program Files\Inno Setup 6\ISCC.exe" installer.iss
    ) else (
        echo.
        echo WARNING: Inno Setup not found!
        echo Download from: https://jrsoftware.org/isdl.php
        echo After installing, run: iscc installer.iss
        echo.
        echo PyInstaller output is ready in: dist\CCTV-Processor\
        pause
        exit /b 0
    )
) else (
    iscc installer.iss
)

if errorlevel 1 (
    echo ERROR: Inno Setup build failed
    pause
    exit /b 1
)

echo.
echo ============================================
echo   BUILD COMPLETE!
echo   Installer set: installer_output\CCTV-Processor-Setup-1.0.0.exe + *.bin
echo ============================================
pause
