"""Local HTTP bridge for the browser demo.

The MCP server remains the source of truth. This adapter only translates
browser requests into the same tool calls, so the web UI can use the complete
mandate -> policy -> passkey -> payment -> order -> return workflow locally.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from opayai import server


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, body: dict) -> None:
        raw = json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self) -> None:
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}")
            if self.path == "/checkout/start":
                intent = server.create_intent_mandate(
                    user_id="boski-demo", category="laptop", max_total="9000",
                    hard_requirements=["free_returns"], per_transaction="9000",
                    per_period="18000", step_up_threshold="1",
                )
                return self._json(200, {"intent": intent, "offers": server.suggest_offers(intent["id"], 3)})
            if self.path == "/checkout/select":
                cart = server.propose_cart(data["intent_id"], [data["offer_id"]], "card", "Selected in Boski")
                return self._json(200, {"cart": cart, "policy": server.evaluate_policy(cart["id"])})
            if self.path == "/checkout/approve":
                return self._json(200, server.request_approval(data["cart_id"], True))
            if self.path == "/checkout/passkey":
                return self._json(200, server.authorize_step_up(data["cart_id"]))
            if self.path == "/checkout/pay":
                return self._json(200, server.execute_payment(data["cart_id"]))
            if self.path == "/order/advance":
                return self._json(200, server.advance_order(data["order_id"]))
            if self.path == "/order/return":
                return self._json(200, server.create_return(data["order_id"], "Not the right fit"))
            return self._json(404, {"error": "unknown endpoint"})
        except Exception as exc:
            return self._json(400, {"error": str(exc)})

    def log_message(self, *_: object) -> None: pass


def run() -> None:
    server.reset_session()
    http = ThreadingHTTPServer(("127.0.0.1", 8787), Handler)
    print("opayai browser bridge on http://127.0.0.1:8787")
    http.serve_forever()


if __name__ == "__main__":
    run()
