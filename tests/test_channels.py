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


def test_deliver_fans_out_and_reports_success():
    r = _Rec()
    out = channels.deliver({"title": "x", "body": "y", "needs_action": True}, [r])
    assert out == ["rec"] and len(r.got) == 1


def test_failing_channel_does_not_block_others():
    r = _Rec()
    out = channels.deliver({"title": "x"}, [_Boom(), r])
    assert out == ["rec"]  # boom swallowed, rec still delivered


def test_enabled_channels_are_env_driven(monkeypatch):
    monkeypatch.setenv("OPAYAI_NOTIFY", "0")            # desktop off
    monkeypatch.delenv("OPAYAI_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("OPAYAI_NOTIFY_EMAIL", raising=False)
    assert channels.enabled_channels() == []

    monkeypatch.setenv("OPAYAI_WEBHOOK_URL", "http://localhost:9/hook")
    assert [c.name for c in channels.enabled_channels()] == ["webhook"]

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("OPAYAI_NOTIFY_EMAIL", "me@example.com")
    names = [c.name for c in channels.enabled_channels()]
    assert "webhook" in names and "email" in names


def test_desktop_enabled_by_default(monkeypatch):
    monkeypatch.delenv("OPAYAI_NOTIFY", raising=False)
    monkeypatch.delenv("OPAYAI_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert [c.name for c in channels.enabled_channels()] == ["desktop"]
