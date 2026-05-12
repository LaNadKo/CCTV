FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout=120 -r requirements.txt

COPY alembic.ini .
COPY migrations/ migrations/
COPY app/ app/
COPY config/ config/
COPY cctv_ai/ cctv_ai/
COPY frontend/dist/ frontend_dist/
COPY docker-entrypoint.sh .
RUN sed -i 's/\r$//' docker-entrypoint.sh && chmod +x docker-entrypoint.sh

EXPOSE 8000 5005/udp

CMD ["./docker-entrypoint.sh"]
