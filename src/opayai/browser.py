"""Minimal browser host for the OpenAI agent and local opayai MCP server."""
from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager

import uvicorn
from agents.mcp import MCPServerStdio
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from opayai import authstore
from opayai.agent import AgentConversation, build_agent, model_name, server_params
from opayai.web import (
    authorize as issue_authorization,
    load_events,
    render_index,
    render_order,
    render_profile,
)


_CSRF_TOKEN = secrets.token_urlsafe(32)


PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>opayai local agent</title>
  <style>
    body { font: 16px/1.5 system-ui, sans-serif; max-width: 760px; margin: 40px auto;
           padding: 0 18px; color: #17202a; background: #f7f8fa; }
    h1 { font-size: 24px; margin-bottom: 4px; }
    .muted { color: #667085; margin-top: 0; }
    #chat { min-height: 260px; margin: 24px 0; }
    .message { white-space: pre-wrap; padding: 12px 14px; border-radius: 10px;
               margin: 10px 0; overflow-wrap: anywhere; }
    .user { background: #e9eefb; margin-left: 12%; }
    .agent { background: white; border: 1px solid #e4e7ec; margin-right: 12%; }
    form { display: flex; gap: 8px; position: sticky; bottom: 16px; }
    input { flex: 1; padding: 12px; border: 1px solid #98a2b3; border-radius: 8px;
            font: inherit; background: white; }
    button { padding: 10px 16px; border: 0; border-radius: 8px; background: #101828;
             color: white; font: inherit; cursor: pointer; }
    button:disabled { opacity: .55; cursor: wait; }
    #status { font-size: 13px; color: #667085; }
    #authorizations { background: #fff7e8; border: 1px solid #fdb022;
                      border-radius: 10px; padding: 14px; margin: 18px 0; }
    #authorizations h2 { font-size: 17px; margin: 0 0 8px; }
    .authorization { display: flex; align-items: center; justify-content: space-between;
                     gap: 12px; }
    nav { display: flex; gap: 14px; margin-bottom: 12px; }
    a { color: #175cd3; }
  </style>
</head>
<body>
  <h1>opayai</h1>
  <p class="muted">Local OpenAI agent driving the existing MCP purchase workflow.</p>
  <nav><a href="/orders">Orders and audit trail</a><a href="/profile">Profile</a></nav>
  <div id="status">Connecting…</div>
  <section id="authorizations" hidden>
    <h2>Authorization required</h2>
    <div id="pending"></div>
  </section>
  <main id="chat"></main>
  <form id="form">
    <input id="message" autocomplete="off" autofocus
      placeholder="Buy a monitor under $300 with free returns…">
    <button id="send" type="submit">Send</button>
  </form>
  <script>
    const chat = document.querySelector('#chat');
    const form = document.querySelector('#form');
    const input = document.querySelector('#message');
    const button = document.querySelector('#send');
    const status = document.querySelector('#status');
    const authorizationPanel = document.querySelector('#authorizations');
    const pending = document.querySelector('#pending');
    let csrfToken = '';

    function addMessage(text, kind) {
      const box = document.createElement('div');
      box.className = `message ${kind}`;
      const urlPattern = /(https?:\\/\\/[^\\s]+)/g;
      let start = 0;
      for (const match of text.matchAll(urlPattern)) {
        box.append(document.createTextNode(text.slice(start, match.index)));
        const link = document.createElement('a');
        link.href = match[0];
        link.target = '_blank';
        link.rel = 'noopener';
        link.textContent = match[0];
        box.append(link);
        start = match.index + match[0].length;
      }
      box.append(document.createTextNode(text.slice(start)));
      chat.append(box);
      box.scrollIntoView({behavior: 'smooth', block: 'end'});
    }

    async function refreshAuthorizations() {
      const response = await fetch('/api/authorizations');
      const data = await response.json();
      pending.replaceChildren();
      authorizationPanel.hidden = data.pending.length === 0;
      for (const request of data.pending) {
        const row = document.createElement('div');
        row.className = 'authorization';
        const description = document.createElement('span');
        const label = request.kind === 'step_up' ? 'Passkey step-up' : 'Approval';
        description.textContent = `${label} · $${request.amount} · cart ${request.cart_id}`;
        const approve = document.createElement('button');
        approve.textContent = request.kind === 'step_up' ? 'Authorize' : 'Approve';
        approve.addEventListener('click', async () => {
          approve.disabled = true;
          status.textContent = 'Authorizing…';
          const result = await fetch(
            `/api/authorizations/${encodeURIComponent(request.cart_id)}/${encodeURIComponent(request.kind)}`,
            {method: 'POST', headers: {'X-CSRF-Token': csrfToken}}
          );
          const body = await result.json();
          if (!result.ok) {
            addMessage(body.error || 'Authorization failed', 'agent');
            status.textContent = 'Authorization failed';
            approve.disabled = false;
            return;
          }
          addMessage(`${label} completed for ${request.cart_id}.`, 'user');
          await refreshAuthorizations();
          await sendToAgent('I completed the requested authorization. Retry execute_payment now.', false);
        });
        row.append(description, approve);
        pending.append(row);
      }
    }

    fetch('/api/health').then(r => r.json()).then(data => {
      csrfToken = data.csrf_token;
      status.textContent = data.api_key
        ? `Ready · ${data.model} · 12 local MCP tools`
        : 'OPENAI_API_KEY is not set. Restart the app after exporting it.';
      refreshAuthorizations();
    }).catch(() => status.textContent = 'Local agent is unavailable.');

    async function sendToAgent(message, showUser = true) {
      if (showUser) addMessage(message, 'user');
      button.disabled = true;
      status.textContent = 'Agent is working…';
      try {
        const response = await fetch('/api/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({message})
        });
        const data = await response.json();
        addMessage(data.reply || data.error || 'No response', 'agent');
        status.textContent = response.ok ? 'Ready' : 'Request failed';
        await refreshAuthorizations();
      } catch (error) {
        addMessage(`Connection error: ${error}`, 'agent');
        status.textContent = 'Connection failed';
      } finally {
        button.disabled = false;
        input.focus();
      }
    }

    form.addEventListener('submit', async event => {
      event.preventDefault();
      const message = input.value.trim();
      if (!message) return;
      input.value = '';
      await sendToAgent(message);
    });

    setInterval(refreshAuthorizations, 2000);
  </script>
</body>
</html>
"""


async def homepage(_: Request) -> HTMLResponse:
    return HTMLResponse(PAGE)


async def health(_: Request) -> JSONResponse:
    return JSONResponse({
        "ok": True,
        "api_key": bool(os.environ.get("OPENAI_API_KEY")),
        "model": model_name(),
        "csrf_token": _CSRF_TOKEN,
    })


async def chat(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Expected a JSON request."}, status_code=400)

    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, str) or not message.strip():
        return JSONResponse({"error": "Message cannot be empty."}, status_code=400)

    try:
        reply = await request.app.state.conversation.send(message.strip())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    return JSONResponse({"reply": reply})


async def pending_authorizations(_: Request) -> JSONResponse:
    return JSONResponse({"pending": authstore.list_pending()})


async def authorize_pending(request: Request) -> JSONResponse:
    if request.headers.get("X-CSRF-Token") != _CSRF_TOKEN:
        return JSONResponse({"error": "Invalid authorization token."}, status_code=403)
    cart_id = request.path_params["cart_id"]
    kind = request.path_params["kind"]
    if kind not in {"approval", "step_up"}:
        return JSONResponse({"error": "Invalid authorization kind."}, status_code=400)
    if not issue_authorization(cart_id, kind):
        return JSONResponse({"error": "Authorization request not found."}, status_code=404)
    return JSONResponse({"authorized": True, "cart_id": cart_id, "kind": kind})


async def orders_page(_: Request) -> HTMLResponse:
    return HTMLResponse(render_index(load_events()))


async def order_page(request: Request) -> HTMLResponse:
    return HTMLResponse(render_order(load_events(), request.path_params["order_id"]))


async def profile_page(_: Request) -> HTMLResponse:
    return HTMLResponse(render_profile(load_events()))


async def authorize_redirect(_: Request) -> RedirectResponse:
    return RedirectResponse("/#authorizations", status_code=303)


def browser_base_url() -> str:
    configured = os.environ.get("OPAYAI_AGENT_BASE")
    if configured:
        return configured.rstrip("/")
    return f"http://127.0.0.1:{os.environ.get('OPAYAI_AGENT_PORT', '8080')}"


def browser_server_params() -> dict:
    params = server_params()
    params["env"]["OPAYAI_WEB_BASE"] = browser_base_url()
    return params


def routes() -> list[Route]:
    return [
        Route("/", homepage),
        Route("/orders", orders_page),
        Route("/order/{order_id}", order_page),
        Route("/profile", profile_page),
        Route("/authorize", authorize_redirect),
        Route("/api/health", health),
        Route("/api/chat", chat, methods=["POST"]),
        Route("/api/authorizations", pending_authorizations),
        Route(
            "/api/authorizations/{cart_id}/{kind}",
            authorize_pending,
            methods=["POST"],
        ),
    ]


def create_app(conversation=None) -> Starlette:
    if conversation is not None:
        app = Starlette(routes=routes())
        app.state.conversation = conversation
        return app

    @asynccontextmanager
    async def lifespan(app: Starlette):
        async with MCPServerStdio(
            name="opayai local server",
            params=browser_server_params(),
            cache_tools_list=True,
        ) as server:
            app.state.conversation = AgentConversation(build_agent(server))
            yield

    return Starlette(
        routes=routes(),
        lifespan=lifespan,
    )


app = create_app()


def main() -> None:
    port = int(os.environ.get("OPAYAI_AGENT_PORT", "8080"))
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
