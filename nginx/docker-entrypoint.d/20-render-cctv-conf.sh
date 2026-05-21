#!/bin/sh
set -eu

domain="${DOMAIN:-localhost}"
https_enabled="${NGINX_HTTPS_ENABLED:-false}"
cert_path="/etc/letsencrypt/live/${domain}/fullchain.pem"
key_path="/etc/letsencrypt/live/${domain}/privkey.pem"

if [ "${https_enabled}" = "true" ] && [ -f "${cert_path}" ] && [ -f "${key_path}" ]; then
    template="/etc/cctv-nginx/templates/https.conf.template"
else
    template="/etc/cctv-nginx/templates/http.conf.template"
fi

envsubst '${DOMAIN} ${NGINX_CLIENT_MAX_BODY_SIZE}' < "${template}" > /etc/nginx/conf.d/default.conf
