from datetime import datetime, timedelta, timezone
from decimal import Decimal
from opayai.types import CartMandate, CartItem, Money, Receipt
from opayai.orders import OrderStore
from opayai.fulfillment import advance_due

T0 = datetime(2026, 7, 11, 9, 0, 0, tzinfo=timezone.utc)


def _cart():
    return CartMandate(
        id="cm_1", intent_mandate_id="im_1",
        items=[CartItem(offer_id="of_1", title="Mon", qty=1,
                        unit_price=Money(amount=Decimal("289")))],
        total=Money(amount=Decimal("289")), selected_rail="ap2", rationale="x",
        created_at=T0, signature="s")


def _receipt():
    return Receipt(id="rcpt_1", cart_mandate_id="cm_1", rail="ap2",
                   amount=Money(amount=Decimal("289")), paid_at=T0, rail_reference="ap2_0001")


def _at(secs):
    return T0 + timedelta(seconds=secs)


def test_ticker_ships_then_delivers_over_time():
    store = OrderStore()
    o = store.create(_cart(), _receipt(), returns_window_days=30, now=T0)
    assert o.status == "PAID"

    advance_due(store, _at(10), ship_secs=20, deliver_secs=40)      # too early
    assert store.get(o.id).status == "PAID"

    advance_due(store, _at(25), ship_secs=20, deliver_secs=40)      # ship due
    assert store.get(o.id).status == "SHIPPED"

    advance_due(store, _at(45), ship_secs=20, deliver_secs=40)      # deliver due
    assert store.get(o.id).status == "DELIVERED"

    advance_due(store, _at(100), ship_secs=20, deliver_secs=40)     # idempotent - stays
    assert store.get(o.id).status == "DELIVERED"
