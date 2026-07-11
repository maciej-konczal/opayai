from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field


class MerchantLineItem(BaseModel):
    sku: str
    qty: int = Field(default=1, ge=1)


class ProposalBody(BaseModel):
    intent_id: str
    line_items: list[MerchantLineItem] = Field(min_length=1, max_length=1)
    agent_id: str = "merchant_router"


class ConfirmBody(BaseModel):
    purchase_id: str


class ReturnBody(BaseModel):
    purchase_id: str
    reason: str


class RefundBody(BaseModel):
    purchase_id: str

router = APIRouter(prefix="/merchant", tags=["mock merchant"])


@router.get("/catalog")
def catalog(request: Request, q: str = "", category: str | None = None, max_price: int | None = None):
    """Mock merchant catalog. Agent paths use service.request_purchase, which checks policy."""
    return request.app.state.service.search_products(q, category, max_price, None)["offers"]


@router.post("/checkout/proposal")
def checkout_proposal(body: ProposalBody, request: Request):
    """Internal merchant proposal; policy is mandatory before proposal creation."""
    item = body.line_items[0]
    purchase = request.app.state.service.request_purchase(
        body.intent_id, item.sku, item.qty, body.agent_id, "merchant-router")
    return {"proposal_id": purchase.id, **purchase.proposal}


@router.post("/checkout/confirm")
def checkout_confirm(body: ConfirmBody, request: Request):
    return request.app.state.service.merchant_confirm_checkout(body.purchase_id)


@router.get("/orders/{order_id}")
def order(order_id: str, request: Request):
    purchase = next(p for p in request.app.state.service.store.purchases.values() if p.order and p.order["id"] == order_id)
    return purchase.order


@router.post("/orders/{order_id}/returns")
def create_return(order_id: str, body: ReturnBody, request: Request):
    purchase = next(p for p in request.app.state.service.store.purchases.values()
                    if p.order and p.order["id"] == order_id)
    if purchase.id != body.purchase_id:
        raise ValueError("Purchase does not own this order.")
    return request.app.state.service.merchant_create_return(purchase.id, body.reason)


@router.post("/orders/{order_id}/refund")
def refund(order_id: str, body: RefundBody, request: Request):
    purchase = next(p for p in request.app.state.service.store.purchases.values()
                    if p.order and p.order["id"] == order_id)
    if purchase.id != body.purchase_id:
        raise ValueError("Purchase does not own this order.")
    return request.app.state.service.merchant_refund(purchase.id)
