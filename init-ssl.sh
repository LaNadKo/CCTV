#!/usr/bin/env bash
# ============================================================
#  CCTV Console — SSL Certificate Setup
#  Run once on the server to obtain a Let's Encrypt certificate.
#
#  Prerequisites:
#    - Domain DNS A-record must point to this server's IP
#    - Ports 80 and 443 must be open
#    - .env must have DOMAIN and SSL_EMAIL set
#
#  Usage: chmod +x init-ssl.sh && ./init-ssl.sh
# ============================================================
set -e

if [ ! -f .env ]; then
    echo "ERROR: .env not found. Copy .env.example to .env and fill in your values."
    exit 1
fi

set -a; source .env; set +a

if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "cctv.example.com" ]; then
    echo "ERROR: Set DOMAIN in .env to your actual domain (not cctv.example.com)"
    exit 1
fi

if [ -z "$SSL_EMAIL" ] || [ "$SSL_EMAIL" = "admin@example.com" ]; then
    echo "ERROR: Set SSL_EMAIL in .env to your real email"
    exit 1
fi

echo "=== SSL Certificate Setup ==="
echo "Domain: $DOMAIN"
echo "Email:  $SSL_EMAIL"
echo ""

# Step 1: Start nginx in HTTP-only mode to serve ACME challenge
echo "[1/3] Starting nginx for ACME challenge..."
docker compose up -d nginx

# Step 2: Request certificate
echo "[2/3] Requesting certificate from Let's Encrypt..."
docker compose run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$SSL_EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"

# Step 3: Instruct user to enable HTTPS in nginx config
echo ""
echo "=== Certificate obtained! ==="
echo ""
echo "Now enable HTTPS in nginx/default.conf.template:"
echo "  1. Uncomment the 'return 301' line in the HTTP server block"
echo "  2. Comment out the development location blocks"
echo "  3. Uncomment the HTTPS server block at the bottom"
echo "  4. Run: docker compose restart nginx"
echo ""
echo "Certificate will auto-renew via the certbot container."
