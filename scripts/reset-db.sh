#!/bin/bash
# Полный сброс базы данных (чистый старт)
# ВНИМАНИЕ: Удаляет все данные!

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

derive_compose_project_name() {
    local raw_name transliterated sanitized
    raw_name="$(basename "$PROJECT_DIR")"
    transliterated="$(printf '%s' "$raw_name" | iconv -f UTF-8 -t ASCII//TRANSLIT 2>/dev/null || printf '%s' "$raw_name")"
    sanitized="$(printf '%s' "$transliterated" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
    if [ -z "$sanitized" ]; then
        sanitized="cctvlocal"
    fi
    printf '%s\n' "$sanitized"
}

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$(derive_compose_project_name)}"
export COMPOSE_PROJECT_NAME

compose_cmd() {
    docker compose -p "$COMPOSE_PROJECT_NAME" "$@"
}

cd "$PROJECT_DIR"

echo "!!! ВНИМАНИЕ !!!"
echo "Это удалит ВСЕ данные из базы (пользователи, камеры, записи)."
read -p "Продолжить? (y/N): " confirm

if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Отменено."
    exit 0
fi

echo "Остановка сервера..."
compose_cmd down

echo "Удаление базы данных..."
docker volume rm "${COMPOSE_PROJECT_NAME}_pgdata" 2>/dev/null || \
docker volume rm cctv_pgdata 2>/dev/null || \
echo "Volume не найден, продолжаем..."

echo "Запуск с чистой базой..."
compose_cmd up -d --build db backend mediamtx

echo ""
echo "Ожидание инициализации..."
sleep 8

compose_cmd ps

echo ""
echo "=== Чистый старт выполнен ==="
echo "Логин: admin / admin"
