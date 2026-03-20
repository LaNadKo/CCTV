@echo off
echo ============================================
echo   CCTV Processor - Fast Dev Build
echo ============================================
echo.

cd /d "%~dp0"

echo [1/2] Building GUI package without CLI...
set SKIP_PROCESSOR_CLI=1
python build_exe.py
if errorlevel 1 (
    echo ERROR: PyInstaller build failed
    pause
    exit /b 1
)

echo [2/2] Building fast installer...
where iscc >nul 2>&1
if errorlevel 1 (
    echo Inno Setup not found in PATH. Trying default locations...
    if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DFastBuild=1 installer.iss
    ) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
        "C:\Program Files\Inno Setup 6\ISCC.exe" /DFastBuild=1 installer.iss
    ) else (
        echo.
        echo WARNING: Inno Setup not found!
        echo PyInstaller output is ready in: dist\CCTV-Processor\
        pause
        exit /b 0
    )
) else (
    iscc /DFastBuild=1 installer.iss
)

if errorlevel 1 (
    echo ERROR: Inno Setup build failed
    pause
    exit /b 1
)

echo.
echo ============================================
echo   FAST BUILD COMPLETE!
echo   Installer: installer_output\CCTV-Processor-Setup-1.0.0.exe
echo   Mode: zip compression, no solid archive, CLI skipped
echo ============================================
pause
