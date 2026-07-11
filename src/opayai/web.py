"""Super simple read-only status site for opayai orders.

Reads the append-only event log the MCP server writes (OPAYAI_EVENT_LOG) and
renders order status + the signed audit trail as HTML. Separate process from the
MCP server; they share state through the log file, so the page reflects whatever
the agent has done. Zero third-party dependencies (stdlib http.server).

Run:  OPAYAI_EVENT_LOG=/path/opayai-events.jsonl python -m opayai.web
Then open http://localhost:8000
"""
from __future__ import annotations
import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def log_path() -> str:
    return os.environ.get("OPAYAI_EVENT_LOG", os.path.expanduser("~/.opayai/events.jsonl"))


def load_events(path: str | None = None) -> list[dict]:
    path = path or log_path()
    events: list[dict] = []
    if not os.path.exists(path):
        return events
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def order_index(events: list[dict]) -> dict[str, dict]:
    """order_id -> {order_id, intent, status, ts} from order.* events (latest wins)."""
    orders: dict[str, dict] = {}
    for e in events:
        if not e.get("type", "").startswith("order."):
            continue
        oid = e.get("payload", {}).get("order_id")
        if not oid:
            continue
        row = orders.setdefault(oid, {"order_id": oid, "intent": e.get("mandate_ref")})
        row["intent"] = e.get("mandate_ref") or row.get("intent")
        row["status"] = e.get("payload", {}).get("status")
        row["ts"] = e.get("ts")
    return orders


def order_detail(events: list[dict], order_id: str) -> dict | None:
    idx = order_index(events)
    if order_id not in idx:
        return None
    row = idx[order_id]
    intent = row.get("intent")
    trail = [e for e in events if e.get("mandate_ref") == intent]
    summary: dict = {"order_id": order_id, "status": row.get("status"), "intent": intent}
    for e in trail:
        p = e.get("payload", {})
        if e["type"] == "intent.created":
            summary["category"] = p.get("category")
            summary["max_total"] = p.get("max_total")
        elif e["type"] == "cart.proposed":
            summary["total"] = p.get("total")
            summary["rail"] = p.get("rail")
        elif e["type"] == "payment.settled":
            summary["amount"] = p.get("amount")
            summary["reference"] = p.get("reference")
    return {"summary": summary, "trail": trail}


_STATUS_COLOR = {
    "PAID": "#2563eb", "SHIPPED": "#7c3aed", "DELIVERED": "#16a34a",
    "CANCELLED": "#6b7280", "RETURN_REQUESTED": "#d97706", "RETURNED": "#dc2626",
}

_FAVICON = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' "
            "viewBox='0 0 128 96' fill='none'><style>.i{stroke:%2316181C}"
            "@media(prefers-color-scheme:dark){.i{stroke:%23F3F4F2}}</style>"
            "<circle class='i' cx='50' cy='48' r='30' stroke-width='11'/>"
            "<circle cx='82' cy='48' r='30' stroke='%2300D179' stroke-width='11'/></svg>")

# Two overlapping rings (ink + signal-green): two agents, one signed transaction.
_BRAND = ('<a class=brand href="/">'
          '<svg class=mark viewBox="0 0 128 96" width="42" height="31" fill="none" aria-hidden="true">'
          '<circle cx="50" cy="48" r="30" stroke="currentColor" stroke-width="7"/>'
          '<circle cx="82" cy="48" r="30" stroke="#00D179" stroke-width="7"/>'
          '</svg><span>opayai</span></a>')

