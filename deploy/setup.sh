#!/usr/bin/env bash
# One script that sets up and runs everything. On the server:
#   git clone https://github.com/IanMIsik/Coffee-Price-Analyzer.git && cd Coffee-Price-Analyzer && ./deploy/setup.sh
# After that, to update:  git pull && ./deploy/setup.sh      (re-running is safe; it keeps your settings)
#
# It: installs Docker if needed, asks for your DuckDNS name/token and a dashboard login (first run only), keeps the
# DuckDNS address pointing at this server, starts the app behind HTTPS, and makes it start on boot and update nightly.
#
# Non-interactive use: set DUCKDNS_SUBDOMAIN, DUCKDNS_TOKEN, APP_USER, APP_PASSWORD in the environment.
# Flags: --reconfigure (ask the questions again)   --config-only (write .env and stop; for testing)
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"
RECONFIGURE=0
CONFIG_ONLY=0
for a in "$@"; do
  case "$a" in
    --reconfigure) RECONFIGURE=1 ;;
    --config-only) CONFIG_ONLY=1 ;;
  esac
done

say() { printf '\n==> %s\n' "$*"; }

if [ "$CONFIG_ONLY" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
  exec sudo -E bash "$0" "$@"        # system changes need root; re-run this script with sudo
fi

[ -f docker-compose.yml ] || { echo "Run this from a clone of the repository." >&2; exit 1; }

# ---- 1. Docker ------------------------------------------------------------------------------------
install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then return; fi
  . /etc/os-release
  case "$ID" in
    ubuntu|debian)
      say "Installing Docker"
      apt-get update -y
      apt-get install -y ca-certificates curl git openssl
      curl -fsSL https://get.docker.com | sh
      ;;
    *)
      echo "Unsupported OS '$ID'. Use Ubuntu 24.04, or install Docker + the compose plugin yourself and re-run." >&2
      exit 1
      ;;
  esac
  systemctl enable --now docker
}

if [ "$CONFIG_ONLY" -eq 0 ]; then
  install_docker
  # 1 GB swap so the image build does not run out of memory on a 1 GB instance
  if [ "$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)" -lt 1900 ] && ! swapon --show | grep -q .; then
    say "Adding 1 GB swap"
    fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
fi

# ---- 2. Settings (.env) ---------------------------------------------------------------------------
getenvfile() {   # value of KEY from the existing .env (empty if none)
  [ -f .env ] || return 0
  grep -E "^$1=" .env | head -1 | cut -d= -f2- | sed "s/^'//; s/'\$//" || true
}

ask() {          # ask VAR "Prompt" [default] [secret]
  local var="$1" prompt="$2" def="${3:-}" secret="${4:-}" val=""
  if [ -t 0 ]; then
    if [ -n "$secret" ]; then
      read -r -s -p "$prompt: " val
      echo
    else
      read -r -p "$prompt${def:+ [$def]}: " val
    fi
  fi
  printf -v "$var" '%s' "${val:-$def}"
}

DUCKDNS_SUBDOMAIN="${DUCKDNS_SUBDOMAIN:-$(getenvfile DUCKDNS_SUBDOMAIN)}"
DUCKDNS_TOKEN="${DUCKDNS_TOKEN:-$(getenvfile DUCKDNS_TOKEN)}"
APP_USER="${APP_USER:-$(getenvfile BASIC_AUTH_USER)}"
APP_PASSWORD="${APP_PASSWORD:-}"
HASH="$(getenvfile BASIC_AUTH_HASH)"
FIRST_RUN=0
[ -f .env ] || FIRST_RUN=1

if [ "$FIRST_RUN" -eq 1 ] || [ "$RECONFIGURE" -eq 1 ]; then
  say "Setup questions (press Enter to accept a default)"
  [ -n "$DUCKDNS_SUBDOMAIN" ] || ask DUCKDNS_SUBDOMAIN "DuckDNS name (e.g. mycoffee or mycoffee.duckdns.org; empty to skip DuckDNS)"
  if [ -n "$DUCKDNS_SUBDOMAIN" ]; then
    for _try in 1 2 3; do
      [ -z "$DUCKDNS_TOKEN" ] || break
      ask DUCKDNS_TOKEN "DuckDNS token (input is hidden: paste it, then press Enter)" "" secret
      if [ -n "$DUCKDNS_TOKEN" ]; then echo "  received ${#DUCKDNS_TOKEN} characters"; else echo "  nothing received, try again"; fi
    done
  fi
  [ -n "$APP_USER" ] || ask APP_USER "Dashboard login name" "admin"
  if [ -z "$APP_PASSWORD" ]; then
    ask APP_PASSWORD "Dashboard password (hidden; press Enter to generate one)" "" secret
  fi
  HASH=""   # recomputed below
