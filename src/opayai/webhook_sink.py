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
            ev = json.loads(raw)
        except json.JSONDecodeError:
            ev = {"type": "?", "raw": raw.decode(errors="replace")}
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        note = ev.get("notification")
        if note and note.get("needs_action"):
            print(f"[{ts}] \U0001f514 ACTION  {note['title']} - {note['body']}   "
                  f"(from {ev.get('type')})", flush=True)
        else:
            print(f"[{ts}]    event  #{ev.get('seq', '')} {ev.get('type', '?')} "
                  f"[{ev.get('actor', '')}] {ev.get('payload', {})}", flush=True)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self) -> None:
        msg = (b"opayai webhook sink - this endpoint only RECEIVES posted events; "
               b"watch this terminal for them.\nThe status site (profile / authorize / "
               b"orders) is at http://localhost:8000\n")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        self.wfile.write(msg)

    def log_message(self, *args) -> None:
        pass


def run() -> None:
    port = int(os.environ.get("OPAYAI_WEBHOOK_PORT", "9099"))
    print(f"opayai webhook sink on http://127.0.0.1:{port}  "
          f"(set OPAYAI_WEBHOOK_URL=http://127.0.0.1:{port})")
    ThreadingHTTPServer(("127.0.0.1", port), _Handler).serve_forever()


if __name__ == "__main__":
    run()
