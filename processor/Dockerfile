FROM python:3.11-slim@sha256:f9fa7f851e38bfb19c9de3afbc4b86ae7176ea7aaf94535c31df5458d5849457

ARG CCTV_UID=999
ARG CCTV_GID=999

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates && \
    groupadd --gid "${CCTV_GID}" cctv && \
    useradd --uid "${CCTV_UID}" --gid cctv --home-dir /app --shell /usr/sbin/nologin cctv && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY processor/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --upgrade \
    pip==26.1.1 setuptools==82.0.1 wheel==0.47.0
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=cctv:cctv processor/ ./processor/
COPY --chown=cctv:cctv cctv_ai/ ./cctv_ai/
COPY processor/docker-entrypoint.sh /usr/local/bin/cctv-processor-entrypoint.sh
RUN mkdir -p /app/processor-runtime /app/media/recordings /app/media/snapshots && \
    chmod +x /usr/local/bin/cctv-processor-entrypoint.sh && \
    chown -R cctv:cctv /app

USER cctv

ENTRYPOINT ["cctv-processor-entrypoint.sh"]
CMD ["python", "-m", "processor.runtime"]
