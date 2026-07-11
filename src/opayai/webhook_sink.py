"""Local webhook receiver for the demo - prints notifications the server POSTs.

Stands in for Boski's push endpoint so you can see the proactive pings arrive.

Run:   python -m opayai.webhook_sink            (listens on 127.0.0.1:9099)
Then point the opayai server/CLI at it:
       export OPAYAI_WEBHOOK_URL=http://127.0.0.1:9099
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            n = json.loads(raw)
        except json.JSONDecodeError:
            n = {"title": "?", "body": raw.decode(errors="replace")}
        flag = "\U0001f514 ACTION" if n.get("needs_action") else "   update"
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[{ts}] {flag}  {n.get('title', '?')} - {n.get('body', '')}", flush=True)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args) -> None:
        pass


def run() -> None:
    port = int(os.environ.get("OPAYAI_WEBHOOK_PORT", "9099"))
    print(f"opayai webhook sink on http://127.0.0.1:{port}  "
          f"(set OPAYAI_WEBHOOK_URL=http://127.0.0.1:{port})")
    ThreadingHTTPServer(("127.0.0.1", port), _Handler).serve_forever()


if __name__ == "__main__":
    run()
