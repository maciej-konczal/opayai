from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .models import Constraints
from .policy import PolicyBlock
from .service import MandateLoopService


def _service(request: Request) -> MandateLoopService:
    return request.app.state.service


class DraftBody(BaseModel):
    text: str


class IntentBody(BaseModel):
    description: str
    constraints: Constraints


class PurchaseBody(BaseModel):
    intent_id: str
    sku: str
    qty: int = 1
    agent_id: str = "webapp"
    client_info: str = "webapp"


class SigningRequest(BaseModel):
    context_id: str
    context_type: Literal["intent", "cart", "resolution"]


class VerifyRequest(SigningRequest):
    assertion: dict[str, Any] = {}


class RailBody(BaseModel):
    rail: Literal["blik_lite", "card_spt_stub", "usdc_stub"]


class ReasonBody(BaseModel):
    reason: str


class FaultBody(BaseModel):
    type: Literal["wrong_item", "decline_payment"]


router = APIRouter(prefix="/api", tags=["webapp"])


@router.post("/intents/draft")
def draft_intent(body: DraftBody, request: Request):
    return _service(request).draft_intent(body.text).model_dump(mode="json")


@router.post("/intents")
def create_intent(body: IntentBody, request: Request):
    return _service(request).create_intent(body.description, body.constraints).model_dump(mode="json")


@router.post("/intents/{intent_id}/revoke")
def revoke_intent(intent_id: str, request: Request):
    return _service(request).revoke_intent(intent_id).model_dump(mode="json")


@router.post("/webauthn/register/options")
def registration_options():
    return {"auth_mode": "demo_key", "credential_id": "demo-device", "message": "Demo key enabled; platform registration is optional."}


@router.post("/webauthn/register/verify")
def registration_verify():
    return {"verified": True, "credential_id": "demo-device"}


@router.post("/webauthn/auth/options")
def auth_options(body: SigningRequest, request: Request):
    return _service(request).signing_options(body.context_id, body.context_type)


@router.post("/webauthn/auth/verify")
def auth_verify(body: VerifyRequest, request: Request):
    return _service(request).verify_signing(body.context_id, body.context_type, body.assertion).model_dump(mode="json")


@router.get("/products")
def products(request: Request, query: str = "", category: str | None = None,
             max_price: int | None = None, intent_id: str | None = None):
    return _service(request).search_products(query, category, max_price, intent_id)


@router.post("/purchases")
def request_purchase(body: PurchaseBody, request: Request):
    purchase = _service(request).request_purchase(**body.model_dump())
    return {"purchase_id": purchase.id, "status": "awaiting_human_authorization", "proposal": purchase.proposal}


@router.get("/purchases")
def list_purchases(request: Request):
    return [purchase.model_dump(mode="json") for purchase in _service(request).store.purchases.values()]


@router.get("/purchases/{purchase_id}")
def get_purchase(purchase_id: str, request: Request):
    service = _service(request)
    purchase = service.store.purchases[purchase_id]
    data = purchase.model_dump(mode="json")
    data["events"] = [event.model_dump(mode="json") for event in service.ledger.for_purchase(purchase_id)]
    return data


@router.post("/purchases/{purchase_id}/select-rail")
def select_rail(purchase_id: str, body: RailBody, request: Request):
    return _service(request).select_rail(purchase_id, body.rail, str(request.base_url).rstrip("/"))


@router.post("/purchases/{purchase_id}/retry-payment")
def retry_payment(purchase_id: str, request: Request):
    return _service(request).retry_payment(purchase_id, str(request.base_url).rstrip("/"))


@router.post("/purchases/{purchase_id}/initiate-return")
def initiate_return(purchase_id: str, body: ReasonBody, request: Request):
    purchase = _service(request).request_return(purchase_id, body.reason)
    return {"status": "awaiting_human_authorization", "purchase_id": purchase.id}


@router.post("/purchases/{purchase_id}/approve-resolution")
def approve_resolution(purchase_id: str, request: Request):
    return _service(request).approve_resolution(purchase_id)


@router.post("/purchases/{purchase_id}/decline-resolution")
def decline_resolution(purchase_id: str, request: Request):
    purchase = _service(request).store.purchases[purchase_id]
    if purchase.exception:
        purchase.exception.resolution_status = "declined"
    _service(request)._event("user", "resolution_declined", purchase_id)
    return {"status": "declined"}


@router.post("/purchases/{purchase_id}/confirm-satisfied")
def confirm_satisfied(purchase_id: str, request: Request):
    return _service(request).confirm_satisfied(purchase_id).model_dump(mode="json")


@router.get("/purchases/{purchase_id}/evidence")
def evidence(purchase_id: str, request: Request):
    return _service(request).evidence(purchase_id).model_dump(mode="json")


@router.get("/events")
async def events(request: Request, since: int = 0):
    service = _service(request)

    async def stream():
        for event in service.ledger.events[since:]:
            yield {"event": "ledger", "id": str(event.seq), "data": event.model_dump_json()}
        queue = service.ledger.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield {"event": "ledger", "id": str(event.seq), "data": event.model_dump_json()}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            service.ledger.unsubscribe(queue)
    return EventSourceResponse(stream())


@router.post("/demo/advance/{order_id}")
def demo_advance(order_id: str, request: Request):
    return _service(request).advance(order_id).model_dump(mode="json")


@router.post("/demo/fault/{order_id}")
def demo_fault(order_id: str, body: FaultBody, request: Request):
    _service(request).inject_fault(order_id, body.type)
    return {"ok": True}


@router.post("/demo/reset")
def demo_reset(request: Request):
    service = _service(request)
    service.store.reset()
    service.ledger.reset()
    service._event("system", "demo_reset", message="Demo state reset")
    return {"ok": True}
