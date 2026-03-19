@echo off
chcp 65001 >nul
echo === Starting Backend ===

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate

echo Installing dependencies...
pip install -r requirements.txt -q

echo Running migrations...
alembic upgrade head

echo.
echo === Backend: http://localhost:8000 ===
echo === Swagger: http://localhost:8000/docs ===
echo.
uvicorn app.main:app --reload --port 8000