fi
APP_USER="${APP_USER:-admin}"
DUCKDNS_SUBDOMAIN="${DUCKDNS_SUBDOMAIN%.duckdns.org}"

if [ -n "$DUCKDNS_SUBDOMAIN" ] && [ -z "$DUCKDNS_TOKEN" ]; then
  echo "No DuckDNS token received. Run it again, or pass the token directly:" >&2
  echo "  DUCKDNS_SUBDOMAIN=${DUCKDNS_SUBDOMAIN} DUCKDNS_TOKEN=your-token ./deploy/setup.sh" >&2
  exit 1
fi

GENERATED=0
if [ -z "$HASH" ]; then
  if [ -z "$APP_PASSWORD" ]; then
    APP_PASSWORD="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 16)"
    GENERATED=1
  fi
  HASH="$(docker run --rm caddy:2 caddy hash-password --plaintext "$APP_PASSWORD")"
fi

if [ -n "$DUCKDNS_SUBDOMAIN" ]; then
  [ -n "$DUCKDNS_TOKEN" ] || { echo "A DuckDNS token is required with a DuckDNS name." >&2; exit 1; }
  DOMAIN="${DUCKDNS_SUBDOMAIN}.duckdns.org"
  AUTO_HOST=0
else
  DOMAIN="$(getenvfile DOMAIN)"
  DOMAIN="${DOMAIN:-placeholder.sslip.io}"
  AUTO_HOST=1     # boot.sh fills in <ip>.sslip.io
fi

POLL="$(getenvfile PA_POLL_MINUTES)"
NEWS="$(getenvfile PA_NEWS_HOURS)"
umask 077
cat > .env <<ENV
COMPOSE_PROJECT_NAME=price-analyzer
DOMAIN=${DOMAIN}
AUTO_HOST=${AUTO_HOST}
DUCKDNS_SUBDOMAIN=${DUCKDNS_SUBDOMAIN}
DUCKDNS_TOKEN=${DUCKDNS_TOKEN}
BASIC_AUTH_USER=${APP_USER}
BASIC_AUTH_HASH='${HASH}'
PA_POLL_MINUTES=${POLL:-30}
PA_NEWS_HOURS=${NEWS:-12}
ENV
chmod 600 .env
say "Settings saved to $APP_DIR/.env"
if [ "$CONFIG_ONLY" -eq 1 ]; then
  echo "(config only; stopping here)"
  exit 0
fi
chmod +x deploy/*.sh

# ---- 3. DuckDNS updater: keeps the name pointing at this server even if its IP changes -------------------
if [ -n "$DUCKDNS_SUBDOMAIN" ]; then
  say "Pointing ${DOMAIN} at this server"
  ./deploy/duckdns-update.sh || true
  echo "*/5 * * * * root ${APP_DIR}/deploy/duckdns-update.sh >/dev/null 2>&1" > /etc/cron.d/price-analyzer-duckdns
  MYIP="$(curl -fsS -m 5 https://checkip.amazonaws.com 2>/dev/null | tr -d '[:space:]' || true)"
  for _ in $(seq 1 24); do
    if [ "$(getent hosts "$DOMAIN" | awk '{print $1; exit}')" = "$MYIP" ]; then
      echo "DNS is ready ($DOMAIN -> $MYIP)"
      break
    fi
    sleep 5
  done
fi

# ---- 4. Start now, on every boot, and update nightly ---------------------------------------------------
say "Installing the boot service"
cat > /etc/systemd/system/price-analyzer.service <<UNIT
[Unit]
Description=Coffee Price Analyzer
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=${APP_DIR}/deploy/boot.sh
TimeoutStartSec=1200

[Install]
WantedBy=multi-user.target
UNIT
echo "30 3 * * * root ${APP_DIR}/deploy/update.sh >> /var/log/price-analyzer-update.log 2>&1" > /etc/cron.d/price-analyzer
systemctl daemon-reload
systemctl enable price-analyzer.service >/dev/null 2>&1
say "Building and starting the app (the first build takes a few minutes)"
systemctl restart price-analyzer.service

# ---- 5. Wait for health and report ---------------------------------------------------------------------
state=starting
for _ in $(seq 1 40); do
  state="$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q app 2>/dev/null)" 2>/dev/null || echo starting)"
  [ "$state" = healthy ] && break
  sleep 3
done
HOST="$(grep '^DOMAIN=' .env | cut -d= -f2-)"
echo
echo "=============================================================="
echo " App health : $state"
echo " Address    : https://${HOST}   (allow a minute for the HTTPS certificate)"
echo " Login      : ${APP_USER}"
if [ "$GENERATED" -eq 1 ]; then
  echo " Password   : ${APP_PASSWORD}   <- shown once; save it now"
else
  echo " Password   : (the one you chose; run with --reconfigure to change it)"
fi
echo "=============================================================="