_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3"><title>{title}</title>
<link rel="icon" href="{favicon}">
<style>
:root{{color-scheme:light dark}}
body{{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;max-width:760px;
margin:40px auto;padding:0 20px;color:#e7e9ee;background:#0d1117}}
a{{color:#58a6ff;text-decoration:none}} a:hover{{text-decoration:underline}}
.brand{{display:inline-flex;align-items:center;gap:10px;color:#e7e9ee;font-weight:640;
font-size:22px;letter-spacing:-.04em;margin:0 0 22px}}
.brand:hover{{text-decoration:none}} .brand .mark{{color:#e7e9ee}}
h1{{font-size:20px}} h2{{font-size:15px;color:#9aa4b2;margin-top:28px}}
.badge{{display:inline-block;padding:2px 10px;border-radius:999px;color:#fff;font-size:12px;font-weight:600}}
.card{{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:14px 16px;margin:10px 0}}
table{{width:100%;border-collapse:collapse}} td{{padding:4px 0;color:#c9d1d9}}
td.k{{color:#8b949e;width:120px}}
.ev{{display:flex;gap:10px;padding:6px 0;border-bottom:1px solid #21262d;font-size:13px}}
.ev .seq{{color:#6e7681;width:26px}} .ev .type{{color:#58a6ff;width:190px}}
.ev .actor{{color:#a371f7;width:70px}} .ev .pl{{color:#8b949e;flex:1;word-break:break-word}}
.muted{{color:#6e7681}}
</style></head><body>{brand}{body}</body></html>"""


def _page(title: str, body: str) -> str:
    return _PAGE.format(title=title, body=body, brand=_BRAND, favicon=_FAVICON)


def render_index(events: list[dict]) -> str:
    orders = sorted(order_index(events).values(), key=lambda r: r.get("order_id", ""))
    if not orders:
        body = ("<h1>Orders</h1><p class=muted>No orders yet. Complete a "
                "purchase (via the agent or the CLI) and this refreshes automatically.</p>")
        return _page("opayai orders", body)
    rows = []
    for r in orders:
        color = _STATUS_COLOR.get(r.get("status"), "#6b7280")
        oid = html.escape(r["order_id"])
        rows.append(
            f'<div class=card><a href="/order/{oid}"><b>{oid}</b></a> '
            f'<span class=badge style="background:{color}">{html.escape(str(r.get("status")))}</span>'
            f'<div class=muted>intent {html.escape(str(r.get("intent")))}</div></div>')
    body = "<h1>Orders</h1>" + "".join(rows)
    return _page("opayai orders", body)


def render_order(events: list[dict], order_id: str) -> str:
    d = order_detail(events, order_id)
    if d is None:
        body = f'<h1>Order {html.escape(order_id)}</h1><p class=muted>Not found.</p><p><a href="/">All orders</a></p>'
        return _page(f"Order {order_id}", body)
    s = d["summary"]
    color = _STATUS_COLOR.get(s.get("status"), "#6b7280")
    def row(k, v):
        return f'<tr><td class=k>{k}</td><td>{html.escape(str(v))}</td></tr>' if v is not None else ""
    summary_html = (
        f'<h1>Order {html.escape(order_id)} '
        f'<span class=badge style="background:{color}">{html.escape(str(s.get("status")))}</span></h1>'
        f'<div class=card><table>'
        + row("Item", s.get("category"))
        + row("Paid", (f'{s.get("amount")} via {s.get("rail")}' if s.get("amount") else None))
        + row("Receipt", s.get("reference"))
        + row("Budget", s.get("max_total"))
        + row("Intent", s.get("intent"))
        + '</table></div>')
    evs = []
    for e in d["trail"]:
        evs.append(
            f'<div class=ev><span class=seq>#{e.get("seq")}</span>'
            f'<span class=type>{html.escape(e.get("type",""))}</span>'
            f'<span class=actor>{html.escape(e.get("actor",""))}</span>'
            f'<span class=pl>{html.escape(json.dumps(e.get("payload",{})))}</span></div>')
    body = summary_html + "<h2>Signed audit trail</h2>" + "".join(evs) + '<p><a href="/">All orders</a></p>'
    return _page(f"Order {order_id}", body)


class _Handler(BaseHTTPRequestHandler):
    def _send(self, body: str) -> None:
        payload = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        events = load_events()
        path = self.path.split("?", 1)[0].rstrip("/")
        if path.startswith("/order/"):
            self._send(render_order(events, path[len("/order/"):]))
        else:
            self._send(render_index(events))

    def log_message(self, *args) -> None:
        pass


def run() -> None:
    port = int(os.environ.get("OPAYAI_WEB_PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"opayai status site on http://localhost:{port}  (log: {log_path()})")
    server.serve_forever()


if __name__ == "__main__":
    run()
