import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import demo_store
from inboxpilot.triage import build_questions


def _respond(handler, status, payload):
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            q = parse_qs(urlparse(self.path).query)
            email_id = q.get("id", [None])[0]
            seed = int(q.get("seed", ["0"])[0] or "0")
            emails, _ = demo_store.triage_all(seed=seed)
            match = next((e for e in emails if e["id"] == email_id), None)
            if match is None:
                _respond(self, 404, {"error": f"unknown email id {email_id!r}"})
                return
            email = {k: v for k, v in match.items() if k != "decision"}
            _respond(self, 200, {
                "email": email,
                "decision": match["decision"],
                "questions": build_questions(),
                "thresholds": demo_store.get_thresholds(),
                "contacts": demo_store.DEMO_CONTACTS,
                "honesty": [
                    "Answers are scripted for the demo (mock-jev-1.13.0)",
                    "Real Jev flips 1.3-2.2% of answers on identical repeats — nothing is presented as certain",
                ],
            })
        except Exception as exc:  # never a traceback HTML page
            _respond(self, 500, {"error": str(exc)})

    def log_message(self, *args):
        pass
