from opayai import server


def setup_function():
    server.reset_session()


def test_end_to_end_happy_path():
    intent = server.create_intent_mandate(
        user_id="u_1", category="monitor", max_total="300",
        hard_requirements=["free_returns", "compat:macbook", "arrives_by:2026-07-12"],
        per_transaction="400", per_period="1000")
    offers = server.search_offers(category="monitor", max_price="300")
    picked = [o["id"] for o in offers if o["free_returns"]
              and "macbook" in o["specs"].get("compat", [])
              and o["delivery_est_date"] <= "2026-07-12"][:1]
    cart = server.propose_cart(intent_id=intent["id"], offer_ids=picked,
                               rail="x402", rationale="best fit")
    decision = server.evaluate_policy(cart_id=cart["id"])
    assert decision["result"] == "AUTO_APPROVE"
    order = server.execute_payment(cart_id=cart["id"])
    assert order["status"] == "PAID"
    trail = server.get_audit_trail(mandate_ref=intent["id"])
    types = [e["type"] for e in trail]
    assert "intent.created" in types and "payment.settled" in types


def test_escalation_blocks_until_approval():
    intent = server.create_intent_mandate(
        user_id="u_1", category="monitor", max_total="400",
        hard_requirements=[], per_transaction="400", per_period="200")
    offers = server.search_offers(category="monitor", max_price="400")
    picked = [offers[0]["id"]]
    cart = server.propose_cart(intent_id=intent["id"], offer_ids=picked,
                               rail="card", rationale="pick")
    decision = server.evaluate_policy(cart_id=cart["id"])
    assert decision["result"] == "ESCALATE"
    # paying an un-approved escalated cart is refused
    try:
        server.execute_payment(cart_id=cart["id"])
        assert False
    except ValueError:
        assert True
    server.request_approval(cart_id=cart["id"], approved=True)
    order = server.execute_payment(cart_id=cart["id"])
    assert order["status"] == "PAID"


def _pay_a_monitor(per_period="1000"):
    intent = server.create_intent_mandate(
        user_id="u_1", category="monitor", max_total="300",
        hard_requirements=["free_returns", "compat:macbook", "arrives_by:2026-07-12"],
        per_transaction="400", per_period=per_period)
    offers = server.search_offers(category="monitor", max_price="300")
    picked = [o["id"] for o in offers if o["free_returns"]
              and "macbook" in o["specs"].get("compat", [])
              and o["delivery_est_date"] <= "2026-07-12"][:1]
    cart = server.propose_cart(intent_id=intent["id"], offer_ids=picked,
                               rail="x402", rationale="best fit")
    server.evaluate_policy(cart_id=cart["id"])
    return intent, cart


def test_double_payment_is_refused():
    _intent, cart = _pay_a_monitor()
    server.execute_payment(cart_id=cart["id"])
    try:
        server.execute_payment(cart_id=cart["id"])
        assert False
    except ValueError:
        assert True


def test_audit_trail_includes_order_lifecycle():
    intent, cart = _pay_a_monitor()
    order = server.execute_payment(cart_id=cart["id"])
    server.advance_order(order_id=order["id"])
    types = [e["type"] for e in server.get_audit_trail(mandate_ref=intent["id"])]
    assert "order.created" in types and "order.advanced" in types
