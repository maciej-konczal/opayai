from datetime import datetime
from decimal import Decimal
from opayai.types import CartMandate, CartItem, Money, Receipt
from opayai.orders import OrderStore


def _cart():
    return CartMandate(id="cm_1", intent_mandate_id="im_1",
                       items=[CartItem(offer_id="of_1", title="Mon", qty=1,
                                       unit_price=Money(amount=Decimal("289")))],
                       total=Money(amount=Decimal("289")), selected_rail="ap2",
                       rationale="fits", created_at=datetime(2026, 7, 11, 9, 1), signature="s")


def _receipt():
    return Receipt(id="rcpt_1", cart_mandate_id="cm_1", rail="ap2",
                   amount=Money(amount=Decimal("289")), paid_at=datetime(2026, 7, 11, 9, 2),
                   rail_reference="ap2_0001")


def test_create_is_paid_and_advances():
    s = OrderStore()
    o = s.create(_cart(), _receipt())
    assert o.status == "PAID"
    assert s.advance(o.id).status == "SHIPPED"
    assert s.advance(o.id).status == "DELIVERED"


def test_cancel_only_before_shipped():
    s = OrderStore()
    o = s.create(_cart(), _receipt())
    assert s.cancel(o.id).status == "CANCELLED"
    o2 = s.create(_cart(), _receipt())
    s.advance(o2.id)  # SHIPPED
    try:
        s.cancel(o2.id)
        assert False
    except ValueError:
        assert True


def test_return_requires_delivered_and_in_window():
    s = OrderStore()
    o = s.create(_cart(), _receipt())
    s.advance(o.id); s.advance(o.id)  # DELIVERED
    r = s.request_return(o.id, "changed mind", returns_window_days=30,
                         now=datetime(2026, 7, 15, 9, 0))
    assert r.status == "RETURN_REQUESTED"
