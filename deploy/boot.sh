#!/usr/bin/env bash
# Runs on every boot (via the price-analyzer systemd service) and from setup.sh: refreshes the address, starts the app.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

if grep -q '^DUCKDNS_SUBDOMAIN=.' .env 2>/dev/null; then
  ./deploy/duckdns-update.sh || true          # make sure the DuckDNS name points at this boot's public IP
elif grep -q '^AUTO_HOST=1' .env 2>/dev/null; then
  TOKEN="$(curl -fsS -m 5 -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 300' || true)"
  IP="$(curl -fsS -m 5 -H "X-aws-ec2-metadata-token: ${TOKEN}" http://169.254.169.254/latest/meta-data/public-ipv4 || true)"
  if [ -n "${IP}" ]; then sed -i "s|^DOMAIN=.*|DOMAIN=${IP//./-}.sslip.io|" .env; fi
fi

docker compose --profile https up -d --build
