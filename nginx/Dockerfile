FROM nginx:alpine

RUN apk del curl || true

COPY templates/ /etc/cctv-nginx/templates/
COPY docker-entrypoint.d/ /docker-entrypoint.d/

RUN chmod +x /docker-entrypoint.d/*.sh
