#!/usr/bin/env bash
set -euo pipefail

if [ ! -f .env ]; then
    echo "ERROR: .env not found. Copy .env.example to .env first."
    exit 1
fi

set -a
source .env
set +a

python3 scripts/setup_public_https.py --domain "${DOMAIN:?Set DOMAIN in .env}" --email "${SSL_EMAIL:?Set SSL_EMAIL in .env}"
