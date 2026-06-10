FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libglib2.0-0 fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --system cctv && \
    useradd --system --gid cctv --home-dir /app --shell /usr/sbin/nologin cctv

COPY --chown=cctv:cctv requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade \
    pip==26.1.1 setuptools==82.0.1 wheel==0.47.0
RUN pip install --no-cache-dir --timeout=120 -r requirements.txt

COPY --chown=cctv:cctv alembic.ini .
COPY --chown=cctv:cctv migrations/ migrations/
COPY --chown=cctv:cctv app/ app/
COPY --chown=cctv:cctv cctv_ai/ cctv_ai/
COPY --chown=cctv:cctv docker-entrypoint.sh .
RUN sed -i 's/\r$//' docker-entrypoint.sh && \
    chmod +x docker-entrypoint.sh && \
    mkdir -p recordings snapshots recordings_cache && \
    chown -R cctv:cctv /app

EXPOSE 8000
USER cctv

CMD ["./docker-entrypoint.sh"]
