import anyio
import httpx

from opayai.browser import create_app


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
