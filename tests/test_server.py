from opayai import server
from concurrent.futures import ThreadPoolExecutor


def setup_function():
    server.reset_session()


def test_end_to_end_happy_path():
    intent = server.create_intent_mandate(
        user_id="u_1", category="monitor", max_total="300",
        hard_requirements=["free_returns", "compat:macbook", "arrives_by:2026-07-12"],
        per_transaction="400", per_period="1000", step_up_threshold="100000")
    offers = server.search_offers(category="monitor", max_price="300")
    picked = [o["id"] for o in offers if o["free_returns"]
              and "macbook" in o["specs"].get("compat", [])
              and o["delivery_est_date"] <= "2026-07-12"][:1]
    cart = server.propose_cart(intent_id=intent["id"], offer_ids=picked,
                               rail="ap2", rationale="best fit")
    decision = server.evaluate_policy(cart_id=cart["id"])
    assert decision["result"] == "AUTO_APPROVE"
    order = server.execute_payment(cart_id=cart["id"])
    assert order["status"] == "PAID"
    trail = server.get_audit_trail(mandate_ref=intent["id"])
    types = [e["type"] for e in trail]
    assert "intent.created" in types and "payment.settled" in types


def test_escalation_requires_web_approval():
    from opayai import web
    intent = server.create_intent_mandate(
        user_id="u_1", category="monitor", max_total="400",
        hard_requirements=[], per_transaction="400", per_period="200",
        step_up_threshold="100000")
    offers = server.search_offers(category="monitor", max_price="400")
    picked = [offers[0]["id"]]
    cart = server.propose_cart(intent_id=intent["id"], offer_ids=picked,
                               rail="card", rationale="pick")
    decision = server.evaluate_policy(cart_id=cart["id"])
    assert decision["result"] == "ESCALATE"
    # payment does not pay - it returns PENDING (the agent cannot self-authorize)
    pending = server.execute_payment(cart_id=cart["id"])
    assert pending["status"] == "PENDING_APPROVAL"
    # the human authorizes on the web trusted surface, then payment succeeds
    assert web.authorize(cart["id"], "approval") is True
    order = server.execute_payment(cart_id=cart["id"])
    assert order["status"] == "PAID"


def test_suggest_offers_shortlist_then_buy_the_choice():
    intent = server.create_intent_mandate(
        user_id="u_1", category="monitor", max_total="300",
        hard_requirements=["free_returns", "compat:macbook"],
        per_transaction="400", per_period="1000", step_up_threshold="100000")
    shortlist = server.suggest_offers(intent_id=intent["id"], limit=3)
    # top suggestion qualifies; at least one is disqualified with a reason
    assert shortlist[0]["qualifies"] is True
    assert any(not s["qualifies"] and s["match_reason"] for s in shortlist)
    # the user picks the top one -> the rest of the flow works on that offer
    chosen = shortlist[0]["offer_id"]
    cart = server.propose_cart(intent_id=intent["id"], offer_ids=[chosen],
                               rail="ap2", rationale="user picked")
    assert server.evaluate_policy(cart_id=cart["id"])["result"] == "AUTO_APPROVE"
    assert server.execute_payment(cart_id=cart["id"])["status"] == "PAID"


def _pay_a_monitor(per_period="1000"):
    intent = server.create_intent_mandate(
        user_id="u_1", category="monitor", max_total="300",
        hard_requirements=["free_returns", "compat:macbook", "arrives_by:2026-07-12"],
        per_transaction="400", per_period=per_period, step_up_threshold="100000")
    offers = server.search_offers(category="monitor", max_price="300")
    picked = [o["id"] for o in offers if o["free_returns"]
              and "macbook" in o["specs"].get("compat", [])
              and o["delivery_est_date"] <= "2026-07-12"][:1]
    cart = server.propose_cart(intent_id=intent["id"], offer_ids=picked,
                               rail="ap2", rationale="best fit")
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


def test_concurrent_payment_only_charges_once_in_process():
    _intent, cart = _pay_a_monitor()

    def pay():
        try:
            return server.execute_payment(cart_id=cart["id"])["status"]
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _n: pay(), range(2)))
    assert outcomes.count("PAID") == 1
    assert sum("already paid" in outcome for outcome in outcomes) == 1


def test_audit_trail_includes_order_lifecycle():
    intent, cart = _pay_a_monitor()
    order = server.execute_payment(cart_id=cart["id"])
    server.advance_order(order_id=order["id"])
    types = [e["type"] for e in server.get_audit_trail(mandate_ref=intent["id"])]
    assert "order.created" in types and "order.advanced" in types


def test_step_up_requires_web_passkey():
    from opayai import web
    intent = server.create_intent_mandate(
        user_id="u_1", category="monitor", max_total="300",
        hard_requirements=["free_returns", "compat:macbook"],
        per_transaction="400", per_period="1000", step_up_threshold="250")
    offers = server.search_offers(category="monitor", max_price="300")
    picked = [o["id"] for o in offers if o["free_returns"]
              and "macbook" in o["specs"].get("compat", [])][:1]
    cart = server.propose_cart(intent_id=intent["id"], offer_ids=picked,
                               rail="ap2", rationale="fit")
    dec = server.evaluate_policy(cart_id=cart["id"])
    assert dec["step_up_required"] is True
    # payment returns PENDING until the human authorizes on the trusted surface
    pending = server.execute_payment(cart_id=cart["id"])
    assert pending["status"] == "PENDING_STEP_UP"
    assert web.authorize(cart["id"], "step_up") is True
    order = server.execute_payment(cart_id=cart["id"])
    assert order["status"] == "PAID"
    types = [e["type"] for e in server.get_audit_trail(mandate_ref=intent["id"])]
    assert "authorization.pending" in types and "stepup.authorized" in types


def test_web_proof_is_bound_to_the_cart():
    from opayai import web
    intent = server.create_intent_mandate(
        user_id="u_1", category="monitor", max_total="300",
        hard_requirements=["free_returns", "compat:macbook"],
        per_transaction="400", per_period="1000", step_up_threshold="250")
    offers = server.search_offers(category="monitor", max_price="300")
    picked = [o["id"] for o in offers if o["free_returns"]
              and "macbook" in o["specs"].get("compat", [])][:1]
    cart = server.propose_cart(intent_id=intent["id"], offer_ids=picked,
                               rail="ap2", rationale="fit")
    server.evaluate_policy(cart_id=cart["id"])
    server.execute_payment(cart_id=cart["id"])          # writes the pending request
    # authorizing a different cart id does nothing for this one
    assert web.authorize("cm_does_not_exist", "step_up") is False
    assert server.execute_payment(cart_id=cart["id"])["status"] == "PENDING_STEP_UP"


def test_payment_rechecks_stock_after_policy_decision():
    _intent, cart = _pay_a_monitor()
    offer_id = cart["items"][0]["offer_id"]
    server.SESSION["offers"][offer_id].stock_available = False
    server.SESSION["offers"][offer_id].stock_qty = 0
    try:
        server.execute_payment(cart_id=cart["id"])
        assert False
    except ValueError as exc:
        assert "policy rejected" in str(exc)


def test_order_captures_authoritative_return_window():
    _intent, cart = _pay_a_monitor()
    offer_id = cart["items"][0]["offer_id"]
    expected = server.SESSION["offers"][offer_id].returns_window_days
    order = server.execute_payment(cart_id=cart["id"])
    assert order["returns_window_days"] == expected
