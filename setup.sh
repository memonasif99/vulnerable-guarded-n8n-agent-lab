#!/bin/sh
# Generates a .env file with fresh random secrets. Safe to re-run: it will not overwrite an existing .env.
set -eu
cd "$(dirname "$0")"
if [ -f .env ]; then echo ".env already exists, leaving it as is."; exit 0; fi
r() { openssl rand -hex 24; }
umask 077
cat > .env <<ENV
N8N_ENCRYPTION_KEY=$(r)
PORTAL_WEBHOOK_KEY=$(r)
CRM_AGENT_KEY=$(r)
CRM_ADMIN_KEY=$(r)
LLM_API_KEY=$(r)
ENV
echo "Wrote .env with new random secrets (readable only by you)."
