#!/bin/bash
# Полный сброс базы данных (чистый старт)
# ВНИМАНИЕ: Удаляет все данные!

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "!!! ВНИМАНИЕ !!!"
echo "Это удалит ВСЕ данные из базы (пользователи, камеры, записи)."
read -p "Продолжить? (y/N): " confirm

if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Отменено."
    exit 0
fi

echo "Остановка сервера..."
docker compose down

echo "Удаление базы данных..."
docker volume rm "$(basename "$PROJECT_DIR" | tr '[:upper:]' '[:lower:]')_pgdata" 2>/dev/null || \
docker volume rm cctv_pgdata 2>/dev/null || \
echo "Volume не найден, продолжаем..."

echo "Запуск с чистой базой..."
docker compose up -d --build db backend mediamtx

echo ""
echo "Ожидание инициализации..."
sleep 8

docker compose ps

echo ""
echo "=== Чистый старт выполнен ==="
echo "Логин: admin / admin"
