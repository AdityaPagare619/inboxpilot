import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import demo_store


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
            seed = int(q.get("seed", ["0"])[0] or "0")
            entries = demo_store.build_audit(seed=seed)
            _, counts = demo_store.triage_all(seed=seed)
            _respond(self, 200, {
                "entries": entries,
                "note": "Newest first. Session memory only — resets on cold start.",
                "counts": counts,
            })
        except Exception as exc:  # never a traceback HTML page
            _respond(self, 500, {"error": str(exc)})

    def log_message(self, *args):
        pass
