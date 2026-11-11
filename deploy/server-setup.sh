#!/bin/bash
# One-time setup of a fresh Ubuntu 24.04 server (e.g. Hetzner CX23), run as root:
#   curl -fsSL https://raw.githubusercontent.com/<you>/build-advisor/main/deploy/server-setup.sh | bash
# or copy it over and run: bash server-setup.sh
set -euo pipefail

APP_DIR=/srv/build-advisor
REPO=${REPO:-https://github.com/wahid/build-advisor.git}

echo "== Updates and basics"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
apt-get install -y ca-certificates curl git ufw unattended-upgrades fail2ban

echo "== Swap file (4 GB): a safety net for 4 GB servers such as the CX23"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 4G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
# Only swap under real memory pressure.
sysctl -w vm.swappiness=10
echo 'vm.swappiness=10' > /etc/sysctl.d/99-build-advisor.conf

echo "== Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi

echo "== Firewall: SSH, HTTP, HTTPS only"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

echo "== Deploy user (used by GitHub Actions)"
if ! id deploy >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" deploy
  usermod -aG docker deploy
  mkdir -p /home/deploy/.ssh
  cp /root/.ssh/authorized_keys /home/deploy/.ssh/ 2>/dev/null || true
  chown -R deploy:deploy /home/deploy/.ssh
  chmod 700 /home/deploy/.ssh
fi

echo "== App directory"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO" "$APP_DIR"
fi
mkdir -p "$APP_DIR/backups"
chown -R deploy:deploy "$APP_DIR"

echo "== Nightly database backup (kept 14 days)"
cat > /etc/cron.d/build-advisor-backup <<CRON
15 3 * * * deploy cd $APP_DIR && docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T db pg_dump -U build_advisor -Fc -f /backups/nightly-\$(date +\%a).dump build_advisor
CRON

echo
echo "Done. Next:"
echo "  1. cp $APP_DIR/.env.prod.example $APP_DIR/.env.prod and fill it in"
echo "  2. Copy your database over (see docs/deploy-hetzner.md)"
echo "  3. sudo -u deploy bash $APP_DIR/deploy/deploy.sh"
