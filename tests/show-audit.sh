#!/bin/sh
# Prints the mock CRM's audit log, tickets and pending refund approvals.
# Uses the admin key from inside the CRM container, so it is never sent to n8n.
cd "$(dirname "$0")/.."
docker compose exec -T mock-crm python -c "
import os, json, urllib.request as u
r = u.Request('http://localhost:8000/admin/audit', headers={'X-API-Key': os.environ['CRM_ADMIN_KEY']})
print(json.dumps(json.load(u.urlopen(r)), indent=2))"
