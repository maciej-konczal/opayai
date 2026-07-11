from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/merchant", tags=["mock merchant"])


@router.get("/catalog")
def catalog(request: Request, q: str = "", category: str | None = None, max_price: int | None = None):
    """Mock merchant catalog. Agent paths use service.request_purchase, which checks policy."""
    return request.app.state.service.search_products(q, category, max_price, None)["offers"]


@router.get("/orders/{order_id}")
def order(order_id: str, request: Request):
    purchase = next(p for p in request.app.state.service.store.purchases.values() if p.order and p.order["id"] == order_id)
    return purchase.order
