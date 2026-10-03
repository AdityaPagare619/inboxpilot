import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import json
from http.server import BaseHTTPRequestHandler

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
            _respond(self, 200, {
                "cost": demo_store.COST_MATH,
                "privacy": demo_store.PRIVACY_COPY,
                "scopes": demo_store.SCOPES_COPY,
                "demo_caveats": [
                    "Demo runs on a fixture inbox with scripted answers",
                    "Real usage needs YOUR TypeSafe API key (BYOK) and YOUR Gmail OAuth client — see the 'Connect your own' cards in the UI",
                    "Thresholds start conservative: digest-heavy first week by design",
                ],
            })
        except Exception as exc:  # never a traceback HTML page
            _respond(self, 500, {"error": str(exc)})

    def log_message(self, *args):
        pass
