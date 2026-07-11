from opayai.notify import notification_for, notifications


def test_step_up_needs_action():
    n = notification_for({"type": "policy.evaluated",
                          "payload": {"result": "AUTO_APPROVE", "step_up_required": True}})
    assert n["needs_action"] is True and n["level"] == "action_required"


def test_escalate_and_reject_need_action():
    assert notification_for({"type": "policy.evaluated", "payload": {"result": "ESCALATE"}})["needs_action"]
    assert notification_for({"type": "policy.evaluated", "payload": {"result": "REJECT"}})["needs_action"]


def test_suggestions_ready_is_a_decision():
    assert notification_for({"type": "suggestions.ready", "payload": {"count": 3}})["needs_action"] is True


def test_clean_auto_approve_is_not_a_ping():
    assert notification_for({"type": "policy.evaluated",
                             "payload": {"result": "AUTO_APPROVE", "step_up_required": False}}) is None


def test_progress_updates_are_not_actions():
    assert notification_for({"type": "payment.settled",
                             "payload": {"amount": "289.00", "rail": "ap2"}})["needs_action"] is False
    assert notification_for({"type": "order.advanced",
                             "payload": {"status": "SHIPPED"}})["needs_action"] is False


def test_delivered_is_pushed_but_shipped_is_not():
    delivered = notification_for({"type": "order.advanced", "payload": {"status": "DELIVERED"}})
    shipped = notification_for({"type": "order.advanced", "payload": {"status": "SHIPPED"}})
    assert delivered["push"] is True and delivered["needs_action"] is False
    assert shipped["push"] is False


def test_action_items_are_always_pushed():
    n = notification_for({"type": "policy.evaluated", "payload": {"result": "ESCALATE"}})
    assert n["needs_action"] is True and n["push"] is True


def test_notifications_filters_by_mandate():
    events = [{"type": "payment.settled", "payload": {"amount": "1", "rail": "ap2"}, "mandate_ref": "im_1"},
              {"type": "order.advanced", "payload": {"status": "SHIPPED"}, "mandate_ref": "im_2"}]
    out = notifications(events, mandate_ref="im_1")
    assert len(out) == 1 and out[0]["source_event"] == "payment.settled"
