"""Mock CRM for the secured agent lab.

All data is fake. The CRM enforces its own scoped API keys, so the agent's
key can only do what the agent needs, even if the workflow is misconfigured.
Standard library only, so it runs without extra packages.
"""
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AGENT_KEY = os.environ["CRM_AGENT_KEY"]
ADMIN_KEY = os.environ["CRM_ADMIN_KEY"]

# Each key gets only the scopes it needs (least privilege).
KEY_SCOPES = {
    AGENT_KEY: {"agent:context", "tool:get_order_status", "tool:create_ticket", "tool:request_refund"},
    ADMIN_KEY: {"admin:audit", "admin:approvals"},
}

# Fake customers. Session tokens stand in for a real customer login: the
# portal sends the token, and the CRM (not the chat message) decides who
# the customer is.
CUSTOMERS = {
    "C-1001": {
        "first_name": "Priya",
        "last_name": "Example",
        "email": "priya@example.com",
        "phone": "+1-555-0101",
        "plan": "Pro",
        "orders": {"ORD-5001": {"status": "shipped", "amount": 49.0}, "ORD-5002": {"status": "processing", "amount": 120.0}},
    },
    "C-1002": {
        "first_name": "Diego",
        "last_name": "Sample",
        "email": "diego@example.com",
        "phone": "+1-555-0102",
        "plan": "Free",
        "orders": {"ORD-5003": {"status": "delivered", "amount": 15.0}},
    },
}
SESSIONS = {"sess-priya-demo": "C-1001", "sess-diego-demo": "C-1002"}

TICKETS, APPROVALS, AUDIT = [], [], []
LOCK = threading.Lock()
ORDER_RE = re.compile(r"^ORD-\d{4}$")
REFUND_LIMIT = 200.0


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def audit(event, **fields):
    with LOCK:
        AUDIT.append({"at": now(), "event": event, **fields})


def summary(cid):
    """Only the fields the agent needs. No email, phone or last name."""
    c = CUSTOMERS[cid]
    return {
        "first_name": c["first_name"],
        "plan": c["plan"],
        "orders": [{"order_id": k, "status": v["status"]} for k, v in c["orders"].items()],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "mock-crm"

    def log_message(self, fmt, *args):  # keep container logs quiet
        pass

    def send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def scopes(self):
        key = self.headers.get("X-API-Key", "")
        for k, s in KEY_SCOPES.items():
            if secrets.compare_digest(key, k):
                return s
        return set()

    def body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 16_384:
            return None
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return None

    def require(self, scope):
        if scope not in self.scopes():
            audit("denied", path=self.path, scope=scope)
            self.send(403, {"error": "forbidden", "missing_scope": scope})
            return False
        return True

    def do_GET(self):
        if self.path == "/health":
            return self.send(200, {"ok": True})
        if self.path == "/admin/audit":
            if self.require("admin:audit"):
                self.send(200, {"audit": AUDIT, "tickets": TICKETS, "approvals": APPROVALS})
            return
        self.send(404, {"error": "not found"})

    def do_POST(self):
        body = self.body()
        if body is None:
            return self.send(400, {"error": "invalid body"})

        if self.path == "/agent/context":
            if not self.require("agent:context"):
                return
            cid = SESSIONS.get(str(body.get("session_token", "")))
            if not cid:
                audit("session_rejected")
                return self.send(200, {"valid": False})
            audit("context_read", customer_id=cid)
            return self.send(200, {"valid": True, "customer_id": cid, "customer": summary(cid)})

        m = re.fullmatch(r"/agent/tools/([a-z_]+)", self.path)
        if m:
            return self.tool(m.group(1), body)

        self.send(404, {"error": "not found"})

    def tool(self, name, body):
        if not self.require(f"tool:{name}"):
            return
        # Re-check identity and arguments server side. Never trust the caller alone.
        cid = SESSIONS.get(str(body.get("session_token", "")))
        if not cid:
            return self.send(401, {"error": "invalid session"})
        args = body.get("args") or {}
        orders = CUSTOMERS[cid]["orders"]

        if name == "get_order_status":
            oid = str(args.get("order_id", ""))
            if not ORDER_RE.match(oid) or oid not in orders:
                audit("tool_rejected", tool=name, customer_id=cid, reason="order not owned")
                return self.send(404, {"error": "order not found for this customer"})
            audit("tool_ok", tool=name, customer_id=cid, order_id=oid)
            return self.send(200, {"order_id": oid, "status": orders[oid]["status"]})

        if name == "create_ticket":
            text = str(args.get("summary", ""))[:200]
            ticket = {"id": f"T-{len(TICKETS) + 1:04d}", "customer_id": cid, "summary": text, "at": now()}
            with LOCK:
                TICKETS.append(ticket)
            audit("tool_ok", tool=name, customer_id=cid, ticket=ticket["id"])
            return self.send(200, {"ticket_id": ticket["id"]})

        if name == "request_refund":
            oid = str(args.get("order_id", ""))
            if not ORDER_RE.match(oid) or oid not in orders:
                return self.send(404, {"error": "order not found for this customer"})
            amount = min(float(orders[oid]["amount"]), REFUND_LIMIT)
            # The agent can only ask. A human approves refunds.
            req = {"id": f"A-{len(APPROVALS) + 1:04d}", "customer_id": cid, "order_id": oid,
                   "amount": amount, "state": "pending_human_approval", "at": now()}
            with LOCK:
                APPROVALS.append(req)
            audit("approval_requested", tool=name, customer_id=cid, approval=req["id"])
            return self.send(200, {"approval_id": req["id"], "state": req["state"]})

        self.send(404, {"error": "unknown tool"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
