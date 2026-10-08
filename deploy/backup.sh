#!/usr/bin/env bash
# Run ON the instance (or from cron). Makes a consistent copy of the SQLite database and keeps the last 14.
#   Optional: BACKUP_S3=s3://my-bucket/price-analyzer  (needs the AWS CLI and an instance role with write access)
set -euo pipefail
cd ~/price-analyzer
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p backups
sudo docker compose exec -T app python - <<PY
import sqlite3
src = sqlite3.connect("/data/prices.db")
dst = sqlite3.connect("/data/backup-${STAMP}.db")
src.backup(dst)
dst.close()
PY
sudo docker compose cp "app:/data/backup-${STAMP}.db" "backups/prices-${STAMP}.db"
sudo docker compose exec -T app rm -f "/data/backup-${STAMP}.db"
ls -1t backups/prices-*.db | tail -n +15 | xargs -r rm -f
if [ -n "${BACKUP_S3:-}" ]; then aws s3 cp "backups/prices-${STAMP}.db" "${BACKUP_S3}/prices-${STAMP}.db"; fi
echo "Backup saved: backups/prices-${STAMP}.db"
