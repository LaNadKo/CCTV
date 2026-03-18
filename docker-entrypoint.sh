#!/bin/bash
# Точка входа для backend-контейнера
# Ожидает готовности PostgreSQL, применяет миграции, запускает сервер

set -e

MAX_RETRIES=30
RETRY_INTERVAL=2

echo "=== CCTV Backend ==="
echo "Ожидание готовности PostgreSQL..."

for i in $(seq 1 $MAX_RETRIES); do
    if python -c "
import asyncio, asyncpg, os
async def check():
    url = os.environ.get('DATABASE_URL', '').replace('+asyncpg', '').replace('postgresql://', 'postgresql://')
    # Parse from SQLAlchemy URL
    url = url.replace('postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)
    await conn.close()
asyncio.run(check())
" 2>/dev/null; then
        echo "PostgreSQL готов!"
        break
    fi

    if [ $i -eq $MAX_RETRIES ]; then
        echo "ОШИБКА: PostgreSQL недоступен после $MAX_RETRIES попыток"
        exit 1
    fi

    echo "  Попытка $i/$MAX_RETRIES — PostgreSQL ещё не готов, ждём ${RETRY_INTERVAL}с..."
    sleep $RETRY_INTERVAL
done

echo "Применение миграций..."
alembic upgrade head

echo "Запуск сервера..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
