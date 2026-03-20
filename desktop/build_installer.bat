@echo off
setlocal

echo ========================================
echo Building CCTV Console Installer
echo ========================================

echo [1/3] Building frontend...
call npm --prefix ..\frontend run build
if errorlevel 1 goto :fail

echo [2/3] Building Electron app...
call npm run build:win
if errorlevel 1 (
    if exist "release\win-unpacked\resources.pak" (
        echo WARNING: electron-builder ended with error after producing win-unpacked. Continuing...
    ) else if exist "release\release\win-unpacked\resources.pak" (
        echo WARNING: electron-builder ended with error after producing nested win-unpacked. Continuing...
    ) else (
        goto :fail
    )
)

echo [2.5/3] Normalizing win-unpacked layout...
if exist "release\release\win-unpacked\resources.pak" (
    robocopy "release\release\win-unpacked" "release\win-unpacked" /MIR /NFL /NDL /NJH /NJS /NP >nul
    if errorlevel 8 goto :fail
)
if not exist "release\win-unpacked\resources.pak" (
    echo ERROR: Full win-unpacked build not found.
    goto :fail
)

echo [2.6/3] Syncing latest frontend bundle into win-unpacked...
if not exist "..\frontend\dist\index.html" (
    echo ERROR: frontend dist not found.
    goto :fail
)
if exist "release\win-unpacked\resources\frontend" (
    rmdir /S /Q "release\win-unpacked\resources\frontend"
)
robocopy "..\frontend\dist" "release\win-unpacked\resources\frontend" /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :fail

echo [3/3] Building installer with Inno Setup...
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    "C:\Program Files\Inno Setup 6\ISCC.exe" installer.iss
) else (
    echo ERROR: Inno Setup not found.
    goto :fail
)
if errorlevel 1 goto :fail

echo.
echo Installer ready:
echo   %cd%\installer_output\CCTV-Console-Setup-1.0.0.exe
exit /b 0

:fail
echo.
echo Build failed.
exit /b 1
