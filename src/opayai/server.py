"""The single public OPayAI MCP server.

The teammate prototype established the discover → suggest → propose → evaluate →
track → resolve vocabulary and proactive notification seams. This module keeps
that host-facing contract while delegating execution to the PLN/BLIK lifecycle
service used by the web app. Human consent is intentionally absent from MCP.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.fastmcp import FastMCP

from opayai.commerce.api import router as api_router
from opayai.commerce.merchant import router as merchant_router
from opayai.commerce.policy import PolicyBlock
from opayai.commerce.rails import lan_ip
from opayai.commerce.service import OPayAIService


INSTRUCTIONS = """OPayAI is a human-controlled agent-commerce backbone.
1. Draft an intent, then wait for the human to sign it in the OPayAI web app.
2. Suggest qualifying and blocked offers with clear reasons, then wait for the
   human to choose one before proposing a cart.
3. A proposed cart always returns awaiting_human_authorization. The agent cannot
   sign, approve, confirm BLIK, or advance fulfillment.
4. Track the order and surface action-needed notifications. A return request is
   also only a proposal until the human signs the exact resolution in the UI.
"""


def _policy_error(error: PolicyBlock) -> dict[str, Any]:
    return {"status": "blocked", "violated_clause": error.clause, "detail": error.detail}


def _offer_summary(offer: dict[str, Any], qualifies: bool, reason: str) -> dict[str, Any]:
    return {
        "offer_id": offer["sku"],
        "title": offer["title"],
        "price": {"amount": offer["price"], "currency": "PLN", "unit": "grosze"},
        "delivery_method": offer["delivery_method"],
        "delivery_estimate_days": offer["delivery_estimate_days"],
        "return_window_days": offer["return_policy"]["window_days"],
        "qualifies": qualifies,
        "match_reason": reason,
    }


def create_mcp(service: OPayAIService) -> FastMCP:
    """Build the one MCP surface used by stdio hosts and `/mcp` HTTP clients."""
    mcp = FastMCP("OPayAI", instructions=INSTRUCTIONS)

    @mcp.tool()
    def draft_intent(description: str) -> dict:
        """Draft purchase constraints; a human must sign them in the OPayAI UI."""
        intent = service.draft_intent(description, agent_id="mcp")
        return {
            "intent_id": intent.id,
            "status": "awaiting_human_authorization",
            "parsed_constraints": intent.constraints.model_dump(mode="json"),
            "next_action": "Ask the human to review and sign the intent in OPayAI.",
        }

    @mcp.tool()
    def search_offers(query: str = "", category: str | None = None,
                      max_price: int | None = None, intent_id: str | None = None) -> dict:
        """Search the PLN catalog and disclose offers blocked by mandate policy."""
        return service.search_products(query, category, max_price, intent_id)

    @mcp.tool()
    def suggest_offers(intent_id: str, limit: int = 3) -> list[dict]:
        """Return a deterministic shortlist with match and policy-block reasons."""
        intent = service.store.intents[intent_id]
        results = service.search_products(
            query="", category=intent.constraints.categories[0], intent_id=intent_id)
        suggestions: list[dict[str, Any]] = []
        for offer in results["offers"]:
            window = offer["return_policy"]["window_days"]
            reason = (
                f"Within the signed budget; {window}-day returns; "
                f"delivery in {offer['delivery_estimate_days']} day(s)."
            )
            suggestions.append(_offer_summary(offer, True, reason))
        for item in results["filtered_out"]:
            offer = item["offer"]
            suggestions.append(_offer_summary(
                offer, False, f"Blocked by policy clause {item['violated_clause']}."))
        service._event(
            "agent", "suggestions_ready", intent_id=intent_id,
            count=min(limit, len(suggestions)),
            qualifying=sum(1 for item in suggestions[:limit] if item["qualifies"]),
        )
        return suggestions[:max(1, limit)]

    @mcp.tool()
    def propose_cart(intent_id: str, offer_id: str, qty: int = 1) -> dict:
        """Propose an exact cart; never sign it or pay for it."""
        try:
            purchase = service.request_purchase(
                intent_id, offer_id, qty, agent_id="mcp", client_info="MCP client")
            return {
                "purchase_id": purchase.id,
                "status": "awaiting_human_authorization",
                "proposal": purchase.proposal,
                "next_action": "Present the exact cart and wait for the human signature.",
            }
        except PolicyBlock as error:
            return _policy_error(error)

    @mcp.tool()
    def evaluate_policy(purchase_id: str) -> dict:
        """Read the deterministic policy result already recorded for a proposal."""
        purchase = service.store.purchases[purchase_id]
        events = service.ledger.for_purchase(purchase_id)
        checks = [event.model_dump(mode="json") for event in events
                  if event.actor == "policy"]
        blocked = next((event for event in reversed(checks)
                        if event["type"] == "policy_block"), None)
        return {
            "purchase_id": purchase_id,
            "result": "BLOCK" if blocked else "PASS",
            "checks": checks,
            "human_authorization_required": purchase.cart is None or purchase.cart.signing is None,
        }

    @mcp.tool()
    def get_order(purchase_id: str, since: int = 0) -> dict:
        """Track order state, lifecycle events, and any pending exception."""
        purchase = service.store.purchases[purchase_id]
        events = service.ledger.for_purchase(purchase_id)
        return {
            "purchase_id": purchase.id,
            "stage": purchase.status,
            "order_status": purchase.order_status,
            "order": purchase.order,
            "events_since_last_call": [event.model_dump(mode="json") for event in events[since:]],
            "pending_exception": purchase.exception.model_dump(mode="json")
            if purchase.exception else None,
            "status_url": f"{os.getenv('OPAYAI_WEB_BASE', 'http://localhost:8000')}/?purchase={purchase.id}",
        }

    @mcp.tool()
    def create_return(purchase_id: str, reason: str) -> dict:
        """Propose a return; a human must sign the exact resolution in OPayAI."""
        try:
            purchase = service.request_return(purchase_id, reason)
            return {
                "purchase_id": purchase.id,
                "status": "awaiting_human_authorization",
                "next_action": "Ask the human to review and sign the return resolution.",
            }
        except PolicyBlock as error:
            return _policy_error(error)

    @mcp.tool()
    def list_purchases() -> list[dict]:
        """List purchases with their current lifecycle state."""
        return [{"purchase_id": purchase.id, "stage": purchase.status,
                 "order_status": purchase.order_status}
                for purchase in service.store.purchases.values()]

    @mcp.tool()
    def get_audit_trail(purchase_id: str) -> dict:
        """Return the hash-chained audit trail and its validation result."""
        events = service.ledger.for_purchase(purchase_id)
        return {
            "purchase_id": purchase_id,
            "hash_chain_valid": service.ledger.verify(),
            "events": [event.model_dump(mode="json") for event in events],
        }

    @mcp.tool()
    def get_notifications(purchase_id: str | None = None, since: int = 0) -> list[dict]:
        """Return action-needed and progress notifications for proactive hosts."""
        from opayai.notify import notifications

        events = service.ledger.events
        if purchase_id:
            events = service.ledger.for_purchase(purchase_id)
        return notifications([event.model_dump(mode="json") for event in events[since:]])

    @mcp.tool()
    def get_evidence_bundle(purchase_id: str) -> dict:
        """Return signed contexts, payment attempts, diffs, and validated ledger evidence."""
        return service.evidence(purchase_id).model_dump(mode="json")

    return mcp


def default_service() -> OPayAIService:
    return OPayAIService(Path(os.getenv("OPAYAI_STATE", ".opayai")))


def create_app() -> FastAPI:
    """Create the unified web, REST, BLIK, SSE, and HTTP-MCP process."""
    service = default_service()
    mcp = create_mcp(service)
    mcp_http_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        from opayai import channels

        print(f"OPayAI is ready at http://{lan_ip()}:8000")
        channels.install(service.ledger)
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="OPayAI", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.service = service

    @app.exception_handler(PolicyBlock)
    async def policy_block(_: Request, error: PolicyBlock):
        return JSONResponse(
            status_code=409,
            content={"status": "blocked", "violated_clause": error.clause,
                     "detail": error.detail},
        )

    app.include_router(api_router)
    app.include_router(merchant_router)
    app.router.routes.extend(mcp_http_app.routes)

    @app.get("/pay/blik/{session_id}", response_class=HTMLResponse)
    def blik_page(session_id: str):
        session = service.rails["blik_lite"].sessions.get(session_id)
        if not session:
            raise HTTPException(404, "Unknown BLIK session")
        amount = f"{session.amount // 100:,}".replace(",", " ") + f",{session.amount % 100:02d} zł"
        return f'''<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OPayAI BLIK</title>
        <style>body{{margin:0;background:#0d1110;color:#f5f5ed;font:16px ui-rounded,system-ui;display:grid;min-height:100vh;place-items:center}}main{{width:min(92vw,370px);background:#f5f5ed;color:#13231d;padding:28px;border-radius:26px;box-shadow:0 20px 70px #0008}}small{{color:#64736d;text-transform:uppercase;letter-spacing:.13em}}h1{{font-size:23px;margin:24px 0 8px}}strong{{font-size:32px}}button{{width:100%;border:0;border-radius:12px;padding:16px;margin-top:12px;font-weight:800;font-size:16px;background:#0aaa64;color:white}}button:last-child{{background:#e8ece7;color:#183027}}</style>
        <main><small>OPayAI · demo store</small><h1>Confirm this BLIK payment?</h1><strong>{amount}</strong><p>You signed the mandate on your laptop. This screen only confirms the payment.</p><form method="post"><button name="decision" value="confirm">Confirm payment</button><button name="decision" value="reject">Decline</button></form></main></html>'''

    @app.post("/pay/blik/{session_id}", response_class=HTMLResponse)
    def blik_confirm(session_id: str, decision: str = Form(...)):
        purchase = service.blik_decision(session_id, decision)
        outcome = "Payment confirmed" if purchase.order_status == "paid" else "Payment declined"
        return HTMLResponse(
            "<meta name='viewport' content='width=device-width'>"
            f"<body style='font-family:system-ui;padding:32px'><h2>{outcome}</h2>"
            "<p>You can close this page and return to OPayAI.</p></body>")

    web_dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if web_dist.exists():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    return app


if __name__ == "__main__":
    from opayai import channels

    runtime_service = default_service()
    channels.install(runtime_service.ledger)
    create_mcp(runtime_service).run()
