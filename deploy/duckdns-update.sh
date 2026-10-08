#!/usr/bin/env bash
# Tells DuckDNS this server's current public IP. Run by cron every 5 minutes (and once by setup.sh).
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SUB="$(grep -E '^DUCKDNS_SUBDOMAIN=' "$APP_DIR/.env" | cut -d= -f2-)"
TOKEN="$(grep -E '^DUCKDNS_TOKEN=' "$APP_DIR/.env" | cut -d= -f2-)"
[ -n "$SUB" ] && [ -n "$TOKEN" ] || exit 0
# An empty ip= lets DuckDNS use the address the request comes from.
RESULT="$(curl -fsS -m 20 "https://www.duckdns.org/update?domains=${SUB}&token=${TOKEN}&ip=" || echo KO)"
echo "$(date -Is) duckdns ${SUB}: ${RESULT}"
[ "$RESULT" = OK ]
