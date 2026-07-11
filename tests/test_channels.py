from opayai import channels


class _Rec:
    def __init__(self, name="rec"):
        self.name = name
        self.got = []

    def deliver(self, n):
        self.got.append(n)


class _Boom:
    name = "boom"

    def deliver(self, n):
        raise RuntimeError("channel down")


class _FakeBus:
    def __init__(self):
        self.cb = None

    def subscribe(self, cb):
        self.cb = cb


class _FakeEvent:
    def __init__(self, d):
        self._d = d

    def model_dump(self, mode="json"):
        return dict(self._d)


def test_deliver_fans_out_and_reports_success():
    r = _Rec()
    out = channels.deliver({"title": "x"}, [r])
    assert out == ["rec"] and len(r.got) == 1


def test_failing_channel_does_not_block_others():
    r = _Rec()
    out = channels.deliver({"title": "x"}, [_Boom(), r])
    assert out == ["rec"]  # boom swallowed, rec still delivered


def test_ping_and_webhook_are_env_driven(monkeypatch):
    monkeypatch.setenv("OPAYAI_NOTIFY", "0")            # desktop off
    monkeypatch.delenv("OPAYAI_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("OPAYAI_NOTIFY_EMAIL", raising=False)
    assert channels.ping_channels() == []
    assert channels.event_webhook() is None

    monkeypatch.setenv("OPAYAI_WEBHOOK_URL", "http://localhost:9/hook")
    assert channels.event_webhook().name == "webhook"

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("OPAYAI_NOTIFY_EMAIL", "me@example.com")
    assert [c.name for c in channels.ping_channels()] == ["email"]


def test_desktop_ping_enabled_by_default(monkeypatch):
    monkeypatch.delenv("OPAYAI_NOTIFY", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert [c.name for c in channels.ping_channels()] == ["desktop"]


def test_webhook_receives_full_event_plus_notification(monkeypatch):
    rec = _Rec("webhook")
    monkeypatch.setattr(channels, "event_webhook", lambda: rec)
    monkeypatch.setattr(channels, "ping_channels", lambda: [])
    bus = _FakeBus()
    channels.install(bus)
    bus.cb(_FakeEvent({"seq": 3, "ts": "t", "type": "policy.evaluated", "actor": "policy",
                       "mandate_ref": "im_1", "payload": {"result": "ESCALATE"}}))
    got = rec.got[0]
    assert got["type"] == "policy.evaluated" and got["seq"] == 3
    assert got["payload"] == {"result": "ESCALATE"}          # full event, like the JSONL
    assert got["notification"]["needs_action"] is True       # + the action notification


def test_delivered_update_pings_but_shipped_does_not(monkeypatch):
    rec = _Rec("desktop")
    monkeypatch.setattr(channels, "ping_channels", lambda: [rec])
    monkeypatch.setattr(channels, "event_webhook", lambda: None)
    bus = _FakeBus()
    channels.install(bus)
    bus.cb(_FakeEvent({"type": "order.advanced", "actor": "merchant",
                       "mandate_ref": "im_1", "payload": {"order_id": "o1", "status": "DELIVERED"}}))
    assert len(rec.got) == 1 and rec.got[0]["source_event"] == "order.advanced"
    rec.got.clear()
    bus.cb(_FakeEvent({"type": "order.advanced", "actor": "merchant",
                       "mandate_ref": "im_1", "payload": {"order_id": "o1", "status": "SHIPPED"}}))
    assert rec.got == []   # a shipped update is not push-worthy


def test_webhook_receives_events_without_a_notification(monkeypatch):
    rec = _Rec("webhook")
    monkeypatch.setattr(channels, "event_webhook", lambda: rec)
    monkeypatch.setattr(channels, "ping_channels", lambda: [])
    bus = _FakeBus()
    channels.install(bus)
    bus.cb(_FakeEvent({"seq": 1, "ts": "t", "type": "intent.created", "actor": "user",
                       "mandate_ref": "im_1", "payload": {"id": "im_1"}}))
    got = rec.got[0]
    assert got["type"] == "intent.created"                   # every event reaches the webhook
    assert "notification" not in got                         # no user-facing notification for this one


def test_email_escapes_html_and_sets_idempotency(monkeypatch):
    captured = {}

    def fake_post(url, payload, headers=None, timeout=6):
        captured["payload"] = payload
        captured["headers"] = headers or {}
        return 200

    monkeypatch.setattr(channels, "_post_json", fake_post)
    ch = channels.EmailChannel(api_key="re_x", to="me@example.com",
                               sender="opayai <onboarding@resend.dev>",
                               link="http://localhost:8000")
    ch.deliver({"title": "Approve <script>alert(1)</script>", "body": "buy <b>now</b>",
                "source_event": "policy.evaluated", "mandate_ref": "im_1", "seq": 3})
    body_html = captured["payload"]["html"]
    assert "<script>" not in body_html and "&lt;script&gt;" in body_html
    assert "<b>now</b>" not in body_html and "&lt;b&gt;now" in body_html
    assert captured["headers"].get("Idempotency-Key") == "opayai-policy.evaluated/im_1-3"
