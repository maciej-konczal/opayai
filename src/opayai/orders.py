from __future__ import annotations
from datetime import datetime, timedelta, timezone
from opayai.types import CartMandate, Receipt, Order, Event
from opayai.events import bus

_ADVANCE = {"PAID": "SHIPPED", "SHIPPED": "DELIVERED"}


class OrderStore:
    def __init__(self):
        self._orders: dict[str, Order] = {}
        self._intent_ref: dict[str, str] = {}
        self._n = 0

    def _record(self, order: Order, type: str, now: datetime) -> None:
        ref = self._intent_ref.get(order.id, order.cart_mandate_id)
        e = Event(seq=len(order.timeline) + 1, ts=now, type=type, actor="merchant",
                  mandate_ref=ref, payload={"status": order.status})
        order.timeline.append(e)
        bus.publish(type, "merchant", {"order_id": order.id, "status": order.status},
                    mandate_ref=ref)

    def create(self, cart: CartMandate, receipt: Receipt, returns_window_days: int,
               now: datetime | None = None) -> Order:
        now = now or datetime.now(timezone.utc)
        self._n += 1
        o = Order(id=f"ord_{self._n}", cart_mandate_id=cart.id, receipt=receipt,
                  status="PAID", returns_window_days=returns_window_days)
        self._orders[o.id] = o
        self._intent_ref[o.id] = cart.intent_mandate_id
        self._record(o, "order.created", now)
        return o

    def all_orders(self) -> list[Order]:
        return list(self._orders.values())

    def get(self, order_id: str) -> Order:
        return self._orders[order_id]

    def advance(self, order_id: str, now: datetime | None = None) -> Order:
        now = now or datetime.now(timezone.utc)
        o = self._orders[order_id]
        if o.status not in _ADVANCE:
            raise ValueError(f"cannot advance from {o.status}")
        o.status = _ADVANCE[o.status]
        self._record(o, "order.advanced", now)
        return o

    def cancel(self, order_id: str, now: datetime | None = None) -> Order:
        now = now or datetime.now(timezone.utc)
        o = self._orders[order_id]
        if o.status not in ("CREATED", "PAID"):
            raise ValueError(f"cannot cancel from {o.status}")
        o.status = "CANCELLED"
        self._record(o, "order.cancelled", now)
        return o

    def request_return(self, order_id: str, reason: str,
                       now: datetime | None = None) -> Order:
        now = now or datetime.now(timezone.utc)
        o = self._orders[order_id]
        if o.status != "DELIVERED":
            raise ValueError("returns require a delivered order")
        if now > o.receipt.paid_at + timedelta(days=o.returns_window_days):
            raise ValueError("outside returns window")
        o.status = "RETURN_REQUESTED"
        o.exceptions.append(f"return: {reason}")
        self._record(o, "order.return_requested", now)
        return o


store = OrderStore()
