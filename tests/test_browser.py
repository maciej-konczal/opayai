import anyio
import httpx

from opayai import authstore
from opayai.browser import browser_server_params, create_app


class FakeConversation:
    async def send(self, message: str) -> str:
        return f"handled: {message}"


def test_homepage_has_browser_prompt():
    async def request():
        transport = httpx.ASGITransport(app=create_app(FakeConversation()))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/")

    response = anyio.run(request)
    assert response.status_code == 200
    assert "Local OpenAI agent" in response.text
    assert 'id="message"' in response.text


def test_chat_uses_persistent_conversation():
    async def request():
        transport = httpx.ASGITransport(app=create_app(FakeConversation()))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/chat", json={"message": "buy a monitor"})

    response = anyio.run(request)
    assert response.status_code == 200
    assert response.json() == {"reply": "handled: buy a monitor"}


def test_chat_rejects_empty_message():
    async def request():
        transport = httpx.ASGITransport(app=create_app(FakeConversation()))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/chat", json={"message": "  "})

    response = anyio.run(request)
    assert response.status_code == 400


def test_browser_mcp_status_urls_use_the_single_browser_origin(monkeypatch):
    monkeypatch.setenv("OPAYAI_AGENT_PORT", "9000")
    params = browser_server_params()
    assert params["env"]["OPAYAI_WEB_BASE"] == "http://127.0.0.1:9000"
    assert params["env"]["OPAYAI_REQUIRE_APPROVAL"] == "1"


def test_human_can_authorize_pending_cart_from_browser():
    authstore.write_pending("cm_1", "step_up", "289.00", "USD", "im_1")

    async def request():
        transport = httpx.ASGITransport(app=create_app(FakeConversation()))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            pending = await client.get("/api/authorizations")
            health = await client.get("/api/health")
            authorized = await client.post(
                "/api/authorizations/cm_1/step_up",
                headers={"X-CSRF-Token": health.json()["csrf_token"]},
            )
            return pending, authorized

    pending, authorized = anyio.run(request)
    assert pending.json()["pending"][0]["cart_id"] == "cm_1"
    assert authorized.json()["authorized"] is True
    assert authstore.has_proof("cm_1", "step_up")


def test_authorization_rejects_missing_csrf_token():
    authstore.write_pending("cm_1", "approval", "289.00", "USD", "im_1")

    async def request():
        transport = httpx.ASGITransport(app=create_app(FakeConversation()))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/authorizations/cm_1/approval")

    response = anyio.run(request)
    assert response.status_code == 403
