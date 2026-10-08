#!/usr/bin/env bash
# Run from YOUR computer (Git Bash on Windows works). Uploads the app to the instance, builds the image, (re)starts it.
#   ./deploy/deploy.sh ubuntu@<ec2-ip> /path/to/key.pem
# Re-run the same command any time to ship an update. The database lives in a Docker volume and is kept.
set -euo pipefail

HOST="${1:?usage: deploy.sh user@host /path/to/key.pem}"
KEY="${2:?usage: deploy.sh user@host /path/to/key.pem}"
cd "$(dirname "$0")/.."

SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "$HOST")

echo "==> Uploading code"
"${SSH[@]}" 'mkdir -p ~/price-analyzer'
tar czf - \
  --exclude='prices.db' --exclude='*.db' --exclude='__pycache__' --exclude='.pytest_cache' \
  --exclude='tests' --exclude='.env' --exclude='.git' --exclude='backups' . \
  | "${SSH[@]}" 'tar xzf - -C ~/price-analyzer'

echo "==> Building and starting"
"${SSH[@]}" 'bash -s' <<'REMOTE'
set -euo pipefail
cd ~/price-analyzer
# Use the HTTPS profile when a .env with a DOMAIN exists on the server, otherwise localhost-only.
if [ -f .env ] && grep -q '^DOMAIN=' .env; then PROFILE="--profile https"; else PROFILE=""; fi
sudo docker compose $PROFILE up -d --build
sudo docker image prune -f >/dev/null
echo "==> Waiting for the app to become healthy"
for i in $(seq 1 30); do
  state="$(sudo docker inspect -f '{{.State.Health.Status}}' "$(sudo docker compose ps -q app)" 2>/dev/null || echo starting)"
  [ "$state" = healthy ] && break
  sleep 2
done
echo "Health: $state"
sudo docker compose $PROFILE ps
REMOTE

echo "==> Deployed. Open it with:  ssh -i $KEY -L 8100:localhost:8100 $HOST   then http://localhost:8100"
echo "    (or https://<your-domain> if you set up the HTTPS profile)"
