from datetime import datetime
from decimal import Decimal
from opayai.types import Constraint, Money, SpendingLimit, Offer
from opayai.signing import default_signer
from opayai.mandate import create_intent_mandate, propose_cart
from opayai.events import EventBus
import opayai.mandate as mandate_mod


def _now():
    return datetime(2026, 7, 11, 9, 0, 0)


def _offer():
    return Offer(id="of_1", title="Mon", merchant="M", price=Money(amount=Decimal("289")),
                 stock_available=True, stock_qty=3, delivery_est_date="2026-07-12",
                 delivery_cutoff="2026-07-11T18:00:00", returns_window_days=30,
                 free_returns=True, warranty_months=24, specs={"category": "monitor"}, rating=4.6)


def test_intent_is_signed_and_published(monkeypatch):
    b = EventBus()
    monkeypatch.setattr(mandate_mod, "bus", b)
    mandate_mod.reset_ids()
    im = create_intent_mandate(
        "u_1",
        Constraint(max_total=Money(amount=Decimal("300")), category="monitor"),
        SpendingLimit(per_transaction=Money(amount=Decimal("400")),
                      per_period=Money(amount=Decimal("1000"))),
        now=_now())
    assert im.id == "im_1"
    assert default_signer().verify(im, im.signature) is True
    assert [e.type for e in b.all()] == ["intent.created"]


def test_cart_totals_and_signed(monkeypatch):
    b = EventBus()
    monkeypatch.setattr(mandate_mod, "bus", b)
    mandate_mod.reset_ids()
    im = create_intent_mandate(
        "u_1",
        Constraint(max_total=Money(amount=Decimal("300")), category="monitor"),
        SpendingLimit(per_transaction=Money(amount=Decimal("400")),
                      per_period=Money(amount=Decimal("1000"))),
        now=_now())
    cart = propose_cart(im, [_offer()], rail="ap2", rationale="fits", now=_now())
    assert cart.total.amount == Decimal("289")
    assert cart.intent_mandate_id == im.id
    assert default_signer().verify(cart, cart.signature) is True
