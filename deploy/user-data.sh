#!/bin/bash
# =====================================================================================================
# Paste this whole script into  EC2 > Launch instance > Advanced details > User data.
# Use Ubuntu Server 24.04 LTS and a "Free tier eligible" instance type.
# On first boot it installs everything, starts the app with HTTPS and a login, and keeps itself running
# and up to date. Edit REPO_URL below first.
# =====================================================================================================
REPO_URL="https://github.com/IanMIsik/Coffee-Price-Analyzer.git"   # <-- change this only if you fork it
REPO_BRANCH="main"
APP_USER="admin"                                             # login name for the dashboard
# Optional: your own domain (A record -> the instance's Elastic IP). Leave empty to use a free <ip>.sslip.io name.
CUSTOM_DOMAIN=""

set -euo pipefail
exec > >(tee -a /var/log/price-analyzer-setup.log) 2>&1
export DEBIAN_FRONTEND=noninteractive
echo "==> Setup started $(date -Is)"

# --- Docker (includes the compose and buildx plugins) -----------------------------------------------
apt-get update -y
apt-get install -y ca-certificates curl git openssl
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# --- 1 GB swap so the image build does not run out of memory on a 1 GB instance --------------------------
if ! swapon --show | grep -q .; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# --- Code ---------------------------------------------------------------------------------------------
git clone --branch "$REPO_BRANCH" "$REPO_URL" /opt/price-analyzer
cd /opt/price-analyzer
chmod +x deploy/*.sh

# --- Login + address ----------------------------------------------------------------------------------
PASSWORD="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 16)"
HASH="$(docker run --rm caddy:2 caddy hash-password --plaintext "$PASSWORD")"
if [ -n "$CUSTOM_DOMAIN" ]; then DOMAIN="$CUSTOM_DOMAIN"; AUTO=0; else DOMAIN="placeholder.sslip.io"; AUTO=1; fi
cat > .env <<ENV
DOMAIN=${DOMAIN}
AUTO_HOST=${AUTO}
BASIC_AUTH_USER=${APP_USER}
BASIC_AUTH_HASH='${HASH}'
PA_POLL_MINUTES=30
PA_NEWS_HOURS=12
ENV
chmod 600 .env
printf 'user: %s\npassword: %s\n' "$APP_USER" "$PASSWORD" > /root/price-analyzer-login.txt
chmod 600 /root/price-analyzer-login.txt

# --- Start now, and on every boot ---------------------------------------------------------------------
cat > /etc/systemd/system/price-analyzer.service <<'UNIT'
[Unit]
Description=Coffee Price Analyzer
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/opt/price-analyzer/deploy/boot.sh
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable price-analyzer.service
systemctl start price-analyzer.service     # first run builds the image (a few minutes)

# --- Nightly self-update from the repo ---------------------------------------------------------------
echo '30 3 * * * root /opt/price-analyzer/deploy/update.sh >> /var/log/price-analyzer-update.log 2>&1' > /etc/cron.d/price-analyzer

# --- Done: print the address and login (visible under Actions > Monitor > Get system log) -----------
TOKEN="$(curl -fsS -m 5 -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 300' || true)"
IP="$(curl -fsS -m 5 -H "X-aws-ec2-metadata-token: ${TOKEN}" http://169.254.169.254/latest/meta-data/public-ipv4 || true)"
[ -n "$CUSTOM_DOMAIN" ] && ADDR="https://${CUSTOM_DOMAIN}" || ADDR="https://${IP//./-}.sslip.io"
echo "=============================================================="
echo " PRICE ANALYZER READY (give it a minute for the certificate)"
echo " Address : ${ADDR}"
echo " Login   : ${APP_USER} / ${PASSWORD}"
echo " Saved on the server in /root/price-analyzer-login.txt"
echo "=============================================================="
