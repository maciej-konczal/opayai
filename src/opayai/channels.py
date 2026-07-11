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
import html
import json
import os
import platform
import subprocess
import sys
import urllib.request
from typing import Protocol
from opayai import notify


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
        # escape every interpolated field - notifications may carry dynamic data
        # (product titles, LLM rationale) that must not become active HTML.
        title = html.escape(str(n.get("title", "")))
        body = html.escape(str(n.get("body", "")))
        link = html.escape(str(self.link), quote=True)
        msg = (f'<p><b>{title}</b></p><p>{body}</p>'
               f'<p><a href="{link}">Open opayai to act</a></p>')
        # idempotency: same event never emails twice on a retry (Resend, 24h window)
        key = f'opayai-{n.get("source_event", "evt")}/{n.get("mandate_ref", "-")}-{n.get("seq", "")}'[:256]
        _post_json(
            "https://api.resend.com/emails",
            {"from": self.sender, "to": [self.to],
             "subject": f'opayai: {n.get("title", "")}', "html": msg},
            headers={"Authorization": f"Bearer {self.api_key}", "Idempotency-Key": key})


def ping_channels() -> list[NotificationChannel]:
    """Channels that fire only on action-needed notifications (desktop, email)."""
    chans: list[NotificationChannel] = []
    if os.environ.get("OPAYAI_NOTIFY", "1") != "0":
        chans.append(DesktopChannel())
    api_key = os.environ.get("RESEND_API_KEY")
    to = os.environ.get("OPAYAI_NOTIFY_EMAIL")
    if api_key and to:
        sender = os.environ.get("OPAYAI_EMAIL_FROM", "opayai <onboarding@resend.dev>")
        link = os.environ.get("OPAYAI_WEB_BASE", "http://localhost:8000")
        chans.append(EmailChannel(api_key, to, sender, link))
    return chans


def event_webhook() -> WebhookChannel | None:
    """The webhook receives EVERY event (the full stream, like the JSONL)."""
    url = os.environ.get("OPAYAI_WEBHOOK_URL")
    return WebhookChannel(url) if url else None


def deliver(n: dict, channels: list[NotificationChannel]) -> list[str]:
    """Deliver to each channel; return names that succeeded. Best-effort.

    A failing channel never blocks the others.
    """
    delivered = []
    for c in channels:
        try:
            c.deliver(n)
            delivered.append(c.name)
        except Exception:
            pass
    return delivered


def install(bus) -> None:
    """Subscribe delivery to the event bus.

    - Webhook: POST EVERY event (seq, ts, type, actor, mandate_ref, payload) so an
      external service (e.g. Boski) stays fully in sync; an action-needed event also
      carries a `notification` object it can push to the user.
    - Desktop/email: fire only on action-needed notifications (the user pings).
    """
    pings = ping_channels()
    webhook = event_webhook()

    def _sink(event) -> None:
        ev = event.model_dump(mode="json")
        n = notify.notification_for(ev)
        if webhook is not None:
            payload = dict(ev)
            if n is not None:
                payload["notification"] = n
            try:
                webhook.deliver(payload)
            except Exception:
                pass
        if n is not None and n["needs_action"]:
            print(f"[opayai] ACTION NEEDED: {n['title']} - {n['body']}", file=sys.stderr, flush=True)
            deliver(n, pings)

    bus.subscribe(_sink)
