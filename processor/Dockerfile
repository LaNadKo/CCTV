FROM python:3.11-slim

ARG CCTV_UID=999
ARG CCTV_GID=999

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 && \
    groupadd --gid "${CCTV_GID}" cctv && \
    useradd --uid "${CCTV_UID}" --gid cctv --home-dir /app --shell /usr/sbin/nologin cctv && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY processor/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=cctv:cctv processor/ ./processor/
COPY --chown=cctv:cctv cctv_ai/ ./cctv_ai/
COPY processor/docker-entrypoint.sh /usr/local/bin/cctv-processor-entrypoint.sh
RUN mkdir -p /app/processor-runtime /app/media/recordings /app/media/snapshots && \
    chmod +x /usr/local/bin/cctv-processor-entrypoint.sh && \
    chown -R cctv:cctv /app

ENTRYPOINT ["cctv-processor-entrypoint.sh"]
CMD ["python", "-m", "processor.runtime"]
