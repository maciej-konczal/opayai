from datetime import datetime, timedelta
from decimal import Decimal
from opayai.types import (
    Money, Constraint, SpendingLimit, IntentMandate,
    CartItem, CartMandate, PolicyCheck, PolicyDecision,
    Event, Receipt, Offer, Order,
)


def _intent() -> IntentMandate:
    return IntentMandate(
        id="im_1", user_id="u_1",
        created_at=datetime(2026, 7, 11, 9, 0, 0),
        expires_at=datetime(2026, 7, 12, 9, 0, 0),
        human_present=False,
        constraint=Constraint(
            max_total=Money(amount=Decimal("300")),
            category="monitor",
            hard_requirements=["free_returns", "compat:macbook"],
        ),
        spending_limit=SpendingLimit(
            per_transaction=Money(amount=Decimal("400")),
            per_period=Money(amount=Decimal("1000")),
        ),
        signature="",
    )


def test_money_is_decimal():
    m = Money(amount=Decimal("12.5"))
    assert m.amount == Decimal("12.5")
    assert m.currency == "USD"


def test_intent_roundtrips_json():
    im = _intent()
    dumped = im.model_dump(mode="json")
    assert dumped["constraint"]["max_total"]["amount"] == "300"
    restored = IntentMandate.model_validate(dumped)
    assert restored == im


def test_cart_and_decision_build():
    cart = CartMandate(
        id="cm_1", intent_mandate_id="im_1",
        items=[CartItem(offer_id="of_1", title="Mon", qty=1,
                        unit_price=Money(amount=Decimal("289")))],
        total=Money(amount=Decimal("289")),
        selected_rail="x402", rationale="fits",
        created_at=datetime(2026, 7, 11, 9, 1, 0), signature="",
    )
    dec = PolicyDecision(
        cart_mandate_id="cm_1", result="AUTO_APPROVE",
        checks=[PolicyCheck(rule="budget", passed=True, detail="289<=300")],
    )
    assert cart.total.amount == Decimal("289")
    assert dec.result == "AUTO_APPROVE"
