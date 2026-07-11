from datetime import datetime, timezone
from opayai.events import EventBus


def _fixed_clock():
    return datetime(2026, 7, 11, 9, 0, 0, tzinfo=timezone.utc)


def test_publish_increments_seq_and_notifies():
    seen = []
    bus = EventBus(clock=_fixed_clock)
    bus.subscribe(seen.append)
    e1 = bus.publish("intent.created", "user", {"id": "im_1"}, mandate_ref="im_1")
    e2 = bus.publish("policy.evaluated", "policy", {"result": "AUTO_APPROVE"}, mandate_ref="im_1")
    assert e1.seq == 1 and e2.seq == 2
    assert [e.type for e in seen] == ["intent.created", "policy.evaluated"]


def test_trail_filters_by_mandate_ref():
    bus = EventBus(clock=_fixed_clock)
    bus.publish("a", "agent", {}, mandate_ref="im_1")
    bus.publish("b", "agent", {}, mandate_ref="im_2")
    assert [e.type for e in bus.trail("im_1")] == ["a"]
