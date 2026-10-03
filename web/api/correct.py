import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import demo_store
from inboxpilot.triage import CATEGORIES


def _respond(handler, status, payload):
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler):
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8") or "{}")


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            body = _read_json(self)
            email_id = body.get("id")
            category = body.get("category")
            urgent = body.get("urgent")  # True | False | None
            seed = int(body.get("seed", 0) or 0)

            if not email_id or category not in CATEGORIES:
                _respond(self, 400, {
                    "error": "bad input",
                    "expected": {
                        "id": "email id (string)",
                        "category": f"one of {list(CATEGORIES)}",
                        "urgent": "true | false | null",
                        "seed": "int, optional",
                    },
                })
                return
            if urgent is not None and not isinstance(urgent, bool):
                _respond(self, 400, {"error": "bad input: 'urgent' must be true, false, or null"})
                return

            tuner_status = demo_store.record_correction(email_id, category, urgent)
            emails, counts = demo_store.triage_all(seed=seed)
            match = next((e for e in emails if e["id"] == email_id), None)
            retriage = match["decision"] if match else None

            _respond(self, 200, {
                "ok": True,
                "email_id": email_id,
                "correction": {"category": category, "urgent": urgent},
                "retriage": retriage,
                "counts": counts,
                "tuner_status": tuner_status,
            })
        except ValueError as exc:  # e.g. unknown category from store
            _respond(self, 400, {"error": str(exc)})
        except Exception as exc:  # never a traceback HTML page
            _respond(self, 500, {"error": str(exc)})

    def log_message(self, *args):
        pass
