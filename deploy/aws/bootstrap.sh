#!/bin/bash
# Installs Docker and starts the lab with the public 8443 listener.
# Run as root on Amazon Linux 2023 from the repo root. The CloudFormation
# template runs it on first boot. Usage: deploy/aws/bootstrap.sh <public-ip>
set -euo pipefail
PUBLIC_IP="${1:?usage: bootstrap.sh <public-ip>}"
cd "$(dirname "$0")/../.."

COMPOSE_VERSION=v2.29.7
BUILDX_VERSION=v0.17.1
case "$(uname -m)" in
  x86_64) ARCH=amd64; CARCH=x86_64 ;;
  aarch64) ARCH=arm64; CARCH=aarch64 ;;
  *) echo "unsupported architecture"; exit 1 ;;
esac

# Docker, plus automatic security updates for an always-on host.
dnf install -y docker openssl dnf-automatic
sed -i 's/^upgrade_type.*/upgrade_type = security/' /etc/dnf/automatic.conf
systemctl enable --now dnf-automatic-install.timer

PLUGINS=/usr/local/lib/docker/cli-plugins
mkdir -p "$PLUGINS"
curl -fsSL -o "$PLUGINS/docker-compose" \
  "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${CARCH}"
curl -fsSL -o "$PLUGINS/docker-buildx" \
  "https://github.com/docker/buildx/releases/download/${BUILDX_VERSION}/buildx-${BUILDX_VERSION}.linux-${ARCH}"
chmod 755 "$PLUGINS/docker-compose" "$PLUGINS/docker-buildx"
systemctl enable --now docker

# Secrets and a self-signed certificate for the public IP. Both stay on the host.
./setup.sh
if [ ! -f certs/lab.key ]; then
  mkdir -p certs
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -keyout certs/lab.key -out certs/lab.crt \
    -subj "/CN=${PUBLIC_IP}" -addext "subjectAltName=IP:${PUBLIC_IP}"
  chmod 600 certs/lab.key
fi

# Containers use restart: unless-stopped and Docker starts on boot,
# so the lab comes back by itself after a reboot.
docker compose -f docker-compose.yml -f docker-compose.public.yml up -d --build
echo "Lab started. Webhook: https://${PUBLIC_IP}:8443/webhook/support-agent"
