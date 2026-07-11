from datetime import datetime
from decimal import Decimal
from opayai.types import CartMandate, CartItem, Money
from opayai.rails import get_rail, MockX402Rail
import opayai.rails as rails_mod


def _cart(rail="x402"):
    return CartMandate(id="cm_1", intent_mandate_id="im_1",
                       items=[CartItem(offer_id="of_1", title="Mon", qty=1,
                                       unit_price=Money(amount=Decimal("289")))],
                       total=Money(amount=Decimal("289")), selected_rail=rail,
                       rationale="fits", created_at=datetime(2026, 7, 11, 9, 1),
                       signature="sig")


def test_x402_charge_returns_receipt():
    rails_mod.reset_rail_ids()
    r = get_rail("x402")
    rec = r.charge(_cart("x402"), now=datetime(2026, 7, 11, 9, 2))
    assert rec.rail == "x402"
    assert rec.amount.amount == Decimal("289")
    assert rec.rail_reference.startswith("x402_")


def test_card_charge_returns_receipt():
    rails_mod.reset_rail_ids()
    rec = get_rail("card").charge(_cart("card"), now=datetime(2026, 7, 11, 9, 2))
    assert rec.rail == "card"
    assert rec.rail_reference.startswith("card_")


def test_unknown_rail_raises():
    try:
        get_rail("nope")
        assert False
    except KeyError:
        assert True
