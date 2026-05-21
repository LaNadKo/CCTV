#!/bin/sh
set -eu

interval="${NGINX_RELOAD_INTERVAL_SECONDS:-21600}"
if [ "${interval}" = "0" ]; then
    exit 0
fi

(
    while true; do
        sleep "${interval}"
        nginx -s reload || true
    done
) &
