from datetime import datetime
from decimal import Decimal
from opayai.types import (Constraint, Money, SpendingLimit, Offer)
from opayai.mandate import create_intent_mandate, propose_cart, reset_ids
from opayai.policy import evaluate_policy


def _offer(id="of_1", price="289", free_returns=True, compat=("macbook",),
           est="2026-07-12"):
    return Offer(id=id, title="Mon", merchant="M", price=Money(amount=Decimal(price)),
                 stock_available=True, stock_qty=3, delivery_est_date=est,
                 delivery_cutoff="2026-07-11T18:00:00", returns_window_days=30,
                 free_returns=free_returns, warranty_months=24,
                 specs={"category": "monitor", "compat": list(compat)}, rating=4.6)


def _intent(max_total="300", per_txn="400", per_period="1000",
            reqs=("free_returns", "compat:macbook", "arrives_by:2026-07-12")):
    reset_ids()
    return create_intent_mandate(
        "u_1",
        Constraint(max_total=Money(amount=Decimal(max_total)), category="monitor",
                   hard_requirements=list(reqs)),
        SpendingLimit(per_transaction=Money(amount=Decimal(per_txn)),
                      per_period=Money(amount=Decimal(per_period))),
        now=datetime(2026, 7, 11, 9, 0, 0))


def test_auto_approve_when_all_pass():
    im = _intent()
    offers = [_offer()]
    cart = propose_cart(im, offers, "x402", "fits", now=datetime(2026, 7, 11, 9, 1))
    dec = evaluate_policy(im, cart, {o.id: o for o in offers})
    assert dec.result == "AUTO_APPROVE"


def test_reject_over_budget():
    im = _intent(max_total="250")
    offers = [_offer(price="289")]
    cart = propose_cart(im, offers, "x402", "fits", now=datetime(2026, 7, 11, 9, 1))
    dec = evaluate_policy(im, cart, {o.id: o for o in offers})
    assert dec.result == "REJECT"
    assert any(c.rule == "budget" and not c.passed for c in dec.checks)


def test_reject_missing_free_returns():
    im = _intent()
    offers = [_offer(free_returns=False)]
    cart = propose_cart(im, offers, "x402", "fits", now=datetime(2026, 7, 11, 9, 1))
    dec = evaluate_policy(im, cart, {o.id: o for o in offers})
    assert dec.result == "REJECT"
    assert any(c.rule == "hard_requirement:free_returns" and not c.passed for c in dec.checks)


def test_escalate_when_period_limit_exceeded():
    im = _intent(per_period="300")
    offers = [_offer(price="289")]
    cart = propose_cart(im, offers, "x402", "fits", now=datetime(2026, 7, 11, 9, 1))
    dec = evaluate_policy(im, cart, {o.id: o for o in offers}, period_spent=Decimal("50"))
    assert dec.result == "ESCALATE"
    assert any(c.rule == "spending_limit:per_period" and not c.passed for c in dec.checks)
