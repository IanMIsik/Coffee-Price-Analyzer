#!/usr/bin/env bash
# Pulls the latest code and rebuilds only if something changed. Run by cron every night; safe to run by hand.
set -euo pipefail
cd /opt/price-analyzer
git fetch --quiet origin
if [ "$(git rev-parse HEAD)" != "$(git rev-parse '@{u}')" ]; then
  git pull --ff-only --quiet
  docker compose --profile https up -d --build
  docker image prune -f >/dev/null
  echo "$(date -Is) updated to $(git rev-parse --short HEAD)"
fi
