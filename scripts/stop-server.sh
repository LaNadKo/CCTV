#!/bin/bash
# Остановка всех CCTV контейнеров

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "Остановка CCTV сервера..."
docker compose down
echo "Готово."
