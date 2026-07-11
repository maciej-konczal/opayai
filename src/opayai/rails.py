from __future__ import annotations
from datetime import datetime, timezone
from typing import Protocol
from opayai.types import CartMandate, Receipt
from opayai.events import bus

_counter = {"n": 0}


def reset_rail_ids() -> None:
    _counter["n"] = 0


def _ref(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}_{_counter['n']:04d}"


class PaymentRail(Protocol):
    name: str
    def charge(self, cart: CartMandate, now: datetime | None = None) -> Receipt: ...


class _BaseRail:
    name = "base"

    def charge(self, cart: CartMandate, now: datetime | None = None) -> Receipt:
        now = now or datetime.now(timezone.utc)
        rec = Receipt(id=_ref("rcpt"), cart_mandate_id=cart.id, rail=self.name,
                      amount=cart.total, paid_at=now, rail_reference=_ref(self.name))
        bus.publish("payment.settled", "rail",
                    {"rail": self.name, "amount": str(cart.total.amount),
                     "reference": rec.rail_reference}, mandate_ref=cart.intent_mandate_id)
        return rec


class MockAP2Rail(_BaseRail):
    name = "ap2"


class MockCardRail(_BaseRail):
    name = "card"


_REGISTRY: dict[str, PaymentRail] = {"ap2": MockAP2Rail(), "card": MockCardRail()}


def get_rail(name: str) -> PaymentRail:
    return _REGISTRY[name]
