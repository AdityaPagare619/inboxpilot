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


def _read_json(handler):
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8") or "{}")


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            body = _read_json(self)
            seed = int(body.get("seed", 0) or 0)
            raw_cost = body.get("fn_cost", 100)
            fn_cost = min(1000.0, max(100.0, float(raw_cost)))
            preview = body.get("preview")  # {tau_cat, tau_noise, delta} | True | None
            # Frontend sends preview:true + thresholds:{...} for what-if sliders;
            # accept both shapes.
            if preview is True:
                preview = body.get("thresholds")
            apply = bool(body.get("apply", True))

            report = demo_store.run_tune(
                seed=seed, fn_cost=fn_cost, preview=preview, apply=apply)
            _respond(self, 200, report)
        except Exception as exc:  # never a traceback HTML page
            _respond(self, 500, {"error": str(exc)})

    def log_message(self, *args):
        pass
