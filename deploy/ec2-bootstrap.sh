#!/usr/bin/env bash
# Run ONCE on a fresh EC2 instance (Ubuntu 24.04 or Amazon Linux 2023):
#   ssh -i key.pem ubuntu@<ip> 'bash -s' < deploy/ec2-bootstrap.sh
# Installs Docker + the compose plugin and makes the instance safe to run small containers.
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
. /etc/os-release
echo "==> Detected: ${PRETTY_NAME}"

case "${ID}" in
  ubuntu|debian)
    $SUDO apt-get update -y
    $SUDO apt-get install -y ca-certificates curl
    curl -fsSL https://get.docker.com | $SUDO sh        # installs docker-ce + compose plugin
    ;;
  amzn)
    $SUDO dnf install -y docker
    ARCH="$(uname -m)"                                   # x86_64 or aarch64
    $SUDO mkdir -p /usr/local/lib/docker/cli-plugins
    $SUDO curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH}" \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    $SUDO chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
    ;;
  *)
    echo "Unsupported OS: ${ID}. Install Docker and the compose plugin manually." >&2
    exit 1
    ;;
esac

$SUDO systemctl enable --now docker
$SUDO usermod -aG docker "${SUDO_USER:-$USER}" || true

# Small instances (1 GB RAM) can run out of memory while building the image; add a 1 GB swap file.
if [ "$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)" -lt 1900 ] && ! swapon --show | grep -q .; then
  echo "==> Adding 1 GB swap"
  $SUDO fallocate -l 1G /swapfile
  $SUDO chmod 600 /swapfile
  $SUDO mkswap /swapfile
  $SUDO swapon /swapfile
  echo '/swapfile none swap sw 0 0' | $SUDO tee -a /etc/fstab >/dev/null
fi

mkdir -p "$HOME/price-analyzer"
$SUDO docker --version
$SUDO docker compose version
echo "==> Done. Log out and back in if you want to run docker without sudo."
