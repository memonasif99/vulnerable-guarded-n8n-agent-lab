"""Mock LLM with an OpenAI-style /v1/chat/completions endpoint.

It is deterministic and offline, so the lab runs without a real model or API
key. It answers with a JSON object {"reply": str, "tool": {...} | null}.

To exercise the workflow's guardrails, it sometimes proposes tools the agent
is not allowed to use. The point is that the workflow must never trust what
the model proposes, whatever the model is.
"""
import json
import os
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_KEY = os.environ["LLM_API_KEY"]
ORDER_RE = re.compile(r"ORD-\d{4}")


def user_text(messages):
    """Return what the customer typed, ignoring the CRM data around it."""
    for m in reversed(messages):
        if m.get("role") == "user":
            content = str(m.get("content", ""))
            found = re.search(r"<user_message>(.*)</user_message>", content, re.S)
            return found.group(1) if found else content
    return ""


def respond(text):
    low = text.lower()
    order = ORDER_RE.search(text)
    if "delete" in low and "account" in low:
        # A tool that is not on the allowlist. The output guard must block it.
        return {"reply": "Deleting your account now.", "tool": {"name": "delete_customer", "args": {}}}
    if "refund" in low and order:
        return {"reply": "I can request a refund for you.",
                "tool": {"name": "request_refund", "args": {"order_id": order.group(0)}}}
    if order:
        return {"reply": "Let me check that order.",
                "tool": {"name": "get_order_status", "args": {"order_id": order.group(0)}}}
    if "ticket" in low or "problem" in low or "broken" in low:
        return {"reply": "I'll open a ticket.", "tool": {"name": "create_ticket", "args": {"summary": text[:200]}}}
    if "link" in low:
        # Output that should be cleaned before it reaches the user.
        return {"reply": "Sure, see <a href='https://example.net/x'>here</a>, https://example.net/help or email help@example.com.", "tool": None}
    return {"reply": "Hi! I can check an order status, open a ticket or request a refund.", "tool": None}


class Handler(BaseHTTPRequestHandler):
    server_version = "mock-llm"

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.send(200, {"ok": True}) if self.path == "/health" else self.send(404, {})

    def do_POST(self):
        auth = self.headers.get("Authorization", "")
        if not secrets.compare_digest(auth, f"Bearer {API_KEY}"):
            return self.send(401, {"error": "unauthorized"})
        if self.path != "/v1/chat/completions":
            return self.send(404, {})
        length = int(self.headers.get("Content-Length") or 0)
        if length > 32_768:
            return self.send(413, {"error": "too large"})
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.send(400, {"error": "bad json"})
        content = json.dumps(respond(user_text(req.get("messages", []))))
        self.send(200, {"choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
