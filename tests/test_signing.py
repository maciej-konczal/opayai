from datetime import datetime
from decimal import Decimal
from opayai.types import IntentMandate, Constraint, Money, SpendingLimit
from opayai.signing import Signer, canonical_payload


def _im(sig=""):
    return IntentMandate(
        id="im_1", user_id="u_1",
        created_at=datetime(2026, 7, 11, 9, 0, 0),
        expires_at=datetime(2026, 7, 12, 9, 0, 0),
        constraint=Constraint(max_total=Money(amount=Decimal("300")), category="monitor"),
        spending_limit=SpendingLimit(
            per_transaction=Money(amount=Decimal("400")),
            per_period=Money(amount=Decimal("1000"))),
        signature=sig,
    )


def test_canonical_payload_ignores_signature():
    assert canonical_payload(_im("A")) == canonical_payload(_im("B"))


def test_sign_and_verify_roundtrip():
    s = Signer()
    im = _im()
    sig = s.sign(im)
    signed = im.model_copy(update={"signature": sig})
    assert s.verify(signed, sig) is True


def test_tampered_object_fails_verify():
    s = Signer()
    im = _im()
    sig = s.sign(im)
    tampered = im.model_copy(update={
        "constraint": Constraint(max_total=Money(amount=Decimal("999")), category="monitor"),
        "signature": sig,
    })
    assert s.verify(tampered, sig) is False
