from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from .api import router as api_router
from .mcp_server import create_mcp
from .merchant import router as merchant_router
from .rails import lan_ip
from .service import MandateLoopService
from .policy import PolicyBlock


def create_app() -> FastAPI:
    app = FastAPI(title="MandateLoop", version="0.3.0")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    state_dir = Path(os.getenv("MANDATELOOP_STATE", ".mandateloop"))
    service = MandateLoopService(state_dir)
    app.state.service = service

    @app.exception_handler(PolicyBlock)
    async def policy_block(_: Request, error: PolicyBlock):
        return JSONResponse(status_code=409, content={"status": "blocked", "violated_clause": error.clause, "detail": error.detail})

    app.include_router(api_router)
    app.include_router(merchant_router)
    mcp = create_mcp(service)
    app.mount("/mcp", mcp.streamable_http_app())

    @app.get("/pay/blik/{session_id}", response_class=HTMLResponse)
    def blik_page(session_id: str):
        session = service.rails["blik_lite"].sessions.get(session_id)
        if not session:
            raise HTTPException(404, "Unknown BLIK session")
        amount = f"{session.amount // 100:,}".replace(",", " ") + f",{session.amount % 100:02d} zł"
        return f'''<!doctype html><html lang="pl"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MandateLoop BLIK</title>
        <style>body{{margin:0;background:#0d1110;color:#f5f5ed;font:16px ui-rounded,system-ui;display:grid;min-height:100vh;place-items:center}}main{{width:min(92vw,370px);background:#f5f5ed;color:#13231d;padding:28px;border-radius:26px;box-shadow:0 20px 70px #0008}}small{{color:#64736d;text-transform:uppercase;letter-spacing:.13em}}h1{{font-size:23px;margin:24px 0 8px}}strong{{font-size:32px}}button{{width:100%;border:0;border-radius:12px;padding:16px;margin-top:12px;font-weight:800;font-size:16px;background:#0aaa64;color:white}}button:last-child{{background:#e8ece7;color:#183027}}</style>
        <main><small>MandateLoop · sklep demo</small><h1>Potwierdzasz płatność BLIK?</h1><strong>{amount}</strong><p>Mandat podpisany na laptopie. Ten ekran tylko potwierdza płatność.</p><form method="post"><button name="decision" value="confirm">Potwierdź</button><button name="decision" value="reject">Odrzuć</button></form></main></html>'''

    @app.post("/pay/blik/{session_id}", response_class=HTMLResponse)
    def blik_confirm(session_id: str, decision: str = Form(...)):
        purchase = service.blik_decision(session_id, decision)
        return HTMLResponse(f"<meta name='viewport' content='width=device-width'><body style='font-family:system-ui;padding:32px'><h2>{'Płatność potwierdzona' if purchase.order_status == 'paid' else 'Płatność odrzucona'}</h2><p>Możesz zamknąć tę stronę i wrócić do MandateLoop.</p></body>")

    return app


app = create_app()


@app.on_event("startup")
async def show_lan_ip() -> None:
    print(f"MandateLoop BLIK phone page is reachable at http://{lan_ip()}:8000/pay/blik/<session_id>")
