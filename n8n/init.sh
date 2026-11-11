#!/bin/sh
# First-run setup: import credentials and the workflow, then start n8n.
# Secret values come from environment variables (set in .env), never from files in the repo.
set -eu

MARKER=/home/node/.n8n/.lab-imported
if [ ! -f "$MARKER" ]; then
  TMP=$(mktemp -d)
  # Credentials are written to a temp file only for the import, then deleted.
  # n8n encrypts them at rest with N8N_ENCRYPTION_KEY.
  node -e '
    const e = process.env;
    const creds = [
      { id: "portalWebhookKy1", name: "Portal webhook key", type: "httpHeaderAuth",
        data: { name: "X-Portal-Key", value: e.PORTAL_WEBHOOK_KEY } },
      { id: "crmAgentKey00001", name: "CRM agent key (scoped)", type: "httpHeaderAuth",
        data: { name: "X-API-Key", value: e.CRM_AGENT_KEY } },
      { id: "mockLlmKey000001", name: "Mock LLM key", type: "httpHeaderAuth",
        data: { name: "Authorization", value: "Bearer " + e.LLM_API_KEY } },
    ];
    require("fs").writeFileSync(process.argv[1], JSON.stringify(creds), { mode: 0o600 });
  ' "$TMP/creds.json"
  n8n import:credentials --input="$TMP/creds.json"
  rm -rf "$TMP"
  n8n import:workflow --input=/lab/workflows/secured-support-agent.json
  n8n update:workflow --id=securedSupportAg --active=true
  touch "$MARKER"
fi

# Do not pass the raw keys on to the running n8n process.
unset PORTAL_WEBHOOK_KEY CRM_AGENT_KEY LLM_API_KEY
exec n8n start
