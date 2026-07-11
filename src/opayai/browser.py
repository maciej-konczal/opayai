"""Minimal browser host for the OpenAI agent and local opayai MCP server."""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from agents.mcp import MCPServerStdio
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from opayai.agent import AgentConversation, build_agent, model_name, server_params


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
    a { color: #175cd3; }
  </style>
</head>
<body>
  <h1>opayai</h1>
  <p class="muted">Local OpenAI agent driving the existing MCP purchase workflow.</p>
  <p><a id="authorize" href="http://127.0.0.1:8000/authorize" target="_blank"
    rel="noopener">Trusted authorization surface</a></p>
  <div id="status">Connecting…</div>
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
    const authorize = document.querySelector('#authorize');

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

    fetch('/api/health').then(r => r.json()).then(data => {
      authorize.href = data.authorize_url;
      status.textContent = data.api_key
        ? `Ready · ${data.model} · 12 local MCP tools`
        : 'OPENAI_API_KEY is not set. Restart the app after exporting it.';
    }).catch(() => status.textContent = 'Local agent is unavailable.');

    form.addEventListener('submit', async event => {
      event.preventDefault();
      const message = input.value.trim();
      if (!message) return;
      addMessage(message, 'user');
      input.value = '';
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
      } catch (error) {
        addMessage(`Connection error: ${error}`, 'agent');
        status.textContent = 'Connection failed';
      } finally {
        button.disabled = false;
        input.focus();
      }
    });
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
        "authorize_url": trusted_surface_url() + "/authorize",
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


def trusted_surface_url() -> str:
    return os.environ.get("OPAYAI_WEB_BASE", "http://127.0.0.1:8000").rstrip("/")


@asynccontextmanager
async def run_trusted_surface():
    """Run the teammate-owned authorization/status site beside the agent host."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "opayai.web",
        env=server_params()["env"],
        start_new_session=True,
    )
    await asyncio.sleep(0.2)
    if process.returncode is not None:
        raise RuntimeError(
            "The trusted authorization surface could not start. "
            f"Port {os.environ.get('OPAYAI_WEB_PORT', '8000')} may already be in use."
        )
    try:
        yield
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()


def create_app(conversation=None, start_trusted_surface: bool = True) -> Starlette:
    if conversation is not None:
        app = Starlette(routes=[
            Route("/", homepage),
            Route("/api/health", health),
            Route("/api/chat", chat, methods=["POST"]),
        ])
        app.state.conversation = conversation
        return app

    @asynccontextmanager
    async def lifespan(app: Starlette):
        surface_context = run_trusted_surface() if start_trusted_surface else _noop()
        async with surface_context:
            async with MCPServerStdio(
                name="opayai local server",
                params=server_params(),
                cache_tools_list=True,
            ) as server:
                app.state.conversation = AgentConversation(build_agent(server))
                yield

    return Starlette(
        routes=[
            Route("/", homepage),
            Route("/api/health", health),
            Route("/api/chat", chat, methods=["POST"]),
        ],
        lifespan=lifespan,
    )


@asynccontextmanager
async def _noop():
    yield


app = create_app()


def main() -> None:
    port = int(os.environ.get("OPAYAI_AGENT_PORT", "8080"))
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
