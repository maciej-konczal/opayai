from __future__ import annotations
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from opayai.types import (IntentMandate, CartMandate, CartItem, Constraint,
                          SpendingLimit, Money, Offer)
from opayai.signing import default_signer
from opayai.events import bus

_counters: dict[str, int] = {}


def reset_ids() -> None:
    _counters.clear()


def _next(prefix: str) -> str:
    _counters[prefix] = _counters.get(prefix, 0) + 1
    return f"{prefix}_{_counters[prefix]}"


def create_intent_mandate(user_id: str, constraint: Constraint,
                          spending_limit: SpendingLimit, ttl_hours: int = 24,
                          now: datetime | None = None) -> IntentMandate:
    now = now or datetime.now(timezone.utc)
    im = IntentMandate(
        id=_next("im"), user_id=user_id, created_at=now,
        expires_at=now + timedelta(hours=ttl_hours), human_present=False,
        constraint=constraint, spending_limit=spending_limit)
    im.signature = default_signer().sign(im)
    bus.publish("intent.created", "user",
                {"id": im.id, "max_total": str(constraint.max_total.amount),
                 "category": constraint.category}, mandate_ref=im.id)
    return im


def propose_cart(intent: IntentMandate, offers: list[Offer], rail: str,
                 rationale: str, now: datetime | None = None) -> CartMandate:
    now = now or datetime.now(timezone.utc)
    items = [CartItem(offer_id=o.id, title=o.title, qty=1, unit_price=o.price)
             for o in offers]
    total = Money(amount=sum((o.price.amount for o in offers), Decimal("0")),
                  currency=offers[0].price.currency if offers else "USD")
    cart = CartMandate(id=_next("cm"), intent_mandate_id=intent.id, items=items,
                       total=total, selected_rail=rail, rationale=rationale,
                       created_at=now)
    cart.signature = default_signer().sign(cart)
    bus.publish("cart.proposed", "agent",
                {"id": cart.id, "total": str(total.amount), "rail": rail,
                 "rationale": rationale}, mandate_ref=intent.id)
    return cart
