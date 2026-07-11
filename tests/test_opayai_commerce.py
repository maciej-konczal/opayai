from pathlib import Path
import json

from opayai.commerce.crypto import demo_assertion
from opayai.commerce.service import OPayAIService


def _sign(service: OPayAIService, context_id: str, context_type: str):
    options = service.signing_options(context_id, context_type)
    return service.verify_signing(context_id, context_type, {"assertion_b64": demo_assertion(options["body"])})


def test_human_signing_blik_and_evidence(tmp_path: Path):
    service = OPayAIService(tmp_path)
    intent = service.draft_intent("Kup monitor USB-C do 1200 zł")
    _sign(service, intent.id, "intent")
    listed = service.search_products(intent_id=intent.id)
    assert listed["offers"]
    purchase = service.request_purchase(intent.id, listed["offers"][0]["sku"], 1, "webapp")
    _sign(service, purchase.id, "cart")
    payment = service.select_rail(purchase.id, "blik_lite", "http://localhost:8000")
    service.confirm_blik_in_chat(purchase.id, "482913")
    assert service.store.purchases[purchase.id].order_status == "paid"
    assert service.store.purchases[purchase.id].payment.attempts[-1]["detail"].endswith("in_chat_prompt")
    evidence = service.evidence(purchase.id)
    assert evidence.hash_chain_valid is True
    assert evidence.cart_mandate and evidence.cart_mandate.signing and evidence.cart_mandate.signing.verified


def test_short_return_offer_is_filtered(tmp_path: Path):
    service = OPayAIService(tmp_path)
    intent = service.draft_intent("Kup opony zimowe do 1600 zł, min. 14 dni na zwrot")
    _sign(service, intent.id, "intent")
    listed = service.search_products(category="winter_tires", intent_id=intent.id)
    clauses = {row["violated_clause"] for row in listed["filtered_out"]}
    assert "return_window_too_short" in clauses


def test_revoked_mandate_blocks_an_agent_proposal(tmp_path: Path):
    service = OPayAIService(tmp_path)
    intent = service.draft_intent("Kup monitor do 1200 zł")
    _sign(service, intent.id, "intent")
    service.revoke_intent(intent.id)
    from opayai.commerce.policy import PolicyBlock
    try:
        service.request_purchase(intent.id, "MON-27-USBC", 1, "mcp")
    except PolicyBlock as error:
        assert error.clause == "mandate_not_open"
    else:
        raise AssertionError("revoked mandate must block")


def test_wrong_item_signed_return_and_merchant_refund(tmp_path: Path):
    service = OPayAIService(tmp_path)
    intent = service.draft_intent("Kup monitor USB-C do 1200 zł")
    _sign(service, intent.id, "intent")
    purchase = service.request_purchase(intent.id, "MON-27-USBC", 1, "mcp")
    _sign(service, purchase.id, "cart")
    payment = service.select_rail(purchase.id, "blik_lite", "http://localhost:8000")
    service.blik_decision(payment["payment"]["rail_ref"], "confirm")
    assert service.merchant_confirm_checkout(purchase.id)["payment_verified"] is True
    order_id = service.store.purchases[purchase.id].order["id"]
    service.inject_fault(order_id, "wrong_item")
    service.advance(order_id)
    service.advance(order_id)
    service.advance(order_id)
    assert service.store.purchases[purchase.id].exception.type == "ITEM_MISMATCH"
    service.approve_resolution(purchase.id)
    _sign(service, purchase.id, "resolution")
    created = service.merchant_create_return(purchase.id, "wrong item")
    assert created["locker_dropoff_code"] == "OPAY-RETURN-482913"
    service.advance(order_id)
    refund = service.merchant_refund(purchase.id)
    assert refund["status"] == "issued"
    assert service.evidence(purchase.id).hash_chain_valid is True


