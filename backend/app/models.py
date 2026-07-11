from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

Currency = Literal["PLN"]
OrderStatus = Literal[
    "created", "payment_pending", "payment_failed", "paid", "confirmed",
    "shipped", "in_paczkomat", "picked_up", "exception", "return_requested",
    "return_in_transit", "refund_issued", "cancelled", "closed_accepted",
    "closed_refunded",
]


class Constraints(BaseModel):
    max_total: int = Field(ge=1, description="PLN grosze")
    currency: Currency = "PLN"
    categories: list[str] = Field(min_length=1)
    requires_refundability: bool = True
    min_return_window_days: int = Field(default=14, ge=0)
    deliver_by: str | None = None
    allowed_rails: list[str] = Field(default_factory=lambda: ["blik_lite"])
    expiry: str


class WebAuthnSigning(BaseModel):
    method: Literal["webauthn", "demo_key"] = "demo_key"
    credential_id: str
    assertion_b64: str
    challenge_derivation: str = "sha256(canonical_json(body))"
    verified: bool
    signed_at: str


class IntentMandate(BaseModel):
    id: str
    user_id: Literal["user_demo"] = "user_demo"
    agent_id: str
    description: str
    constraints: Constraints
    status: Literal["draft", "open", "fulfilled", "revoked", "expired"] = "draft"
    signing: WebAuthnSigning | None = None
    spent_total: int = 0


class LineItem(BaseModel):
    sku: str
    title: str
    qty: int = Field(ge=1)
    unit_price: int = Field(ge=0)


class CartMandate(BaseModel):
    id: str
    parent_intent_id: str
    line_items: list[LineItem]
    totals: dict[str, int]
    delivery_method: Literal["paczkomat", "courier"]
    delivery_promise: str
    return_policy_snapshot: dict[str, Any]
    signing: WebAuthnSigning | None = None


class PaymentMandate(BaseModel):
    id: str
    cart_mandate_id: str
    rail: Literal["blik_lite", "card_spt_stub", "usdc_stub"]
    rail_ref: str
    amount: int
    currency: Currency = "PLN"
    human_present: bool = True
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["pending", "succeeded", "failed", "refunded"] = "pending"


class PurchaseException(BaseModel):
    id: str
    order_id: str
    type: Literal["ITEM_MISMATCH", "PRICE_DRIFT", "LATE_DELIVERY", "USER_REPORTED"]
    evidence: dict[str, Any]
    proposed_resolution: Literal["full_return", "refund_difference", "accept"]
    resolution_status: Literal["proposed", "approved", "executing", "resolved", "declined"] = "proposed"


class OrderEvent(BaseModel):
    seq: int
    ts: str
    actor: Literal["merchant", "agent", "user", "policy", "rail", "system"]
    type: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str


class Offer(BaseModel):
    sku: str
    title: str
    category: str
    price: int
    stock: int
    delivery_method: Literal["paczkomat", "courier"]
    delivery_estimate_days: int
    return_policy: dict[str, Any]
    refundable: bool
    attributes: dict[str, Any] = Field(default_factory=dict)


class Purchase(BaseModel):
    id: str
    intent_id: str
    agent_attribution: dict[str, str]
    status: str = "proposal_ready"
    order_status: OrderStatus = "created"
    proposal: dict[str, Any]
    cart: CartMandate | None = None
    payment: PaymentMandate | None = None
    order: dict[str, Any] | None = None
    exception: PurchaseException | None = None
    resolution: dict[str, Any] | None = None


class EvidenceBundle(BaseModel):
    bundle_id: str
    generated_at: str
    intent_mandate: IntentMandate
    cart_mandate: CartMandate | None
    payment_mandate: PaymentMandate | None
    order_event_log: list[OrderEvent]
    hash_chain_valid: bool
    exception: PurchaseException | None
    diff: dict[str, Any] | None
    resolution_actions: list[OrderEvent]
    agent_attribution: dict[str, str]
