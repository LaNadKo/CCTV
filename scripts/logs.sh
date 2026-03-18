#!/bin/bash
# Просмотр логов CCTV сервера
# Использование: ./logs.sh [сервис]
# Примеры:
#   ./logs.sh          - все логи
#   ./logs.sh backend  - только бэкенд
#   ./logs.sh db       - только база данных

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

docker compose logs -f --tail=100 "$@"
