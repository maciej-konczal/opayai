from __future__ import annotations
from datetime import datetime, timedelta
from opayai.types import CartMandate, Receipt, Order, Event
from opayai.events import bus

_ADVANCE = {"PAID": "SHIPPED", "SHIPPED": "DELIVERED"}


class OrderStore:
    def __init__(self):
        self._orders: dict[str, Order] = {}
        self._n = 0

    def _record(self, order: Order, type: str, now: datetime) -> None:
        e = Event(seq=len(order.timeline) + 1, ts=now, type=type, actor="merchant",
                  mandate_ref=order.cart_mandate_id, payload={"status": order.status})
        order.timeline.append(e)
        bus.publish(type, "merchant", {"order_id": order.id, "status": order.status},
                    mandate_ref=order.cart_mandate_id)

    def create(self, cart: CartMandate, receipt: Receipt, now: datetime | None = None) -> Order:
        now = now or datetime.utcnow()
        self._n += 1
        o = Order(id=f"ord_{self._n}", cart_mandate_id=cart.id, receipt=receipt, status="PAID")
        self._orders[o.id] = o
        self._record(o, "order.created", now)
        return o

    def get(self, order_id: str) -> Order:
        return self._orders[order_id]

    def advance(self, order_id: str, now: datetime | None = None) -> Order:
        now = now or datetime.utcnow()
        o = self._orders[order_id]
        if o.status not in _ADVANCE:
            raise ValueError(f"cannot advance from {o.status}")
        o.status = _ADVANCE[o.status]
        self._record(o, "order.advanced", now)
        return o

    def cancel(self, order_id: str, now: datetime | None = None) -> Order:
        now = now or datetime.utcnow()
        o = self._orders[order_id]
        if o.status not in ("CREATED", "PAID"):
            raise ValueError(f"cannot cancel from {o.status}")
        o.status = "CANCELLED"
        self._record(o, "order.cancelled", now)
        return o

    def request_return(self, order_id: str, reason: str, returns_window_days: int,
                       now: datetime | None = None) -> Order:
        now = now or datetime.utcnow()
        o = self._orders[order_id]
        if o.status != "DELIVERED":
            raise ValueError("returns require a delivered order")
        if now > o.receipt.paid_at + timedelta(days=returns_window_days):
            raise ValueError("outside returns window")
        o.status = "RETURN_REQUESTED"
        o.exceptions.append(f"return: {reason}")
        self._record(o, "order.return_requested", now)
        return o


store = OrderStore()
