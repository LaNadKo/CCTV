#!/bin/bash
# Запуск серверной части CCTV на Raspberry Pi
# Поднимает: PostgreSQL + Backend (FastAPI) + MediaMTX
# Processor запускается отдельно на машине с GPU

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=== CCTV Server ==="
echo "Запуск серверных компонентов..."
echo ""

# Останавливаем старые контейнеры если есть
docker compose down 2>/dev/null || true

# Запускаем только нужные сервисы (без processor и frontend)
docker compose up -d --build db backend mediamtx

echo ""
echo "Ожидание готовности базы данных..."
sleep 5

# Проверяем статус
docker compose ps

echo ""
echo "=== Сервер запущен ==="
echo "API:      http://$(hostname -I | awk '{print $1}'):8000"
echo "RTSP:     rtsp://$(hostname -I | awk '{print $1}'):8554"
echo "Swagger:  http://$(hostname -I | awk '{print $1}'):8000/docs"
echo ""
echo "Логин по умолчанию: admin / admin"
echo "Processor подключать с ключом из .env (PROCESSOR_API_KEY)"
