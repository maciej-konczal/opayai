"""Background fulfillment - advance orders over time.

So the "shipped" and "delivered" notifications arrive proactively, later, without
the agent or the user asking. A daemon thread ticks and advances each order once
enough time has passed since it was placed. Each transition publishes to the event
bus, so the webhook/notifications fire on their own.

Env:
  OPAYAI_FULFILLMENT=0     disable (default on)
  OPAYAI_SHIP_SECONDS      seconds after order placed -> SHIPPED (default 20)
  OPAYAI_DELIVER_SECONDS   seconds after order placed -> DELIVERED (default 40)
"""
from __future__ import annotations
import os
import threading
import time
from datetime import datetime, timezone


def _placed_at(order) -> datetime:
    ts = order.timeline[0].ts
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def advance_due(store, now: datetime, ship_secs: float, deliver_secs: float) -> None:
    """Advance any order whose next fulfillment step is due (idempotent per tick)."""
    for o in store.all_orders():
        if not o.timeline:
            continue
        elapsed = (now - _placed_at(o)).total_seconds()
        try:
            if o.status == "PAID" and elapsed >= ship_secs:
                store.advance(o.id, now=now)
            elif o.status == "SHIPPED" and elapsed >= deliver_secs:
                store.advance(o.id, now=now)
        except Exception:
            pass


def start(interval: float = 2.0) -> None:
    if os.environ.get("OPAYAI_FULFILLMENT", "1") == "0":
        return
    from opayai.orders import store
    ship = float(os.environ.get("OPAYAI_SHIP_SECONDS", "20"))
    deliver = float(os.environ.get("OPAYAI_DELIVER_SECONDS", "40"))

    def loop() -> None:
        while True:
            time.sleep(interval)
            advance_due(store, datetime.now(timezone.utc), ship, deliver)

    threading.Thread(target=loop, daemon=True).start()
