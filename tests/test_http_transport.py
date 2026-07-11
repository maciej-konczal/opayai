from __future__ import annotations

import asyncio

from opayai.server import _bearer_auth_asgi


class _InnerSpy:
    """Minimal ASGI app that records it was reached and returns 200."""

    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope, receive, send) -> None:
        self.called = True
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})


def _drive(app, scope) -> list[dict]:
    """Run an ASGI app once against a fixed scope, capturing sent messages."""

    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


def _http_scope(auth: str | None) -> dict:
    headers = []
    if auth is not None:
        headers.append((b"authorization", auth.encode()))
    return {"type": "http", "headers": headers}


def test_no_token_passes_through() -> None:
    inner = _InnerSpy()
    wrapped = _bearer_auth_asgi(inner, None)
    # No token configured -> identity: same object, inner reached regardless of header.
    assert wrapped is inner
    sent = _drive(wrapped, _http_scope(None))
    assert inner.called is True
    assert sent[0]["status"] == 200


def test_correct_token_reaches_inner() -> None:
    inner = _InnerSpy()
    wrapped = _bearer_auth_asgi(inner, "s3cret")
    sent = _drive(wrapped, _http_scope("Bearer s3cret"))
    assert inner.called is True
    assert sent[0]["status"] == 200


def test_missing_token_is_rejected() -> None:
    inner = _InnerSpy()
    wrapped = _bearer_auth_asgi(inner, "s3cret")
    sent = _drive(wrapped, _http_scope(None))
    assert inner.called is False
    assert sent[0]["status"] == 401


def test_wrong_token_is_rejected() -> None:
    inner = _InnerSpy()
    wrapped = _bearer_auth_asgi(inner, "s3cret")
    sent = _drive(wrapped, _http_scope("Bearer nope"))
    assert inner.called is False
    assert sent[0]["status"] == 401


def test_lifespan_scope_bypasses_auth() -> None:
    inner = _InnerSpy()
    wrapped = _bearer_auth_asgi(inner, "s3cret")

    async def run() -> None:
        await wrapped({"type": "lifespan"}, None, None)  # type: ignore[arg-type]

    # Non-http scope must delegate to inner even with a token set.
    asyncio.run(run())
    assert inner.called is True
