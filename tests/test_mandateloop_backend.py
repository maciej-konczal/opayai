from pathlib import Path

from backend.app.crypto import demo_assertion
from backend.app.service import MandateLoopService


def _sign(service: MandateLoopService, context_id: str, context_type: str):
    options = service.signing_options(context_id, context_type)
    return service.verify_signing(context_id, context_type, {"assertion_b64": demo_assertion(options["body"])})


def test_human_signing_blik_and_evidence(tmp_path: Path):
    service = MandateLoopService(tmp_path)
    intent = service.draft_intent("Kup monitor USB-C do 1200 zł")
    _sign(service, intent.id, "intent")
    listed = service.search_products(intent_id=intent.id)
    assert listed["offers"]
    purchase = service.request_purchase(intent.id, listed["offers"][0]["sku"], 1, "webapp")
    _sign(service, purchase.id, "cart")
    payment = service.select_rail(purchase.id, "blik_lite", "http://localhost:8000")
    service.blik_decision(payment["payment"]["rail_ref"], "confirm")
    assert service.store.purchases[purchase.id].order_status == "paid"
    evidence = service.evidence(purchase.id)
    assert evidence.hash_chain_valid is True
    assert evidence.cart_mandate and evidence.cart_mandate.signing and evidence.cart_mandate.signing.verified


def test_short_return_offer_is_filtered(tmp_path: Path):
    service = MandateLoopService(tmp_path)
    intent = service.draft_intent("Kup opony zimowe do 1600 zł, min. 14 dni na zwrot")
    _sign(service, intent.id, "intent")
    listed = service.search_products(category="winter_tires", intent_id=intent.id)
    clauses = {row["violated_clause"] for row in listed["filtered_out"]}
    assert "return_window_too_short" in clauses


def test_revoked_mandate_blocks_an_agent_proposal(tmp_path: Path):
    service = MandateLoopService(tmp_path)
    intent = service.draft_intent("Kup monitor do 1200 zł")
    _sign(service, intent.id, "intent")
    service.revoke_intent(intent.id)
    from backend.app.policy import PolicyBlock
    try:
        service.request_purchase(intent.id, "MON-27-USBC", 1, "mcp")
    except PolicyBlock as error:
        assert error.clause == "mandate_not_open"
    else:
        raise AssertionError("revoked mandate must block")
