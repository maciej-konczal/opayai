from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from collections.abc import Callable
from typing import Any

from .crypto import canonical_json, now_iso
from .models import OrderEvent


class Ledger:
    """Append-only hash-chain ledger, also serving the SSE event stream."""

    def __init__(self, snapshot_path: Path):
        self.snapshot_path = snapshot_path
        self.events: list[OrderEvent] = []
        self.subscribers: list[asyncio.Queue[OrderEvent]] = []
        self.callbacks: list[Callable[[OrderEvent], None]] = []
        if snapshot_path.exists():
            for line in snapshot_path.read_text().splitlines():
                if line.strip():
                    self.events.append(OrderEvent.model_validate_json(line))

    def append(self, actor: str, event_type: str, payload: dict[str, Any]) -> OrderEvent:
        ts = now_iso()
        prev_hash = self.events[-1].hash if self.events else "0"
        body = {"ts": ts, "actor": actor, "type": event_type, "payload": payload}
        digest = hashlib.sha256((prev_hash + canonical_json(body)).encode()).hexdigest()
        event = OrderEvent(seq=len(self.events) + 1, ts=ts, actor=actor, type=event_type,
                           payload=payload, prev_hash=prev_hash, hash=digest)
        self.events.append(event)
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        with self.snapshot_path.open("a") as log:
            log.write(event.model_dump_json() + "\n")
        for queue in tuple(self.subscribers):
            queue.put_nowait(event)
        for callback in tuple(self.callbacks):
            callback(event)
        return event

    def verify(self, events: list[OrderEvent] | None = None) -> bool:
        previous = "0"
        for event in self.events if events is None else events:
            body = {"ts": event.ts, "actor": event.actor, "type": event.type, "payload": event.payload}
            expected = hashlib.sha256((previous + canonical_json(body)).encode()).hexdigest()
            if event.prev_hash != previous or event.hash != expected:
                return False
            previous = event.hash
        return True

    def for_purchase(self, purchase_id: str) -> list[OrderEvent]:
        return [event for event in self.events if event.payload.get("purchase_id") == purchase_id]

    def subscribe(self, callback: Callable[[OrderEvent], None] | None = None):
        if callback is not None:
            self.callbacks.append(callback)
            return callback
        queue: asyncio.Queue[OrderEvent] = asyncio.Queue()
        self.subscribers.append(queue)
        return queue

    def unsubscribe(self, queue) -> None:
        if queue in self.subscribers:
            self.subscribers.remove(queue)
        if queue in self.callbacks:
            self.callbacks.remove(queue)

    def reset(self) -> None:
        self.events.clear()
        if self.snapshot_path.exists():
            self.snapshot_path.unlink()
