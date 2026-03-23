#!/bin/bash
# Запуск серверной части CCTV на Raspberry Pi
# Поднимает: PostgreSQL + Backend (FastAPI) + MediaMTX
# Processor запускается отдельно на машине с GPU

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=== CCTV Server ==="

# Проверяем наличие .env
if [ ! -f ".env" ]; then
    echo "Файл .env не найден. Создаю из .env.example..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        # Генерируем безопасные значения
        JWT=$(openssl rand -hex 32 2>/dev/null || head -c 64 /dev/urandom | xxd -p | tr -d '\n' | head -c 64)
        PKEY=$(openssl rand -hex 24 2>/dev/null || head -c 48 /dev/urandom | xxd -p | tr -d '\n' | head -c 48)
        DBPW=$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | xxd -p | tr -d '\n' | head -c 32)
        sed -i "s/POSTGRES_PASSWORD=changeme/POSTGRES_PASSWORD=$DBPW/" .env
        sed -i "s/JWT_SECRET=changeme-generate-with-openssl-rand-hex-32/JWT_SECRET=$JWT/" .env
        sed -i "s/PROCESSOR_API_KEY=changeme-generate-with-openssl-rand-hex-24/PROCESSOR_API_KEY=$PKEY/" .env
        echo "  .env создан с автоматически сгенерированными ключами"
    else
        echo "ОШИБКА: .env.example не найден!"
        exit 1
    fi
fi

echo "Запуск серверных компонентов..."
echo ""

# Останавливаем старые контейнеры если есть
docker compose down 2>/dev/null || true

# Запускаем только нужные сервисы (без processor и frontend)
docker compose up -d --build db backend mediamtx

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
docker compose ps

LOCAL_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "=== Сервер запущен ==="
echo "API:      http://$LOCAL_IP:8000"
echo "RTSP:     rtsp://$LOCAL_IP:8554"
echo "Swagger:  http://$LOCAL_IP:8000/docs"
echo ""
echo "Логин по умолчанию: admin / admin"
echo "Processor подключать с ключом из .env (PROCESSOR_API_KEY)"
