from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .policy import PolicyBlock
from .service import MandateLoopService


def create_mcp(service: MandateLoopService) -> FastMCP:
    mcp = FastMCP("OPayAI")

    @mcp.tool()
    def search_products(query: str, category: str | None = None, max_price: int | None = None) -> dict:
        """Find offers. Open mandates filter unsuitable products and disclose the clause."""
        return service.search_products(query, category, max_price)

    @mcp.tool()
    def draft_intent(description: str) -> dict:
        """Create an unsigned intent draft. A human must sign it in the web app."""
        intent = service.draft_intent(description, agent_id="mcp")
        return {"intent_id": intent.id, "parsed_constraints": intent.constraints.model_dump(mode="json"), "missing": ["human signature in the OPayAI web app"]}

    @mcp.tool()
    def request_purchase(intent_id: str, sku: str, qty: int = 1) -> dict:
        """Propose, never buy. It creates a web approval sheet for the human."""
        try:
            purchase = service.request_purchase(intent_id, sku, qty, agent_id="mcp", client_info="MCP client")
            return {"purchase_id": purchase.id, "status": "awaiting_human_authorization", "proposal": purchase.proposal}
        except PolicyBlock as error:
            return {"status": "blocked", "violated_clause": error.clause, "detail": error.detail}

    @mcp.tool()
    def get_purchase_status(purchase_id: str, since: int = 0) -> dict:
        """Read lifecycle events and pending exceptions. This cannot consent or pay."""
        purchase = service.store.purchases[purchase_id]
        events = service.ledger.for_purchase(purchase_id)
        return {"stage": purchase.status, "order_status": purchase.order_status,
                "events_since_last_call": [event.model_dump(mode="json") for event in events[since:]],
                "pending_exception": purchase.exception.model_dump(mode="json") if purchase.exception else None}

    @mcp.tool()
    def initiate_return(purchase_id: str, reason: str) -> dict:
        """Propose a return. A human signs the resolution in the web app."""
        try:
            service.request_return(purchase_id, reason)
            return {"status": "awaiting_human_authorization"}
        except PolicyBlock as error:
            return {"status": "blocked", "violated_clause": error.clause, "detail": error.detail}

    @mcp.tool()
    def list_purchases() -> list[dict]:
        return [{"purchase_id": p.id, "stage": p.status, "order_status": p.order_status} for p in service.store.purchases.values()]

    @mcp.tool()
    def get_evidence_bundle(purchase_id: str) -> dict:
        return service.evidence(purchase_id).model_dump(mode="json")

    return mcp
