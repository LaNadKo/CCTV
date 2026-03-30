#!/bin/bash
# Остановка всех CCTV контейнеров

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

echo "Остановка CCTV сервера..."
compose_cmd down
echo "Готово."
