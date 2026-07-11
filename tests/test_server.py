from pathlib import Path

from opayai.commerce.crypto import demo_assertion
from opayai.commerce.service import OPayAIService
from opayai.server import create_mcp


EXPECTED_TOOLS = [
    "draft_intent", "search_offers", "suggest_offers", "propose_cart",
    "evaluate_policy", "get_order", "create_return", "list_purchases",
    "get_audit_trail", "get_notifications", "get_evidence_bundle",
]


def _runtime(tmp_path: Path):
    service = OPayAIService(tmp_path)
    mcp = create_mcp(service)
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    return service, tools


def _sign_intent(service: OPayAIService, intent_id: str) -> None:
    options = service.signing_options(intent_id, "intent")
    service.verify_signing(
        intent_id, "intent", {"assertion_b64": demo_assertion(options["body"])})


def test_unified_surface_has_no_consent_or_payment_tools(tmp_path: Path):
    _service, tools = _runtime(tmp_path)
    assert list(tools) == EXPECTED_TOOLS
    forbidden = {"request_approval", "authorize_step_up", "execute_payment",
                 "confirm_blik", "advance_order", "approve_resolution"}
    assert forbidden.isdisjoint(tools)


def test_draft_and_suggestions_preserve_human_gate(tmp_path: Path):
    service, tools = _runtime(tmp_path)
    drafted = tools["draft_intent"].fn(
        "Buy winter tires under PLN 1,600 with at least 14-day returns.")
    assert drafted["status"] == "awaiting_human_authorization"
    _sign_intent(service, drafted["intent_id"])
    suggestions = tools["suggest_offers"].fn(drafted["intent_id"], 4)
    assert suggestions[0]["qualifies"] is True
    assert any(not item["qualifies"] and item["match_reason"] for item in suggestions)


def test_proposed_cart_waits_for_human_and_policy_is_read_only(tmp_path: Path):
    service, tools = _runtime(tmp_path)
    intent = service.draft_intent(
        "Buy winter tires under PLN 1,600 with at least 14-day returns.")
    _sign_intent(service, intent.id)
    proposal = tools["propose_cart"].fn(intent.id, "TIR-205-WINTER", 1)
    assert proposal["status"] == "awaiting_human_authorization"
    result = tools["evaluate_policy"].fn(proposal["purchase_id"])
    assert result["result"] == "PASS"
    assert result["human_authorization_required"] is True
    assert service.store.purchases[proposal["purchase_id"]].payment is None


def test_notifications_reuse_teammate_proactive_layer(tmp_path: Path):
    _service, tools = _runtime(tmp_path)
    tools["draft_intent"].fn("Buy a monitor under PLN 1,200 with returns.")
    notifications = tools["get_notifications"].fn()
    assert notifications[-1]["needs_action"] is True
    assert "mandate" in notifications[-1]["title"].lower()
