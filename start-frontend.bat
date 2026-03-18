@echo off
chcp 65001 >nul
echo === Starting Frontend ===

cd frontend

if not exist node_modules (
    echo Installing dependencies...
    npm install
)

echo.
echo === Frontend: http://localhost:5173 ===
echo.
npm run dev
