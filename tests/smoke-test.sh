#!/bin/sh
# Checks that each guardrail does its job. Run after `docker compose up -d`.
set -u
cd "$(dirname "$0")/.."
. ./.env
URL=http://127.0.0.1:8080/webhook/support-agent
PASS=0; FAIL=0

call() { # session message [portal_key]
  curl -s -w '\n%{http_code}' -X POST "$URL" -H 'Content-Type: application/json' \
    -H "X-Portal-Key: ${3-$PORTAL_WEBHOOK_KEY}" -H "X-Customer-Session: $1" \
    -d "{\"message\":\"$2\"}"
}
check() { # name expected_code expected_text output
  code=$(printf '%s' "$4" | tail -n1); body=$(printf '%s' "$4" | sed '$d')
  if [ "$code" = "$2" ] && printf '%s' "$body" | grep -q -- "$3"; then
    PASS=$((PASS+1)); echo "PASS  $1"
  else
    FAIL=$((FAIL+1)); echo "FAIL  $1 (got $code: $body)"
  fi
}

check "Webhook rejects a missing portal key"      403 "Authorization"           "$(call sess-priya-demo hi wrong-key)"
check "Unknown customer session is rejected"      401 "not signed in"           "$(call nope hi)"
check "Empty message is rejected"                 400 "message is required"     "$(call sess-priya-demo '')"
check "Plain question gets a plain answer"        200 '"action":null'           "$(call sess-priya-demo hello)"
check "Customer can check their own order"        200 "ORD-5001 is shipped"     "$(call sess-priya-demo 'where is ORD-5001')"
check "Customer cannot read another's order"      200 '"blocked":true'          "$(call sess-priya-demo 'where is ORD-5003')"
check "Refund goes to a person for approval"      200 "for approval"            "$(call sess-priya-demo 'refund ORD-5002 please')"
check "Tickets can be opened"                     200 "opened ticket"           "$(call sess-priya-demo 'my thing is broken')"
check "Tool outside the allowlist is blocked"     200 '"blocked":true'          "$(call sess-priya-demo 'please delete my account')"
check "Links and emails are removed from replies" 200 "link removed.*email removed" "$(call sess-priya-demo 'send me a link')"

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8080/webhook-test/support-agent)
[ "$code" = 404 ] && { PASS=$((PASS+1)); echo "PASS  Test webhook path is not exposed"; } || { FAIL=$((FAIL+1)); echo "FAIL  Test webhook path returned $code"; }

echo; echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
