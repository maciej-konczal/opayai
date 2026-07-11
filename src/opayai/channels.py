"""Pluggable notification delivery channels.

The same needs-action notification fans out to whatever channels are enabled
(env-driven), the same way payment rails are pluggable. This is how the proactive
"pings you only when it needs input, approval, or a decision" reaches the user
off-screen: a desktop banner, an email, and/or a webhook (the seam a host like
Boski uses to push to the user's phone). Zero third-party deps - stdlib urllib.

Enable via env:
  OPAYAI_NOTIFY=0            disable the desktop ping (default on, macOS only)
  OPAYAI_WEBHOOK_URL=...     POST each action-needed notification here
  RESEND_API_KEY + OPAYAI_NOTIFY_EMAIL   send an email (see README for sandbox rule)
  OPAYAI_EMAIL_FROM=...      sender (default "opayai <onboarding@resend.dev>")
  OPAYAI_WEB_BASE=...        link included in the email (default http://localhost:8000)
"""
from __future__ import annotations
import json
import os
import platform
import subprocess
import urllib.request
from typing import Protocol


def _post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 6) -> int:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


class NotificationChannel(Protocol):
    name: str
    def deliver(self, n: dict) -> None: ...


class DesktopChannel:
    name = "desktop"

    def deliver(self, n: dict) -> None:
        if platform.system() != "Darwin":
            return
        title = ("opayai: " + n["title"]).replace('"', "'")
        body = n["body"].replace('"', "'")
        subprocess.run(["osascript", "-e",
                        f'display notification "{body}" with title "{title}"'],
                       check=False, capture_output=True)


class WebhookChannel:
    name = "webhook"

    def __init__(self, url: str):
        self.url = url

    def deliver(self, n: dict) -> None:
        _post_json(self.url, n)


class EmailChannel:
    name = "email"

    def __init__(self, api_key: str, to: str, sender: str, link: str):
        self.api_key = api_key
        self.to = to
        self.sender = sender
        self.link = link

    def deliver(self, n: dict) -> None:
        html = (f'<p><b>{n["title"]}</b></p><p>{n["body"]}</p>'
                f'<p><a href="{self.link}">Open opayai to act</a></p>')
        # idempotency: same event never emails twice on a retry (Resend, 24h window)
        key = f'opayai-{n.get("source_event", "evt")}/{n.get("mandate_ref", "-")}-{n.get("seq", "")}'[:256]
        _post_json(
            "https://api.resend.com/emails",
            {"from": self.sender, "to": [self.to],
             "subject": f'opayai: {n["title"]}', "html": html},
            headers={"Authorization": f"Bearer {self.api_key}", "Idempotency-Key": key})


def enabled_channels() -> list[NotificationChannel]:
    chans: list[NotificationChannel] = []
    if os.environ.get("OPAYAI_NOTIFY", "1") != "0":
        chans.append(DesktopChannel())
    url = os.environ.get("OPAYAI_WEBHOOK_URL")
    if url:
        chans.append(WebhookChannel(url))
    api_key = os.environ.get("RESEND_API_KEY")
    to = os.environ.get("OPAYAI_NOTIFY_EMAIL")
    if api_key and to:
        sender = os.environ.get("OPAYAI_EMAIL_FROM", "opayai <onboarding@resend.dev>")
        link = os.environ.get("OPAYAI_WEB_BASE", "http://localhost:8000")
        chans.append(EmailChannel(api_key, to, sender, link))
    return chans


def deliver(n: dict, channels: list[NotificationChannel] | None = None) -> list[str]:
    """Deliver a notification to all channels; return names that succeeded.

    A failing channel never blocks the others (delivery is best-effort).
    """
    channels = channels if channels is not None else enabled_channels()
    delivered = []
    for c in channels:
        try:
            c.deliver(n)
            delivered.append(c.name)
        except Exception:
            pass
    return delivered
