from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class Money(BaseModel):
    amount: Decimal
    currency: str = "USD"

    @field_validator("amount")
    @classmethod
    def non_negative_amount(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value < 0:
            raise ValueError("money amount must be finite and non-negative")
        return value

    @field_validator("currency")
    @classmethod
    def iso_currency(cls, value: str) -> str:
        value = value.upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("currency must be a three-letter ISO-style code")
        return value


class Constraint(BaseModel):
    max_total: Money
    category: str
    hard_requirements: list[str] = Field(default_factory=list)
    soft_preferences: list[str] = Field(default_factory=list)


class SpendingLimit(BaseModel):
    per_transaction: Money
    per_period: Money
    period: str = "day"
    # Carts at or above this need a fresh trusted-surface authorization proof.
    # None disables step-up (everything within limits is human-not-present).
    step_up_threshold: Money | None = None


class IntentMandate(BaseModel):
    id: str
    user_id: str
    created_at: datetime
    expires_at: datetime
    human_present: bool = False
    constraint: Constraint
    spending_limit: SpendingLimit
    signature: str = ""


class CartItem(BaseModel):
    offer_id: str
    title: str
    qty: int
    unit_price: Money

    @field_validator("qty")
    @classmethod
    def positive_quantity(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("quantity must be positive")
        return value


class CartMandate(BaseModel):
    id: str
    intent_mandate_id: str
    items: list[CartItem]
    total: Money
    selected_rail: str
    rationale: str
    created_at: datetime
    signature: str = ""


class PolicyCheck(BaseModel):
    rule: str
    passed: bool
    detail: str


class PolicyDecision(BaseModel):
    cart_mandate_id: str
    result: Literal["AUTO_APPROVE", "ESCALATE", "REJECT"]
    checks: list[PolicyCheck]
    step_up_required: bool = False


class Event(BaseModel):
    seq: int
    ts: datetime
    type: str
    actor: Literal["user", "agent", "policy", "rail", "merchant"]
    mandate_ref: str | None = None
    payload: dict = Field(default_factory=dict)


class Receipt(BaseModel):
    id: str
    cart_mandate_id: str
    rail: str
    amount: Money
    paid_at: datetime
    rail_reference: str


class Offer(BaseModel):
    id: str
    title: str
    merchant: str
    price: Money
    stock_available: bool
    stock_qty: int
    delivery_est_date: str
    delivery_cutoff: str
    returns_window_days: int
    free_returns: bool
    warranty_months: int
    specs: dict = Field(default_factory=dict)
    rating: float


class Order(BaseModel):
    id: str
    cart_mandate_id: str
    receipt: Receipt
    status: Literal[
        "CREATED", "PAID", "SHIPPED", "DELIVERED",
        "CANCELLED", "RETURN_REQUESTED", "RETURNED",
    ]
    timeline: list[Event] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    returns_window_days: int
