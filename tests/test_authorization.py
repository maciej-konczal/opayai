from datetime import datetime, timedelta, timezone
from decimal import Decimal
from opayai.authorization import issue, verify
from opayai.types import CartItem, CartMandate, Money


def _cart(cart_id="cm_1", amount="289"):
    return CartMandate(
        id=cart_id, intent_mandate_id="im_1",
        items=[CartItem(offer_id="of_1", title="Monitor", qty=1,
                        unit_price=Money(amount=Decimal(amount)))],
        total=Money(amount=Decimal(amount)), selected_rail="ap2",
        rationale="fits", created_at=datetime.now(timezone.utc), signature="sig")


def test_proof_is_bound_to_cart_amount_and_kind():
    now = datetime.now(timezone.utc)
    cart = _cart()
    proof = issue("approval", cart, now=now)
    assert verify(proof, "approval", cart, now=now)
    assert not verify(proof, "step_up", cart, now=now)
    assert not verify(proof, "approval", _cart(cart_id="cm_2"), now=now)
    assert not verify(proof, "approval", _cart(amount="290"), now=now)


def test_proof_expires_and_rejects_tampering():
    now = datetime.now(timezone.utc)
    cart = _cart()
    proof = issue("approval", cart, ttl_minutes=1, now=now)
    assert not verify(proof, "approval", cart, now=now + timedelta(minutes=2))
    proof["amount"] = "1"
    assert not verify(proof, "approval", cart, now=now)
