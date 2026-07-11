"""Super simple read-only status site for opayai orders.

Reads the append-only event log the MCP server writes (OPAYAI_EVENT_LOG) and
renders order status + the audit event trail as HTML. Separate process from the
MCP server; they share state through the log file, so the page reflects whatever
the agent has done. Zero third-party dependencies (stdlib http.server).

Run:  OPAYAI_EVENT_LOG=/path/opayai-events.jsonl python -m opayai.web
Then open http://localhost:8000
"""
from __future__ import annotations
import html
import json
import os
import secrets
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from opayai import notify, data, authstore, authorization

# Per-process CSRF token: rendered into the authorize form and required on POST, so
# a cross-site page (which cannot read this token) cannot forge an authorization.
_CSRF = secrets.token_urlsafe(32)


def _same_origin(origin: str, host: str) -> bool:
    if not origin:
        return True  # non-browser client with no Origin; the CSRF token still gates it
    try:
        netloc = origin.split("//", 1)[1].split("/", 1)[0]
    except IndexError:
        return False
    return netloc == host or netloc.startswith(("localhost", "127.0.0.1"))


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
.note{{border:1px solid #21262d;background:#161b22;border-radius:8px;padding:9px 12px;margin:7px 0;font-size:13px}}
.note.act{{border-color:#8a5a00;background:#221a08}}
.note .t{{font-weight:640}} .note.act .t{{color:#f0b429}} .note .b{{color:#9aa4b2;margin-left:6px}}
button{{background:#238636;color:#fff;border:0;border-radius:7px;padding:9px 15px;
font-size:13px;font-weight:600;cursor:pointer;margin-top:10px}}
button:hover{{background:#2ea043}}
#pkov{{position:fixed;inset:0;background:rgba(0,0,0,.62);display:none;
align-items:center;justify-content:center;z-index:50}}
#pkm{{background:#161b22;border:1px solid #30363d;border-radius:14px;
padding:26px 30px;max-width:320px;text-align:center}}
#pkm .amt{{font-size:22px;font-weight:700;margin:10px 0 2px}}
#pkcancel{{background:#30363d}} #pkcancel:hover{{background:#3d444d}}
</style></head><body>{brand}{body}</body></html>"""


def _page(title: str, body: str) -> str:
    return _PAGE.format(title=title, body=body, brand=_BRAND, favicon=_FAVICON)


def render_index(events: list[dict]) -> str:
    orders = sorted(order_index(events).values(), key=lambda r: r.get("order_id", ""))
    if not orders:
        body = ("<h1>Orders</h1><p><a href='/profile'>Your profile and context</a> &middot; <a href='/authorize'>Authorize</a></p><p class=muted>No orders yet. Complete a "
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
    body = "<h1>Orders</h1><p><a href='/profile'>Your profile and context</a> &middot; <a href='/authorize'>Authorize</a></p>" + "".join(rows)
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
    notes = notify.notifications(d["trail"])
    notes_html = ""
    if notes:
        def note(n):
            cls = "note act" if n["needs_action"] else "note"
            return (f'<div class="{cls}"><span class=t>{html.escape(n["title"])}</span>'
                    f'<span class=b>{html.escape(n["body"])}</span></div>')
        ordered = ([n for n in notes if n["needs_action"]]
                   + [n for n in notes if not n["needs_action"]])
        notes_html = "<h2>Notifications</h2>" + "".join(note(n) for n in ordered)
    evs = []
    for e in d["trail"]:
        evs.append(
            f'<div class=ev><span class=seq>#{e.get("seq")}</span>'
            f'<span class=type>{html.escape(e.get("type",""))}</span>'
            f'<span class=actor>{html.escape(e.get("actor",""))}</span>'
            f'<span class=pl>{html.escape(json.dumps(e.get("payload",{})))}</span></div>')
    body = (summary_html + notes_html + "<h2>Audit event trail</h2>"
            + "".join(evs) + '<p><a href="/">All orders</a></p>')
    return _page(f"Order {order_id}", body)


def render_profile(events: list[dict]) -> str:
    p = data.load_persona()
    convos = data.load_conversations()
    seed = data.load_seed_orders()
    d = p.get("defaults", {})

    def row(k, v):
        return f'<tr><td class=k>{k}</td><td>{html.escape(str(v))}</td></tr>' if v else ""

    budget = d.get("budget", {}).get("amount")
    stepup = d.get("step_up_over", {}).get("amount")
    ship = p.get("shipping", {})
    prefs = ('<div class=card><table>'
             + row("User", f'{p.get("name")} ({p.get("id")})')
             + row("Goals", ", ".join(p.get("goals", [])))
             + row("Motivations", ", ".join(p.get("motivations", [])))
             + row("Style", p.get("communication_style"))
             + row("Default budget", f'${budget}' if budget else None)
             + row("Preferred brands", ", ".join(d.get("brands", [])))
             + row("Sustainability", d.get("sustainability"))
             + row("Risk tolerance", d.get("risk_tolerance"))
             + row("Passkey over", f'${stepup}' if stepup else None)
             + row("Ships to", f'{ship.get("city")}, {ship.get("country")}' if ship else None)
             + '</table></div>')
    pms = "".join(
        f'<div class=card><b>{html.escape(m.get("label", ""))}</b> '
        f'<span class=muted>rail: {html.escape(m.get("rail", ""))}</span>'
        + (' <span class=badge style="background:#16a34a">default</span>' if m.get("default") else "")
        + '</div>' for m in p.get("payment_methods", []))
    conv = "".join(
        f'<div class=ev><span class=actor>{html.escape(c.get("role", ""))}</span>'
        f'<span class=pl>{html.escape(c.get("text", ""))}</span></div>' for c in convos)
    rows = []
    for o in seed:
        amt = o.get("amount", {}).get("amount", "")
        rows.append(f'<div class=card>{html.escape(o.get("item", ""))} - ${html.escape(str(amt))} '
                    f'<span class=muted>{html.escape(o.get("status", ""))} - {html.escape(o.get("date", ""))}</span></div>')
    for r in sorted(order_index(events).values(), key=lambda x: x.get("order_id", "")):
        oid = html.escape(r["order_id"])
        color = _STATUS_COLOR.get(r.get("status"), "#6b7280")
        rows.append(f'<div class=card><a href="/order/{oid}">{oid}</a> '
                    f'<span class=badge style="background:{color}">{html.escape(str(r.get("status")))}</span></div>')
    orders_html = "".join(rows) or '<p class=muted>No orders yet.</p>'
    body = (f'<h1>What Boski knows about {html.escape(str(p.get("name")))}</h1>'
            '<p class=muted>The context your agent uses before it shops. '
            'Give it a product prompt next.</p>'
            '<h2>Preferences</h2>' + prefs
            + '<h2>Payment methods</h2>' + pms
            + '<h2>Remembered from conversations</h2>' + conv
            + '<h2>Recent orders</h2>' + orders_html
            + '<p><a href="/">All orders</a></p>')
    return _page(f'{p.get("name")} - profile', body)


def authorize(cart_id: str, kind: str) -> bool:
    """The trusted-surface action: issue a signed proof for a pending request.

    Only reachable from the web page (a human click), never from the agent.
    """
    req = authstore.read_pending(cart_id, kind)
    if req is None:
        return False
    proof = authorization.issue_fields(kind, cart_id, req["intent_id"],
                                       req["amount"], req["currency"])
    authstore.write_proof(proof)
    return True


# In-page "passkey" confirmation - a clean simulated gesture on the trusted surface
# (no system/1Password dialog, reliable on stage). The backend still records the
# signed Ed25519 proof, and the agent still cannot perform this step.
_PASSKEY_UI = """<div id="pkov"><div id="pkm">
<svg width="46" height="46" viewBox="0 0 24 24" fill="none" stroke="#2ea043" stroke-width="1.5" stroke-linecap="round"><path d="M4 12a8 8 0 0 1 16 0"/><path d="M7 13a5 5 0 0 1 10 0v2"/><path d="M12 11v5"/><path d="M9.6 15.5a6 6 0 0 0 .4 2.6"/></svg>
<div style="margin-top:8px">Authorize this purchase</div>
<div class="amt" id="pkamt"></div>
<div class="muted">Confirm with your passkey</div>
<div style="margin-top:18px">
<button type="button" id="pkgo">Authorize</button>
<button type="button" id="pkcancel">Cancel</button>
</div></div></div>
<script>
(function(){
  var f=null, ov=document.getElementById('pkov');
  window.passkey=function(ev, form){
    ev.preventDefault(); f=form;
    document.getElementById('pkamt').textContent='$'+(form.dataset.amount||'');
    ov.style.display='flex'; return false;
  };
  document.getElementById('pkgo').onclick=function(){ ov.style.display='none'; if(f) f.submit(); };
  document.getElementById('pkcancel').onclick=function(){ ov.style.display='none'; f=null; };
})();
</script>"""


def render_authorize() -> str:
    pending = authstore.list_pending()
    if not pending:
        body = ("<h1>Authorize</h1><p class=muted>Nothing is waiting for your "
                "authorization right now.</p><p><a href='/'>Orders</a></p>")
        return _page("opayai authorize", body)
    cards = []
    for req in pending:
        kind = req.get("kind", "")
        cid = html.escape(req.get("cart_id", ""))
        is_passkey = kind == "step_up"
        amount = html.escape(str(req.get("amount", "")))
        what = "Passkey step-up" if is_passkey else "Approval"
        label = "Authorize with passkey" if is_passkey else "Approve purchase"
        onsubmit = ' onsubmit="return passkey(event, this)"' if is_passkey else ""
        cards.append(
            f'<div class=card><b>{what}</b> - ${amount}'
            f'<div class=muted>cart {cid}</div>'
            f'<form method="post" action="/authorize/{cid}/{html.escape(kind)}" '
            f'data-amount="{amount}"{onsubmit}>'
            f'<input type="hidden" name="csrf" value="{_CSRF}">'
            f'<button type="submit">{label}</button></form></div>')
    body = ("<h1>Authorize</h1>"
            "<p class=muted>This is your trusted surface. Authorizing here - with your "
            "passkey - is the step the agent cannot do for you.</p>"
            + "".join(cards)
            + "<p><a href='/'>Orders</a></p>"
            + _PASSKEY_UI)
    return _page("opayai authorize", body)


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
        if path == "/profile":
            self._send(render_profile(events))
        elif path == "/authorize":
            self._send(render_authorize())
        elif path.startswith("/order/"):
            self._send(render_order(events, path[len("/order/"):]))
        else:
            self._send(render_index(events))

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        fields = urllib.parse.parse_qs(body.decode("utf-8", "replace"))
        csrf_ok = fields.get("csrf", [""])[0] == _CSRF
        origin_ok = _same_origin(self.headers.get("Origin", ""), self.headers.get("Host", ""))
        parts = self.path.split("?", 1)[0].rstrip("/").split("/")
        if len(parts) == 4 and parts[1] == "authorize" and csrf_ok and origin_ok:
            authorize(parts[2], parts[3])
            self.send_response(303)
            self.send_header("Location", "/authorize")
            self.end_headers()
            return
        self.send_response(403)
        self.end_headers()

    def log_message(self, *args) -> None:
        pass


def run() -> None:
    port = int(os.environ.get("OPAYAI_WEB_PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"opayai status site on http://localhost:{port}  (log: {log_path()})")
    server.serve_forever()


if __name__ == "__main__":
    run()
