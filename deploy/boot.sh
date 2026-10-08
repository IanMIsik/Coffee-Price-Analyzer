#!/usr/bin/env bash
# Runs on every boot (via the price-analyzer systemd service). Keeps the HTTPS address in step with the
# instance's current public IP, then makes sure the containers are up.
set -euo pipefail
cd /opt/price-analyzer

if grep -q '^AUTO_HOST=1' .env 2>/dev/null; then
  TOKEN="$(curl -fsS -m 5 -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 300' || true)"
  IP="$(curl -fsS -m 5 -H "X-aws-ec2-metadata-token: ${TOKEN}" http://169.254.169.254/latest/meta-data/public-ipv4 || true)"
  if [ -n "${IP}" ]; then
    sed -i "s|^DOMAIN=.*|DOMAIN=${IP//./-}.sslip.io|" .env
  fi
fi

docker compose --profile https up -d
