from __future__ import annotations
from datetime import datetime, timezone
from typing import Callable
from opayai.types import Event


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EventBus:
    def __init__(self, clock: Callable[[], datetime] = _utc_now):
        self._clock = clock
        self._seq = 0
        self._events: list[Event] = []
        self._subs: list[Callable[[Event], None]] = []

    def subscribe(self, cb: Callable[[Event], None]) -> None:
        self._subs.append(cb)

    def publish(self, type: str, actor: str, payload: dict,
                mandate_ref: str | None = None) -> Event:
        self._seq += 1
        e = Event(seq=self._seq, ts=self._clock(), type=type, actor=actor,
                  mandate_ref=mandate_ref, payload=payload)
        self._events.append(e)
        for cb in self._subs:
            cb(e)
        return e

    def all(self) -> list[Event]:
        return list(self._events)

    def trail(self, mandate_ref: str | None = None) -> list[Event]:
        if mandate_ref is None:
            return self.all()
        return [e for e in self._events if e.mandate_ref == mandate_ref]


bus = EventBus()
