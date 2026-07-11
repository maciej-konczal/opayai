from opayai.web import (order_index, order_detail, render_index, render_order,
                        render_profile)

EVENTS = [
    {"seq": 1, "type": "intent.created", "actor": "user", "mandate_ref": "im_1",
     "payload": {"id": "im_1", "max_total": "300", "category": "monitor"}},
    {"seq": 2, "type": "cart.proposed", "actor": "agent", "mandate_ref": "im_1",
     "payload": {"id": "cm_1", "total": "289.00", "rail": "ap2"}},
    {"seq": 3, "type": "payment.settled", "actor": "rail", "mandate_ref": "im_1",
     "payload": {"rail": "ap2", "amount": "289.00", "reference": "ap2_0002"}},
    {"seq": 4, "type": "order.created", "actor": "merchant", "mandate_ref": "im_1",
     "payload": {"order_id": "ord_1", "status": "PAID"}},
    {"seq": 5, "type": "order.advanced", "actor": "merchant", "mandate_ref": "im_1",
     "payload": {"order_id": "ord_1", "status": "SHIPPED"}},
    {"seq": 6, "type": "order.advanced", "actor": "merchant", "mandate_ref": "im_1",
     "payload": {"order_id": "ord_1", "status": "DELIVERED"}},
]


def test_order_index_tracks_latest_status():
    idx = order_index(EVENTS)
    assert idx["ord_1"]["status"] == "DELIVERED"
    assert idx["ord_1"]["intent"] == "im_1"


def test_order_detail_summarizes_and_keeps_full_trail():
    d = order_detail(EVENTS, "ord_1")
    assert d["summary"]["status"] == "DELIVERED"
    assert d["summary"]["amount"] == "289.00"
    assert d["summary"]["reference"] == "ap2_0002"
    assert d["summary"]["category"] == "monitor"
    # the whole story is present, not just post-payment
    types = [e["type"] for e in d["trail"]]
    assert types[0] == "intent.created" and "order.advanced" in types


def test_order_detail_missing_returns_none():
    assert order_detail(EVENTS, "ord_999") is None


def test_profile_shows_persona_context():
    out = render_profile(EVENTS)
    assert "Alex Rivera" in out                      # who Boski thinks you are
    assert "Visa ****4242" in out                    # a configured payment method
    assert "MacBook" in out                          # remembered from conversations
    assert "ord_1" in out                            # a recent (live) order


def test_render_pages_include_status_and_escape():
    assert "DELIVERED" in render_order(EVENTS, "ord_1")
    assert "ord_1" in render_index(EVENTS)
    # unknown order renders a not-found page, not a crash
    assert "Not found" in render_order(EVENTS, "ord_x")
