#!/bin/bash
# Запуск серверной части CCTV на Raspberry Pi
# Поднимает: PostgreSQL + Backend (FastAPI) + MediaMTX
# Processor запускается отдельно на машине с GPU

set -e

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
GENERATED_ADMIN_PASSWORD=""

compose_cmd() {
    docker compose -p "$COMPOSE_PROJECT_NAME" "$@"
}

cd "$PROJECT_DIR"

echo "=== CCTV Server ==="

# Проверяем наличие .env
if [ ! -f ".env" ]; then
    umask 077
    echo "Файл .env не найден. Создаю из .env.example..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        # Генерируем безопасные значения
        JWT=$(openssl rand -hex 32 2>/dev/null || head -c 64 /dev/urandom | xxd -p | tr -d '\n' | head -c 64)
        PKEY=$(openssl rand -hex 24 2>/dev/null || head -c 48 /dev/urandom | xxd -p | tr -d '\n' | head -c 48)
        DBPW=$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | xxd -p | tr -d '\n' | head -c 32)
        ADMINPW=$(openssl rand -base64 24 2>/dev/null | tr -d '\n' | tr '/+' '_-' | head -c 24)
        GENERATED_ADMIN_PASSWORD="$ADMINPW"
        TOTPKEY=$(openssl rand -base64 32 2>/dev/null | tr -d '\n' | tr '/+' '_-')
        sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$DBPW|" .env
        sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$JWT|" .env
        sed -i "s|^PROCESSOR_API_KEY=.*|PROCESSOR_API_KEY=$PKEY|" .env
        sed -i "s|^BOOTSTRAP_ADMIN_PASSWORD=.*|BOOTSTRAP_ADMIN_PASSWORD=$ADMINPW|" .env
        sed -i "s|^ALLOW_DEFAULT_ADMIN=.*|ALLOW_DEFAULT_ADMIN=false|" .env
        sed -i "s|^TOTP_ENCRYPTION_KEY=.*|TOTP_ENCRYPTION_KEY=$TOTPKEY|" .env
        chmod 600 .env
        echo "  .env создан с автоматически сгенерированными ключами"
    else
        echo "ОШИБКА: .env.example не найден!"
        exit 1
    fi
fi

echo "Запуск серверных компонентов..."
echo ""

# Останавливаем старые контейнеры если есть
compose_cmd down 2>/dev/null || true

# Запускаем только нужные сервисы (без processor)
compose_cmd up -d --build db backend mediamtx

echo ""
echo "Ожидание готовности сервера..."

# Ждём готовности бэкенда
retries=30
while [ $retries -gt 0 ]; do
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        break
    fi
    retries=$((retries-1))
    sleep 2
    echo -ne "\r  Ожидание... ($retries)"
done
echo ""

# Проверяем статус
compose_cmd ps

LOCAL_IP=$(grep -E '^DOMAIN=' .env 2>/dev/null | head -n1 | cut -d= -f2-)
LOCAL_IP=${LOCAL_IP:-$(hostname -I | awk '{print $1}')}
echo ""
echo "=== Сервер запущен ==="
echo "API:      http://$LOCAL_IP:8000"
echo "RTSP:     rtsp://$LOCAL_IP:8554"
echo "Swagger:  http://$LOCAL_IP:8000/docs"
echo ""
if [ -n "$GENERATED_ADMIN_PASSWORD" ]; then
    echo "Bootstrap admin: admin / $GENERATED_ADMIN_PASSWORD"
else
    echo "Bootstrap admin password: see BOOTSTRAP_ADMIN_PASSWORD in .env"
fi
echo "Processor подключать с ключом из .env (PROCESSOR_API_KEY)"
