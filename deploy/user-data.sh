#!/bin/bash
# =====================================================================================================
# Optional: paste this into  EC2 > Launch instance > Advanced details > User data  to have a NEW instance set
# itself up on first boot. It just clones the repository and runs deploy/setup.sh, which does all the work.
# (If you already have a running server, skip this and run deploy/setup.sh yourself. See DEPLOY.md.)
#
# Use Ubuntu Server 24.04 LTS. Fill in the DuckDNS values to use your own duckdns.org address; leave them empty
# to get a free <ip>.sslip.io address instead. Note: User data is readable by anyone with access to the instance
# in your AWS account, so the DuckDNS token set here is visible there.
# The app has no login: anyone with the address can open the dashboard.
# =====================================================================================================
REPO_URL="https://github.com/IanMIsik/Coffee-Price-Analyzer.git"
DUCKDNS_SUBDOMAIN=""      # e.g. mycoffee   (becomes mycoffee.duckdns.org)
DUCKDNS_TOKEN=""

set -euo pipefail
exec > >(tee -a /var/log/price-analyzer-setup.log) 2>&1
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y git curl ca-certificates
git clone "$REPO_URL" /opt/price-analyzer
cd /opt/price-analyzer
export DUCKDNS_SUBDOMAIN DUCKDNS_TOKEN
bash deploy/setup.sh
