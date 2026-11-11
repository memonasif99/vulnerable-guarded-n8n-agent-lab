# Guardrails and what they stop

Each row is a common weakness in no-code and low-code AI agent builds. The
lab's control for it, where that control lives, and the matching OWASP
categories follow.

- **LLM** refers to the [OWASP Top 10 for LLM Applications 2025](https://genai.owasp.org/llm-top-10/).
- **LCNC** refers to the [OWASP Low-Code/No-Code Top 10](https://owasp.org/www-project-top-10-low-code-no-code-security-risks/).

The guiding idea: **the model's output is untrusted input.** Prompt rules help,
but every action is decided by code and by the CRM, not by the model.

## 1. Secrets kept out of nodes and prompts

**Weakness:** API keys pasted into HTTP node headers, Code nodes or the system
prompt. They end up in exported workflow JSON, screenshots, git and execution logs.

**Controls**
- All keys live in n8n's credential store, encrypted with `N8N_ENCRYPTION_KEY`
  (`n8n/init.sh`). The workflow JSON only references credential IDs.
- `setup.sh` generates fresh random keys into `.env`, which is git-ignored and
  readable only by its owner. No key is committed.
- `init.sh` writes the credentials to a temp file only for import, deletes it,
  and unsets the raw keys before `n8n start`.
- `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` stops Code nodes from reading environment variables.
- The system prompt contains no secrets, codes or internal URLs.

**OWASP:** LLM02 Sensitive Information Disclosure, LLM07 System Prompt Leakage, LCNC-SEC-08 Data and Secret Handling Failures

## 2. Authenticated webhook and verified identity

**Weakness:** a webhook anyone can call, and an agent that trusts a
`customer_id` sent in the request body.

**Controls**
- The webhook uses Header Auth (`X-Portal-Key`, a stored credential). Calls without it get 403.
- Who the customer is comes from `X-Customer-Session`, which the CRM resolves.
  The chat message can't change it.
- The proxy exposes only `POST /webhook/support-agent`. Test webhooks (`/webhook-test/`) and other methods are refused.

**OWASP:** LCNC-SEC-04 Authentication and Secure Communication Failures, LCNC-SEC-01 Account Impersonation

## 3. Limits on abuse and cost

**Weakness:** no rate limits or size limits, so one caller can flood the agent
and run up model cost.

**Controls**
- nginx rate limit of 30 requests per minute per client, with a burst of 10 (`proxy/nginx.conf`).
- 16 KB request body cap at the proxy, 1,000 character message cap in `Validate input`.
- `max_tokens: 300` and `temperature: 0` on model calls, plus 10 second HTTP timeouts.

**OWASP:** LLM10 Unbounded Consumption, LCNC-SEC-05 Security Misconfiguration

## 4. Least-privilege connector

**Weakness:** the agent's connector uses an admin key that can read every
record and call every endpoint.

**Controls**
- The agent's CRM key only has the scopes `agent:context` and the three tool
  scopes (`mocks/crm.py`, `KEY_SCOPES`). Admin endpoints return 403 for it.
- The admin key is never given to n8n. Only the CRM container has it.
- The CRM checks the session and order ownership again on every tool call, so a
  misconfigured workflow still can't reach another customer's data.

**OWASP:** LLM06 Excessive Agency, LCNC-SEC-02 Authorization Misuse, LCNC-SEC-01 Account Impersonation

## 5. Untrusted text kept apart from instructions

**Weakness:** user text (and data pulled from other systems) is pasted straight
into the prompt, where it can override the instructions.

**Controls**
- `Build prompt` wraps customer data and the message in `<customer_data>` and
  `<user_message>` tags, strips `<` and `>` from the message so it can't close a
  tag, and tells the model to treat both as data.
- This reduces risk but can't remove it, which is why controls 6 and 8 don't rely on it.

**OWASP:** LLM01 Prompt Injection, LCNC-SEC-06 Injection Handling Failures

## 6. Tool allowlist, argument checks and human approval

**Weakness:** whatever tool name the model returns gets executed, with whatever arguments.

**Controls** (`Output guard` node)
- Only `get_order_status`, `create_ticket` and `request_refund` can run. Anything else is blocked.
- Arguments are checked against a format (`ORD-` plus 4 digits) and against the
  customer's own orders, then rebuilt so only known fields pass through.
- Refunds are never executed by the agent. They create a request that waits for
  a person, capped at 200 (`request_refund` in `mocks/crm.py`).

**OWASP:** LLM06 Excessive Agency, LCNC-SEC-02 Authorization Misuse

## 7. Data minimisation and no third parties

**Weakness:** full customer records go to the model, to analytics tools and
into execution logs.

**Controls**
- The CRM gives the agent only first name, plan and order statuses. No email, phone or last name.
- The workflow makes no third-party calls. n8n and the mocks sit on an
  `internal` Docker network with no route to the internet.
- n8n telemetry, version checks and templates are off.
- Successful executions are not saved (`EXECUTIONS_DATA_SAVE_ON_SUCCESS=none`).
  Failed ones are kept for debugging and pruned after 72 hours.

**OWASP:** LLM02 Sensitive Information Disclosure, LCNC-SEC-03 Data Leakage and Unexpected Consequences, LCNC-SEC-08 Data and Secret Handling Failures

## 8. Output handling

**Weakness:** raw model text, tool responses or error details are sent straight back to the caller.

**Controls**
- Model output must parse as JSON in the expected shape, otherwise it is refused.
- HTML, links, email addresses and phone numbers are removed from the reply, and it is capped at 500 characters.
- When a tool runs, `Format reply` builds the answer from a template and the
  tool's result, not from the model's text. Raw responses and block reasons are not returned.

**OWASP:** LLM05 Improper Output Handling, LLM09 Misinformation, LCNC-SEC-03 Data Leakage and Unexpected Consequences

## 9. Platform hardening

**Weakness:** default platform settings that give workflows more power than they need.

**Controls** (`docker-compose.yml`)
- Execute Command, SSH and file read and write nodes are disabled (`NODES_EXCLUDE`).
- Code nodes run in task runners, can't read env vars or n8n's own files, and the public API is off.
- Only the proxy publishes a port, on `127.0.0.1`. Containers drop all Linux
  capabilities and use `no-new-privileges`, and the mock services are read-only.
- Image versions are pinned (`n8nio/n8n:1.123.89`, `nginx:1.27-alpine`, `python:3.12-slim`).

**OWASP:** LCNC-SEC-05 Security Misconfiguration, LCNC-SEC-07 Vulnerable and Untrusted Components, LCNC-SEC-09 Asset Management Failures, LLM03 Supply Chain

## 10. Audit trail

**Weakness:** nobody can tell what the agent did, or what it tried and failed to do.

**Controls**
- The CRM logs every context read, tool call, rejected session, denied scope and
  approval request. `tests/show-audit.sh` prints the log.
- Failed n8n executions are kept for review.

**OWASP:** LCNC-SEC-10 Security Logging and Monitoring Failures

## Not covered here

- **LLM04 Data and Model Poisoning** and **LLM08 Vector and Embedding Weaknesses**:
  the lab has no fine-tuning and no retrieval store. They become relevant if you add RAG.
- **Production concerns**: HTTPS, a real identity provider instead of demo
  session tokens, an external secret manager, an egress allowlist if you use a
  hosted model API, and alerting on the audit log.