def test_webauthn_mode_requests_platform_registration(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "webauthn")
    service = OPayAIService(tmp_path)
    intent = service.draft_intent("Kup monitor do 1200 zł")
    auth = service.signing_options(intent.id, "intent")
    assert auth == {"auth_mode": "webauthn", "registration_required": True,
                    "context_id": intent.id, "context_type": "intent"}
    registration = service.registration_options()
    assert registration["auth_mode"] == "webauthn"
    assert registration["options"]["authenticatorSelection"]["authenticatorAttachment"] == "platform"


def test_decline_fault_can_be_armed_before_order_exists(tmp_path: Path):
    service = OPayAIService(tmp_path)
    intent = service.draft_intent("Kup monitor USB-C do 1200 zł")
    _sign(service, intent.id, "intent")
    purchase = service.request_purchase(intent.id, "MON-27-USBC", 1, "webapp")
    _sign(service, purchase.id, "cart")
    service.select_rail(purchase.id, "blik_lite", "http://localhost:8000")
    assert purchase.order is None
    service.inject_fault(purchase.id, "decline_payment")
    service.confirm_blik_in_chat(purchase.id, "482913")
    assert purchase.order_status == "payment_failed"
    service.retry_payment(purchase.id, "http://localhost:8000")
    service.confirm_blik_in_chat(purchase.id, "482913")
    assert purchase.order_status == "paid"


def _pending_payment(service: OPayAIService):
    intent = service.draft_intent(
        "Buy a USB-C monitor under PLN 1,200 with at least 14-day returns.")
    _sign(service, intent.id, "intent")
    purchase = service.request_purchase(intent.id, "MON-27-USBC", 1, "webapp")
    _sign(service, purchase.id, "cart")
    service.select_rail(purchase.id, "blik_lite", "http://localhost:8000")
    return intent, purchase


def test_payment_rechecks_revocation_immediately_before_blik(tmp_path: Path):
    service = OPayAIService(tmp_path)
    intent, purchase = _pending_payment(service)
    service.revoke_intent(intent.id)
    from opayai.commerce.policy import PolicyBlock
    try:
        service.confirm_blik_in_chat(purchase.id, "482913")
    except PolicyBlock as error:
        assert error.clause == "mandate_not_open"
    else:
        raise AssertionError("revoked mandate must block payment confirmation")
    assert purchase.payment and purchase.payment.status == "pending"


def test_payment_rejects_cart_mutation_after_signature(tmp_path: Path):
    service = OPayAIService(tmp_path)
    _intent, purchase = _pending_payment(service)
    assert purchase.cart
    purchase.cart.totals["total"] += 1
    from opayai.commerce.policy import PolicyBlock
    try:
        service.confirm_blik_in_chat(purchase.id, "482913")
    except PolicyBlock as error:
        assert error.clause == "cart_authorization_mismatch"
    else:
        raise AssertionError("mutated signed cart must not be paid")
    assert purchase.payment and purchase.payment.status == "pending"


def test_streamable_mcp_exact_path_exposes_proposal_only_tools(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPAYAI_STATE", str(tmp_path))
    from fastapi.testclient import TestClient
    from opayai.server import create_app

    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    with TestClient(create_app(), base_url="http://localhost:8000") as client:
        initialized = client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "pytest", "version": "1"}},
        })
        assert initialized.status_code == 200
        session_headers = {**headers, "mcp-session-id": initialized.headers["mcp-session-id"]}
        client.post("/mcp", headers=session_headers,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        response = client.post("/mcp", headers=session_headers,
                               json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        data_line = next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
        names = [tool["name"] for tool in json.loads(data_line)["result"]["tools"]]
        assert names == ["draft_intent", "search_offers", "suggest_offers",
                         "propose_cart", "evaluate_policy", "get_order",
                         "create_return", "list_purchases", "get_audit_trail",
                         "get_notifications", "get_evidence_bundle"]
        assert not {"request_approval", "authorize_step_up", "execute_payment",
                    "confirm_blik", "advance_order"}.intersection(names)
