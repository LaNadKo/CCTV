@echo off
echo ============================================
echo   CCTV Processor - Full Build + Installer
echo ============================================
echo.

cd /d "%~dp0"

echo [1/3] Installing dependencies...
set TORCH_INDEX=https://download.pytorch.org/whl/cpu
where nvidia-smi >nul 2>&1
if %errorlevel%==0 (
    echo Detected NVIDIA GPU. Installing CUDA-enabled PyTorch...
    set TORCH_INDEX=https://download.pytorch.org/whl/cu124
) else (
    echo NVIDIA GPU not detected. Installing CPU-only PyTorch...
)

pip install --upgrade --force-reinstall torch torchvision --index-url %TORCH_INDEX% --quiet
if errorlevel 1 (
    echo ERROR: Failed to install PyTorch from %TORCH_INDEX%
    pause
    exit /b 1
)

pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
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
echo   Installer: installer_output\CCTV-Processor-Setup-1.0.0.exe
echo ============================================
pause
