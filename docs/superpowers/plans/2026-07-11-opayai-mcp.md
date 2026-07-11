# opayai-mcp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `opayai-mcp`, an MCP server that takes a user's shopping prompt and drives it to a signed, policy-checked purchase across pluggable payment rails, with an approval gate and an audit trail, demoed from a CLI.

**Architecture:** A Python MCP server exposes commerce tools over deterministic modules (mandates, policy, rails, orders, audit). A CLI host connects as an MCP client, uses an LLM only at the front door (prompt -> structured Intent Mandate) and everything after is deterministic tool calls. Every tool call publishes to one append-only event bus that is simultaneously the live visualization and the audit trail/receipt.

**Tech Stack:** Python 3.11+, `mcp` (official MCP Python SDK, FastMCP-style), Pydantic v2, PyNaCl (Ed25519), Anthropic SDK, `rich`, pytest.

## Global Constraints

- Python 3.11+ only.
- All money is `Decimal`, never `float`. Currency default `"USD"`.
- All domain objects are Pydantic v2 models defined in `src/opayai/types.py`. No task redefines a type defined by Task 1.
- Signatures are Ed25519 (PyNaCl) over canonical JSON (`sort_keys=True`, `separators=(",",":")`, `model_dump(mode="json")`), excluding the `signature` field.
- Package import root is `opayai` (`src/opayai/...`). MCP server id/name is `opayai-mcp`.
- Use only the regular hyphen (`-`) in all code, comments, and copy. No em/en dashes.
- Every mutating tool publishes an `Event` to the shared bus before returning.
- Ownership tags: **[A]** Consent Core, **[B]** Money & Fulfillment, **[C]** Agent & Experience. Tasks 1-2 are done together; after that A/B/C run in parallel.

---

### Task 1: Project scaffold + frozen core types [ALL TOGETHER]

**Files:**
- Create: `pyproject.toml`
- Create: `src/opayai/__init__.py`
- Create: `src/opayai/types.py`
- Create: `tests/test_types.py`
- Create: `.gitignore`

**Interfaces:**
- Produces: all core Pydantic types consumed by every later task - `Money`, `Constraint`, `SpendingLimit`, `IntentMandate`, `CartItem`, `CartMandate`, `PolicyCheck`, `PolicyDecision`, `Event`, `Receipt`, `Offer`, `Order`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "opayai"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.2.0",
    "pydantic>=2.6",
    "pynacl>=1.5",
    "anthropic>=0.40",
    "rich>=13.7",
    "typer>=0.12",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/opayai"]

[tool.pytest.ini_options]
pythonpath = ["src"]
```

- [ ] **Step 2: Create `.gitignore`**

```
__pycache__/
*.pyc
.venv/
.env
dist/
*.egg-info/
```

- [ ] **Step 3: Write the failing test for the type contract**

Create `tests/test_types.py`:

```python
from datetime import datetime, timedelta
from decimal import Decimal
from opayai.types import (
    Money, Constraint, SpendingLimit, IntentMandate,
    CartItem, CartMandate, PolicyCheck, PolicyDecision,
    Event, Receipt, Offer, Order,
)


def _intent() -> IntentMandate:
    return IntentMandate(
        id="im_1", user_id="u_1",
        created_at=datetime(2026, 7, 11, 9, 0, 0),
        expires_at=datetime(2026, 7, 12, 9, 0, 0),
        human_present=False,
        constraint=Constraint(
            max_total=Money(amount=Decimal("300")),
            category="monitor",
            hard_requirements=["free_returns", "compat:macbook"],
        ),
        spending_limit=SpendingLimit(
            per_transaction=Money(amount=Decimal("400")),
            per_period=Money(amount=Decimal("1000")),
        ),
        signature="",
    )


def test_money_is_decimal():
    m = Money(amount=Decimal("12.5"))
    assert m.amount == Decimal("12.5")
    assert m.currency == "USD"


def test_intent_roundtrips_json():
    im = _intent()
    dumped = im.model_dump(mode="json")
    assert dumped["constraint"]["max_total"]["amount"] == "300"
    restored = IntentMandate.model_validate(dumped)
    assert restored == im


def test_cart_and_decision_build():
    cart = CartMandate(
        id="cm_1", intent_mandate_id="im_1",
        items=[CartItem(offer_id="of_1", title="Mon", qty=1,
                        unit_price=Money(amount=Decimal("289")))],
        total=Money(amount=Decimal("289")),
        selected_rail="x402", rationale="fits",
        created_at=datetime(2026, 7, 11, 9, 1, 0), signature="",
    )
    dec = PolicyDecision(
        cart_mandate_id="cm_1", result="AUTO_APPROVE",
        checks=[PolicyCheck(rule="budget", passed=True, detail="289<=300")],
    )
    assert cart.total.amount == Decimal("289")
    assert dec.result == "AUTO_APPROVE"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opayai.types'`

- [ ] **Step 5: Write `src/opayai/__init__.py` (empty) and `src/opayai/types.py`**

```python
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field


class Money(BaseModel):
    amount: Decimal
    currency: str = "USD"


class Constraint(BaseModel):
    max_total: Money
    category: str
    hard_requirements: list[str] = Field(default_factory=list)
    soft_preferences: list[str] = Field(default_factory=list)


class SpendingLimit(BaseModel):
    per_transaction: Money
    per_period: Money
    period: str = "day"


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
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_types.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git init && git add -A
git commit -m "feat: scaffold opayai-mcp with frozen core types"
```

---

### Task 2: Signing (Ed25519) [ALL TOGETHER]

**Files:**
- Create: `src/opayai/signing.py`
- Create: `tests/test_signing.py`

**Interfaces:**
- Consumes: `Money`, `IntentMandate` from Task 1.
- Produces: `canonical_payload(model, exclude=("signature",)) -> bytes`; `Signer` with `.verify_key_hex: str`, `.sign(model) -> str`, `.verify(model, signature_hex) -> bool`; `default_signer() -> Signer` (process-wide singleton seeded from a fixed demo seed for reproducibility).

- [ ] **Step 1: Write the failing test**

Create `tests/test_signing.py`:

```python
from datetime import datetime
from decimal import Decimal
from opayai.types import IntentMandate, Constraint, Money, SpendingLimit
from opayai.signing import Signer, canonical_payload


def _im(sig=""):
    return IntentMandate(
        id="im_1", user_id="u_1",
        created_at=datetime(2026, 7, 11, 9, 0, 0),
        expires_at=datetime(2026, 7, 12, 9, 0, 0),
        constraint=Constraint(max_total=Money(amount=Decimal("300")), category="monitor"),
        spending_limit=SpendingLimit(
            per_transaction=Money(amount=Decimal("400")),
            per_period=Money(amount=Decimal("1000"))),
        signature=sig,
    )


def test_canonical_payload_ignores_signature():
    assert canonical_payload(_im("A")) == canonical_payload(_im("B"))


def test_sign_and_verify_roundtrip():
    s = Signer()
    im = _im()
    sig = s.sign(im)
    signed = im.model_copy(update={"signature": sig})
    assert s.verify(signed, sig) is True


def test_tampered_object_fails_verify():
    s = Signer()
    im = _im()
    sig = s.sign(im)
    tampered = im.model_copy(update={
        "constraint": Constraint(max_total=Money(amount=Decimal("999")), category="monitor"),
        "signature": sig,
    })
    assert s.verify(tampered, sig) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_signing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opayai.signing'`

- [ ] **Step 3: Write `src/opayai/signing.py`**

```python
from __future__ import annotations
import json
from nacl.signing import SigningKey
from nacl.exceptions import BadSignatureError
from pydantic import BaseModel

_DEMO_SEED = bytes.fromhex(
    "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
)


def canonical_payload(model: BaseModel, exclude: tuple[str, ...] = ("signature",)) -> bytes:
    data = model.model_dump(mode="json", exclude=set(exclude))
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


class Signer:
    def __init__(self, signing_key: SigningKey | None = None):
        self._sk = signing_key or SigningKey.generate()
        self.verify_key_hex = self._sk.verify_key.encode().hex()

    def sign(self, model: BaseModel) -> str:
        return self._sk.sign(canonical_payload(model)).signature.hex()

    def verify(self, model: BaseModel, signature_hex: str) -> bool:
        try:
            self._sk.verify_key.verify(canonical_payload(model), bytes.fromhex(signature_hex))
            return True
        except (BadSignatureError, ValueError):
            return False


_default: Signer | None = None


def default_signer() -> Signer:
    global _default
    if _default is None:
        _default = Signer(SigningKey(_DEMO_SEED))
    return _default
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_signing.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opayai/signing.py tests/test_signing.py
git commit -m "feat: Ed25519 mandate signing over canonical JSON"
```

---

### Task 3: Mock data layer + loader [C]

**Files:**
- Create: `src/opayai/data/__init__.py`
- Create: `src/opayai/data/offers.json`
- Create: `src/opayai/data/persona.json`
- Create: `src/opayai/data/conversations.json`
- Create: `src/opayai/data/orders.json`
- Create: `tests/test_data.py`

**Interfaces:**
- Consumes: `Offer` from Task 1.
- Produces: `load_offers() -> list[Offer]`; `search_offers(category: str | None, max_price: Decimal | None) -> list[Offer]`; `load_persona() -> dict`; `load_conversations() -> list[dict]`; `load_seed_orders() -> list[dict]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_data.py`:

```python
from decimal import Decimal
from opayai.data import load_offers, search_offers, load_persona


def test_offers_load_as_models():
    offers = load_offers()
    assert len(offers) >= 3
    assert all(o.price.amount > 0 for o in offers)


def test_search_filters_by_price_and_category():
    hits = search_offers(category="monitor", max_price=Decimal("300"))
    assert len(hits) >= 1
    assert all(o.price.amount <= Decimal("300") for o in hits)
    assert all("monitor" in o.specs.get("category", "") or o.title for o in hits)


def test_persona_has_spending_defaults():
    p = load_persona()
    assert "defaults" in p
    assert "budget" in p["defaults"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opayai.data'`

- [ ] **Step 3: Create `src/opayai/data/offers.json`**

```json
[
  {"id":"of_1","title":"ViewPro 27 4K USB-C Monitor","merchant":"PixelMart","price":{"amount":"289.00","currency":"USD"},"stock_available":true,"stock_qty":12,"delivery_est_date":"2026-07-12","delivery_cutoff":"2026-07-11T18:00:00","returns_window_days":30,"free_returns":true,"warranty_months":24,"specs":{"category":"monitor","resolution":"4K","ports":["USB-C","HDMI"],"compat":["macbook"]},"rating":4.6},
  {"id":"of_2","title":"BudgetView 24 FHD Monitor","merchant":"DealBarn","price":{"amount":"149.00","currency":"USD"},"stock_available":true,"stock_qty":40,"delivery_est_date":"2026-07-14","delivery_cutoff":"2026-07-11T12:00:00","returns_window_days":14,"free_returns":false,"warranty_months":12,"specs":{"category":"monitor","resolution":"1080p","ports":["HDMI"],"compat":[]},"rating":4.0},
  {"id":"of_3","title":"ProArt 27 4K Thunderbolt Monitor","merchant":"CreatorHub","price":{"amount":"329.00","currency":"USD"},"stock_available":true,"stock_qty":5,"delivery_est_date":"2026-07-12","delivery_cutoff":"2026-07-11T20:00:00","returns_window_days":30,"free_returns":true,"warranty_months":36,"specs":{"category":"monitor","resolution":"4K","ports":["Thunderbolt","USB-C"],"compat":["macbook"]},"rating":4.8},
  {"id":"of_4","title":"OfficeView 27 QHD Monitor","merchant":"PixelMart","price":{"amount":"219.00","currency":"USD"},"stock_available":false,"stock_qty":0,"delivery_est_date":"2026-07-18","delivery_cutoff":"2026-07-11T18:00:00","returns_window_days":30,"free_returns":true,"warranty_months":24,"specs":{"category":"monitor","resolution":"1440p","ports":["USB-C","HDMI"],"compat":["macbook"]},"rating":4.3}
]
```

- [ ] **Step 4: Create `src/opayai/data/persona.json`**

```json
{"id":"u_1","name":"Alex Rivera","goals":["work efficiently from home"],"motivations":["quality","time saved"],"communication_style":"concise, decisive","defaults":{"budget":{"amount":"300","currency":"USD"},"brands":["known"],"sustainability":"prefer","risk_tolerance":"low"},"payment_methods":[{"id":"pm_card","type":"card","last4":"4242"},{"id":"pm_x402","type":"x402_wallet","label":"USDC wallet"}],"shipping":{"city":"Warsaw","country":"PL"}}
```

- [ ] **Step 5: Create `src/opayai/data/conversations.json`**

```json
[{"role":"user","text":"I use a MacBook Pro and hate dongles."},{"role":"assistant","text":"Noted: prefer USB-C / Thunderbolt native displays."},{"role":"user","text":"I always want free returns."}]
```

- [ ] **Step 6: Create `src/opayai/data/orders.json`**

```json
[{"id":"ord_seed_1","item":"USB-C Hub","merchant":"PixelMart","amount":{"amount":"49.00","currency":"USD"},"status":"DELIVERED","date":"2026-06-20"}]
```

- [ ] **Step 7: Write `src/opayai/data/__init__.py`**

```python
from __future__ import annotations
import json
from decimal import Decimal
from importlib import resources
from opayai.types import Offer


def _read(name: str):
    return json.loads(resources.files("opayai.data").joinpath(name).read_text())


def load_offers() -> list[Offer]:
    return [Offer.model_validate(o) for o in _read("offers.json")]


def search_offers(category: str | None = None, max_price: Decimal | None = None) -> list[Offer]:
    out = load_offers()
    if category:
        out = [o for o in out if o.specs.get("category") == category]
    if max_price is not None:
        out = [o for o in out if o.price.amount <= max_price]
    return out


def load_persona() -> dict:
    return _read("persona.json")


def load_conversations() -> list[dict]:
    return _read("conversations.json")


def load_seed_orders() -> list[dict]:
    return _read("orders.json")
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_data.py -v`
Expected: PASS (3 tests)

- [ ] **Step 9: Commit**

```bash
git add src/opayai/data tests/test_data.py
git commit -m "feat: mock catalog, persona, conversations, seed orders"
```

---

### Task 4: Event bus + audit trail [A]

**Files:**
- Create: `src/opayai/events.py`
- Create: `tests/test_events.py`

**Interfaces:**
- Consumes: `Event` from Task 1.
- Produces: `EventBus` with `.publish(type, actor, payload, mandate_ref=None) -> Event`, `.subscribe(callback)`, `.trail(mandate_ref=None) -> list[Event]`, `.all() -> list[Event]`; module-level `bus: EventBus` singleton; injectable `clock()` (defaults to `datetime.now(timezone.utc)`) so tests are deterministic.

- [ ] **Step 1: Write the failing test**

Create `tests/test_events.py`:

```python
from datetime import datetime, timezone
from opayai.events import EventBus


def _fixed_clock():
    return datetime(2026, 7, 11, 9, 0, 0, tzinfo=timezone.utc)


def test_publish_increments_seq_and_notifies():
    seen = []
    bus = EventBus(clock=_fixed_clock)
    bus.subscribe(seen.append)
    e1 = bus.publish("intent.created", "user", {"id": "im_1"}, mandate_ref="im_1")
    e2 = bus.publish("policy.evaluated", "policy", {"result": "AUTO_APPROVE"}, mandate_ref="im_1")
    assert e1.seq == 1 and e2.seq == 2
    assert [e.type for e in seen] == ["intent.created", "policy.evaluated"]


def test_trail_filters_by_mandate_ref():
    bus = EventBus(clock=_fixed_clock)
    bus.publish("a", "agent", {}, mandate_ref="im_1")
    bus.publish("b", "agent", {}, mandate_ref="im_2")
    assert [e.type for e in bus.trail("im_1")] == ["a"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opayai.events'`

- [ ] **Step 3: Write `src/opayai/events.py`**

```python
from __future__ import annotations
from datetime import datetime, timezone
from typing import Callable
from opayai.types import Event


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EventBus:
    def __init__(self, clock: Callable[[], datetime] = _utc_now):
        self._clock = clock
        self._seq = 0
        self._events: list[Event] = []
        self._subs: list[Callable[[Event], None]] = []

    def subscribe(self, cb: Callable[[Event], None]) -> None:
        self._subs.append(cb)

    def publish(self, type: str, actor: str, payload: dict,
                mandate_ref: str | None = None) -> Event:
        self._seq += 1
        e = Event(seq=self._seq, ts=self._clock(), type=type, actor=actor,
                  mandate_ref=mandate_ref, payload=payload)
        self._events.append(e)
        for cb in self._subs:
            cb(e)
        return e

    def all(self) -> list[Event]:
        return list(self._events)

    def trail(self, mandate_ref: str | None = None) -> list[Event]:
        if mandate_ref is None:
            return self.all()
        return [e for e in self._events if e.mandate_ref == mandate_ref]


bus = EventBus()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_events.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opayai/events.py tests/test_events.py
git commit -m "feat: append-only event bus that doubles as audit trail"
```

---

### Task 5: Mandate builders [A]

**Files:**
- Create: `src/opayai/mandate.py`
- Create: `tests/test_mandate.py`

**Interfaces:**
- Consumes: types (Task 1), `default_signer` (Task 2), `bus` (Task 4).
- Produces: `create_intent_mandate(user_id, constraint, spending_limit, ttl_hours=24, now=None) -> IntentMandate` (signed, publishes `intent.created`); `propose_cart(intent, offers, rail, rationale, now=None) -> CartMandate` (signed, publishes `cart.proposed`). IDs are deterministic counters (`im_1`, `cm_1`, ...) via an injectable `IdGen` so demos and tests are stable.

- [ ] **Step 1: Write the failing test**

Create `tests/test_mandate.py`:

```python
from datetime import datetime
from decimal import Decimal
from opayai.types import Constraint, Money, SpendingLimit, Offer
from opayai.signing import default_signer
from opayai.mandate import create_intent_mandate, propose_cart
from opayai.events import EventBus
import opayai.mandate as mandate_mod


def _now():
    return datetime(2026, 7, 11, 9, 0, 0)


def _offer():
    return Offer(id="of_1", title="Mon", merchant="M", price=Money(amount=Decimal("289")),
                 stock_available=True, stock_qty=3, delivery_est_date="2026-07-12",
                 delivery_cutoff="2026-07-11T18:00:00", returns_window_days=30,
                 free_returns=True, warranty_months=24, specs={"category": "monitor"}, rating=4.6)


def test_intent_is_signed_and_published(monkeypatch):
    b = EventBus()
    monkeypatch.setattr(mandate_mod, "bus", b)
    mandate_mod.reset_ids()
    im = create_intent_mandate(
        "u_1",
        Constraint(max_total=Money(amount=Decimal("300")), category="monitor"),
        SpendingLimit(per_transaction=Money(amount=Decimal("400")),
                      per_period=Money(amount=Decimal("1000"))),
        now=_now())
    assert im.id == "im_1"
    assert default_signer().verify(im, im.signature) is True
    assert [e.type for e in b.all()] == ["intent.created"]


def test_cart_totals_and_signed(monkeypatch):
    b = EventBus()
    monkeypatch.setattr(mandate_mod, "bus", b)
    mandate_mod.reset_ids()
    im = create_intent_mandate(
        "u_1",
        Constraint(max_total=Money(amount=Decimal("300")), category="monitor"),
        SpendingLimit(per_transaction=Money(amount=Decimal("400")),
                      per_period=Money(amount=Decimal("1000"))),
        now=_now())
    cart = propose_cart(im, [_offer()], rail="x402", rationale="fits", now=_now())
    assert cart.total.amount == Decimal("289")
    assert cart.intent_mandate_id == im.id
    assert default_signer().verify(cart, cart.signature) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mandate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opayai.mandate'`

- [ ] **Step 3: Write `src/opayai/mandate.py`**

```python
from __future__ import annotations
from datetime import datetime, timedelta
from decimal import Decimal
from opayai.types import (IntentMandate, CartMandate, CartItem, Constraint,
                          SpendingLimit, Money, Offer)
from opayai.signing import default_signer
from opayai.events import bus

_counters: dict[str, int] = {}


def reset_ids() -> None:
    _counters.clear()


def _next(prefix: str) -> str:
    _counters[prefix] = _counters.get(prefix, 0) + 1
    return f"{prefix}_{_counters[prefix]}"


def create_intent_mandate(user_id: str, constraint: Constraint,
                          spending_limit: SpendingLimit, ttl_hours: int = 24,
                          now: datetime | None = None) -> IntentMandate:
    now = now or datetime.utcnow()
    im = IntentMandate(
        id=_next("im"), user_id=user_id, created_at=now,
        expires_at=now + timedelta(hours=ttl_hours), human_present=False,
        constraint=constraint, spending_limit=spending_limit)
    im.signature = default_signer().sign(im)
    bus.publish("intent.created", "user",
                {"id": im.id, "max_total": str(constraint.max_total.amount),
                 "category": constraint.category}, mandate_ref=im.id)
    return im


def propose_cart(intent: IntentMandate, offers: list[Offer], rail: str,
                 rationale: str, now: datetime | None = None) -> CartMandate:
    now = now or datetime.utcnow()
    items = [CartItem(offer_id=o.id, title=o.title, qty=1, unit_price=o.price)
             for o in offers]
    total = Money(amount=sum((o.price.amount for o in offers), Decimal("0")),
                  currency=offers[0].price.currency if offers else "USD")
    cart = CartMandate(id=_next("cm"), intent_mandate_id=intent.id, items=items,
                       total=total, selected_rail=rail, rationale=rationale,
                       created_at=now)
    cart.signature = default_signer().sign(cart)
    bus.publish("cart.proposed", "agent",
                {"id": cart.id, "total": str(total.amount), "rail": rail,
                 "rationale": rationale}, mandate_ref=intent.id)
    return cart
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mandate.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opayai/mandate.py tests/test_mandate.py
git commit -m "feat: signed intent and cart mandate builders"
```

---

### Task 6: Policy engine [A]

**Files:**
- Create: `src/opayai/policy.py`
- Create: `tests/test_policy.py`

**Interfaces:**
- Consumes: types (Task 1), `default_signer` (Task 2), `bus` (Task 4).
- Produces: `evaluate_policy(intent, cart, offers_by_id, period_spent=Decimal("0")) -> PolicyDecision` (publishes `policy.evaluated`). Rules in order: signature verify (fail -> REJECT), hard requirements satisfied (fail -> REJECT), budget `total <= max_total` (fail -> REJECT), spending limits (`per_transaction`, and `period_spent + total <= per_period`; exceed -> ESCALATE). All pass -> AUTO_APPROVE. `hard_requirements` grammar: `free_returns`, `compat:<tag>`, `arrives_by:<YYYY-MM-DD>`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_policy.py`:

```python
from datetime import datetime
from decimal import Decimal
from opayai.types import (Constraint, Money, SpendingLimit, Offer)
from opayai.mandate import create_intent_mandate, propose_cart, reset_ids
from opayai.policy import evaluate_policy


def _offer(id="of_1", price="289", free_returns=True, compat=("macbook",),
           est="2026-07-12"):
    return Offer(id=id, title="Mon", merchant="M", price=Money(amount=Decimal(price)),
                 stock_available=True, stock_qty=3, delivery_est_date=est,
                 delivery_cutoff="2026-07-11T18:00:00", returns_window_days=30,
                 free_returns=free_returns, warranty_months=24,
                 specs={"category": "monitor", "compat": list(compat)}, rating=4.6)


def _intent(max_total="300", per_txn="400", per_period="1000",
            reqs=("free_returns", "compat:macbook", "arrives_by:2026-07-12")):
    reset_ids()
    return create_intent_mandate(
        "u_1",
        Constraint(max_total=Money(amount=Decimal(max_total)), category="monitor",
                   hard_requirements=list(reqs)),
        SpendingLimit(per_transaction=Money(amount=Decimal(per_txn)),
                      per_period=Money(amount=Decimal(per_period))),
        now=datetime(2026, 7, 11, 9, 0, 0))


def test_auto_approve_when_all_pass():
    im = _intent()
    offers = [_offer()]
    cart = propose_cart(im, offers, "x402", "fits", now=datetime(2026, 7, 11, 9, 1))
    dec = evaluate_policy(im, cart, {o.id: o for o in offers})
    assert dec.result == "AUTO_APPROVE"


def test_reject_over_budget():
    im = _intent(max_total="250")
    offers = [_offer(price="289")]
    cart = propose_cart(im, offers, "x402", "fits", now=datetime(2026, 7, 11, 9, 1))
    dec = evaluate_policy(im, cart, {o.id: o for o in offers})
    assert dec.result == "REJECT"
    assert any(c.rule == "budget" and not c.passed for c in dec.checks)


def test_reject_missing_free_returns():
    im = _intent()
    offers = [_offer(free_returns=False)]
    cart = propose_cart(im, offers, "x402", "fits", now=datetime(2026, 7, 11, 9, 1))
    dec = evaluate_policy(im, cart, {o.id: o for o in offers})
    assert dec.result == "REJECT"
    assert any(c.rule == "hard_requirement:free_returns" and not c.passed for c in dec.checks)


def test_escalate_when_period_limit_exceeded():
    im = _intent(per_period="300")
    offers = [_offer(price="289")]
    cart = propose_cart(im, offers, "x402", "fits", now=datetime(2026, 7, 11, 9, 1))
    dec = evaluate_policy(im, cart, {o.id: o for o in offers}, period_spent=Decimal("50"))
    assert dec.result == "ESCALATE"
    assert any(c.rule == "spending_limit:per_period" and not c.passed for c in dec.checks)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_policy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opayai.policy'`

- [ ] **Step 3: Write `src/opayai/policy.py`**

```python
from __future__ import annotations
from decimal import Decimal
from opayai.types import IntentMandate, CartMandate, Offer, PolicyCheck, PolicyDecision
from opayai.signing import default_signer
from opayai.events import bus


def _check_hard_requirement(req: str, offers: list[Offer]) -> PolicyCheck:
    if req == "free_returns":
        ok = all(o.free_returns for o in offers)
        return PolicyCheck(rule="hard_requirement:free_returns", passed=ok,
                           detail="all items free returns" if ok else "an item lacks free returns")
    if req.startswith("compat:"):
        tag = req.split(":", 1)[1]
        ok = all(tag in o.specs.get("compat", []) for o in offers)
        return PolicyCheck(rule=f"hard_requirement:{req}", passed=ok,
                           detail=f"compat {tag}: {'ok' if ok else 'missing'}")
    if req.startswith("arrives_by:"):
        deadline = req.split(":", 1)[1]
        ok = all(o.delivery_est_date <= deadline for o in offers)
        return PolicyCheck(rule=f"hard_requirement:{req}", passed=ok,
                           detail=f"delivery by {deadline}: {'ok' if ok else 'too late'}")
    return PolicyCheck(rule=f"hard_requirement:{req}", passed=True, detail="unknown requirement, skipped")


def evaluate_policy(intent: IntentMandate, cart: CartMandate,
                    offers_by_id: dict[str, Offer],
                    period_spent: Decimal = Decimal("0")) -> PolicyDecision:
    checks: list[PolicyCheck] = []
    result = "AUTO_APPROVE"

    sig_ok = (default_signer().verify(intent, intent.signature)
              and default_signer().verify(cart, cart.signature))
    checks.append(PolicyCheck(rule="signature", passed=sig_ok,
                              detail="mandates verify" if sig_ok else "signature invalid"))
    if not sig_ok:
        result = "REJECT"

    offers = [offers_by_id[i.offer_id] for i in cart.items]
    for req in intent.constraint.hard_requirements:
        c = _check_hard_requirement(req, offers)
        checks.append(c)
        if not c.passed:
            result = "REJECT"

    budget_ok = cart.total.amount <= intent.constraint.max_total.amount
    checks.append(PolicyCheck(rule="budget", passed=budget_ok,
                              detail=f"{cart.total.amount} <= {intent.constraint.max_total.amount}"))
    if not budget_ok:
        result = "REJECT"

    txn_ok = cart.total.amount <= intent.spending_limit.per_transaction.amount
    checks.append(PolicyCheck(rule="spending_limit:per_transaction", passed=txn_ok,
                              detail=f"{cart.total.amount} <= {intent.spending_limit.per_transaction.amount}"))
    period_ok = period_spent + cart.total.amount <= intent.spending_limit.per_period.amount
    checks.append(PolicyCheck(rule="spending_limit:per_period", passed=period_ok,
                              detail=f"{period_spent}+{cart.total.amount} <= {intent.spending_limit.per_period.amount}"))
    if result != "REJECT" and not (txn_ok and period_ok):
        result = "ESCALATE"

    dec = PolicyDecision(cart_mandate_id=cart.id, result=result, checks=checks)
    bus.publish("policy.evaluated", "policy",
                {"result": result, "checks": [c.model_dump() for c in checks]},
                mandate_ref=intent.id)
    return dec
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_policy.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opayai/policy.py tests/test_policy.py
git commit -m "feat: policy engine (budget, hard reqs, spending limits, signatures)"
```

---

### Task 7: Payment rails [B]

**Files:**
- Create: `src/opayai/rails.py`
- Create: `tests/test_rails.py`

**Interfaces:**
- Consumes: types (Task 1), `bus` (Task 4).
- Produces: `PaymentRail` Protocol with `name: str` and `charge(cart, now=None) -> Receipt`; `MockX402Rail`, `MockCardRail`; `get_rail(name) -> PaymentRail` registry over `{"x402","card"}`. Each `charge` publishes `payment.settled`. Receipt ids/refs deterministic via injectable counter.

- [ ] **Step 1: Write the failing test**

Create `tests/test_rails.py`:

```python
from datetime import datetime
from decimal import Decimal
from opayai.types import CartMandate, CartItem, Money
from opayai.rails import get_rail, MockX402Rail
import opayai.rails as rails_mod


def _cart(rail="x402"):
    return CartMandate(id="cm_1", intent_mandate_id="im_1",
                       items=[CartItem(offer_id="of_1", title="Mon", qty=1,
                                       unit_price=Money(amount=Decimal("289")))],
                       total=Money(amount=Decimal("289")), selected_rail=rail,
                       rationale="fits", created_at=datetime(2026, 7, 11, 9, 1),
                       signature="sig")


def test_x402_charge_returns_receipt():
    rails_mod.reset_rail_ids()
    r = get_rail("x402")
    rec = r.charge(_cart("x402"), now=datetime(2026, 7, 11, 9, 2))
    assert rec.rail == "x402"
    assert rec.amount.amount == Decimal("289")
    assert rec.rail_reference.startswith("x402_")


def test_card_charge_returns_receipt():
    rails_mod.reset_rail_ids()
    rec = get_rail("card").charge(_cart("card"), now=datetime(2026, 7, 11, 9, 2))
    assert rec.rail == "card"
    assert rec.rail_reference.startswith("card_")


def test_unknown_rail_raises():
    try:
        get_rail("nope")
        assert False
    except KeyError:
        assert True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rails.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opayai.rails'`

- [ ] **Step 3: Write `src/opayai/rails.py`**

```python
from __future__ import annotations
from datetime import datetime
from typing import Protocol
from opayai.types import CartMandate, Receipt
from opayai.events import bus

_counter = {"n": 0}


def reset_rail_ids() -> None:
    _counter["n"] = 0


def _ref(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}_{_counter['n']:04d}"


class PaymentRail(Protocol):
    name: str
    def charge(self, cart: CartMandate, now: datetime | None = None) -> Receipt: ...


class _BaseRail:
    name = "base"

    def charge(self, cart: CartMandate, now: datetime | None = None) -> Receipt:
        now = now or datetime.utcnow()
        rec = Receipt(id=_ref("rcpt"), cart_mandate_id=cart.id, rail=self.name,
                      amount=cart.total, paid_at=now, rail_reference=_ref(self.name))
        bus.publish("payment.settled", "rail",
                    {"rail": self.name, "amount": str(cart.total.amount),
                     "reference": rec.rail_reference}, mandate_ref=cart.intent_mandate_id)
        return rec


class MockX402Rail(_BaseRail):
    name = "x402"


class MockCardRail(_BaseRail):
    name = "card"


_REGISTRY: dict[str, PaymentRail] = {"x402": MockX402Rail(), "card": MockCardRail()}


def get_rail(name: str) -> PaymentRail:
    return _REGISTRY[name]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_rails.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opayai/rails.py tests/test_rails.py
git commit -m "feat: pluggable payment rails (mock x402 + mock card)"
```

---

### Task 8: Order lifecycle + returns/cancel [B]

**Files:**
- Create: `src/opayai/orders.py`
- Create: `tests/test_orders.py`

**Interfaces:**
- Consumes: types (Task 1), `bus` (Task 4).
- Produces: `OrderStore` with `.create(cart, receipt, now=None) -> Order` (status PAID), `.advance(order_id, now=None) -> Order` (PAID->SHIPPED->DELIVERED), `.cancel(order_id) -> Order` (only before SHIPPED), `.request_return(order_id, reason, returns_window_days, now=None) -> Order` (only when DELIVERED and within window), `.get(order_id) -> Order`; module-level `store: OrderStore`. Illegal transitions raise `ValueError`. Every transition appends an `Event` and publishes to `bus`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_orders.py`:

```python
from datetime import datetime
from decimal import Decimal
from opayai.types import CartMandate, CartItem, Money, Receipt
from opayai.orders import OrderStore


def _cart():
    return CartMandate(id="cm_1", intent_mandate_id="im_1",
                       items=[CartItem(offer_id="of_1", title="Mon", qty=1,
                                       unit_price=Money(amount=Decimal("289")))],
                       total=Money(amount=Decimal("289")), selected_rail="x402",
                       rationale="fits", created_at=datetime(2026, 7, 11, 9, 1), signature="s")


def _receipt():
    return Receipt(id="rcpt_1", cart_mandate_id="cm_1", rail="x402",
                   amount=Money(amount=Decimal("289")), paid_at=datetime(2026, 7, 11, 9, 2),
                   rail_reference="x402_0001")


def test_create_is_paid_and_advances():
    s = OrderStore()
    o = s.create(_cart(), _receipt())
    assert o.status == "PAID"
    assert s.advance(o.id).status == "SHIPPED"
    assert s.advance(o.id).status == "DELIVERED"


def test_cancel_only_before_shipped():
    s = OrderStore()
    o = s.create(_cart(), _receipt())
    assert s.cancel(o.id).status == "CANCELLED"
    o2 = s.create(_cart(), _receipt())
    s.advance(o2.id)  # SHIPPED
    try:
        s.cancel(o2.id)
        assert False
    except ValueError:
        assert True


def test_return_requires_delivered_and_in_window():
    s = OrderStore()
    o = s.create(_cart(), _receipt())
    s.advance(o.id); s.advance(o.id)  # DELIVERED
    r = s.request_return(o.id, "changed mind", returns_window_days=30,
                         now=datetime(2026, 7, 15, 9, 0))
    assert r.status == "RETURN_REQUESTED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orders.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opayai.orders'`

- [ ] **Step 3: Write `src/opayai/orders.py`**

```python
from __future__ import annotations
from datetime import datetime, timedelta
from opayai.types import CartMandate, Receipt, Order, Event
from opayai.events import bus

_ADVANCE = {"PAID": "SHIPPED", "SHIPPED": "DELIVERED"}


class OrderStore:
    def __init__(self):
        self._orders: dict[str, Order] = {}
        self._n = 0

    def _record(self, order: Order, type: str, now: datetime) -> None:
        e = Event(seq=len(order.timeline) + 1, ts=now, type=type, actor="merchant",
                  mandate_ref=order.cart_mandate_id, payload={"status": order.status})
        order.timeline.append(e)
        bus.publish(type, "merchant", {"order_id": order.id, "status": order.status},
                    mandate_ref=order.cart_mandate_id)

    def create(self, cart: CartMandate, receipt: Receipt, now: datetime | None = None) -> Order:
        now = now or datetime.utcnow()
        self._n += 1
        o = Order(id=f"ord_{self._n}", cart_mandate_id=cart.id, receipt=receipt, status="PAID")
        self._orders[o.id] = o
        self._record(o, "order.created", now)
        return o

    def get(self, order_id: str) -> Order:
        return self._orders[order_id]

    def advance(self, order_id: str, now: datetime | None = None) -> Order:
        now = now or datetime.utcnow()
        o = self._orders[order_id]
        if o.status not in _ADVANCE:
            raise ValueError(f"cannot advance from {o.status}")
        o.status = _ADVANCE[o.status]
        self._record(o, "order.advanced", now)
        return o

    def cancel(self, order_id: str, now: datetime | None = None) -> Order:
        now = now or datetime.utcnow()
        o = self._orders[order_id]
        if o.status not in ("CREATED", "PAID"):
            raise ValueError(f"cannot cancel from {o.status}")
        o.status = "CANCELLED"
        self._record(o, "order.cancelled", now)
        return o

    def request_return(self, order_id: str, reason: str, returns_window_days: int,
                       now: datetime | None = None) -> Order:
        now = now or datetime.utcnow()
        o = self._orders[order_id]
        if o.status != "DELIVERED":
            raise ValueError("returns require a delivered order")
        if now > o.receipt.paid_at + timedelta(days=returns_window_days):
            raise ValueError("outside returns window")
        o.status = "RETURN_REQUESTED"
        o.exceptions.append(f"return: {reason}")
        self._record(o, "order.return_requested", now)
        return o


store = OrderStore()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_orders.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opayai/orders.py tests/test_orders.py
git commit -m "feat: order lifecycle state machine with cancel and returns"
```

---

### Task 9: MCP server wiring [C]

**Files:**
- Create: `src/opayai/server.py`
- Create: `tests/test_server.py`

**Interfaces:**
- Consumes: everything from Tasks 3-8.
- Produces: a FastMCP server `app` named `opayai-mcp` exposing tools `search_offers`, `create_intent_mandate`, `propose_cart`, `evaluate_policy`, `request_approval`, `execute_payment`, `get_order`, `advance_order`, `create_return`, `cancel_order`, `get_audit_trail`. Tools accept/return plain JSON-able dicts (validated through the Task 1 models internally). A module-level `SESSION` dict holds the in-memory intents/carts/offers/period_spent so tools can reference prior objects by id. `run()` starts stdio transport.

- [ ] **Step 1: Write the failing test (drives the tool functions directly, not over stdio)**

Create `tests/test_server.py`:

```python
from opayai import server


def setup_function():
    server.reset_session()


def test_end_to_end_happy_path():
    intent = server.create_intent_mandate(
        user_id="u_1", category="monitor", max_total="300",
        hard_requirements=["free_returns", "compat:macbook", "arrives_by:2026-07-12"],
        per_transaction="400", per_period="1000")
    offers = server.search_offers(category="monitor", max_price="300")
    picked = [o["id"] for o in offers if o["free_returns"]
              and "macbook" in o["specs"].get("compat", [])
              and o["delivery_est_date"] <= "2026-07-12"][:1]
    cart = server.propose_cart(intent_id=intent["id"], offer_ids=picked,
                               rail="x402", rationale="best fit")
    decision = server.evaluate_policy(cart_id=cart["id"])
    assert decision["result"] == "AUTO_APPROVE"
    order = server.execute_payment(cart_id=cart["id"])
    assert order["status"] == "PAID"
    trail = server.get_audit_trail(mandate_ref=intent["id"])
    types = [e["type"] for e in trail]
    assert "intent.created" in types and "payment.settled" in types


def test_escalation_blocks_until_approval():
    intent = server.create_intent_mandate(
        user_id="u_1", category="monitor", max_total="400",
        hard_requirements=[], per_transaction="400", per_period="300")
    offers = server.search_offers(category="monitor", max_price="400")
    picked = [offers[0]["id"]]
    cart = server.propose_cart(intent_id=intent["id"], offer_ids=picked,
                               rail="card", rationale="pick")
    decision = server.evaluate_policy(cart_id=cart["id"])
    assert decision["result"] == "ESCALATE"
    # paying an un-approved escalated cart is refused
    try:
        server.execute_payment(cart_id=cart["id"])
        assert False
    except ValueError:
        assert True
    server.request_approval(cart_id=cart["id"], approved=True)
    order = server.execute_payment(cart_id=cart["id"])
    assert order["status"] == "PAID"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_server.py -v`
Expected: FAIL with `ImportError` / `AttributeError` (functions not defined)

- [ ] **Step 3: Write `src/opayai/server.py`**

```python
from __future__ import annotations
from decimal import Decimal
from mcp.server.fastmcp import FastMCP
from opayai.types import Constraint, Money, SpendingLimit
from opayai import mandate as mandate_mod
from opayai import data, rails as rails_mod
from opayai.mandate import create_intent_mandate as _create_intent, propose_cart as _propose
from opayai.policy import evaluate_policy as _evaluate
from opayai.orders import store as order_store
from opayai.events import bus

app = FastMCP("opayai-mcp")

SESSION: dict = {}


def reset_session() -> None:
    SESSION.clear()
    SESSION.update({"intents": {}, "carts": {}, "offers": {}, "decisions": {},
                    "approved": set(), "period_spent": Decimal("0")})
    mandate_mod.reset_ids()
    rails_mod.reset_rail_ids()


reset_session()


@app.tool()
def search_offers(category: str | None = None, max_price: str | None = None) -> list[dict]:
    mp = Decimal(max_price) if max_price is not None else None
    offers = data.search_offers(category=category, max_price=mp)
    for o in offers:
        SESSION["offers"][o.id] = o
    return [o.model_dump(mode="json") for o in offers]


@app.tool()
def create_intent_mandate(user_id: str, category: str, max_total: str,
                          hard_requirements: list[str], per_transaction: str,
                          per_period: str) -> dict:
    im = _create_intent(
        user_id,
        Constraint(max_total=Money(amount=Decimal(max_total)), category=category,
                   hard_requirements=hard_requirements),
        SpendingLimit(per_transaction=Money(amount=Decimal(per_transaction)),
                      per_period=Money(amount=Decimal(per_period))))
    SESSION["intents"][im.id] = im
    return im.model_dump(mode="json")


@app.tool()
def propose_cart(intent_id: str, offer_ids: list[str], rail: str, rationale: str) -> dict:
    intent = SESSION["intents"][intent_id]
    offers = [SESSION["offers"][oid] for oid in offer_ids]
    cart = _propose(intent, offers, rail=rail, rationale=rationale)
    SESSION["carts"][cart.id] = cart
    return cart.model_dump(mode="json")


@app.tool()
def evaluate_policy(cart_id: str) -> dict:
    cart = SESSION["carts"][cart_id]
    intent = SESSION["intents"][cart.intent_mandate_id]
    dec = _evaluate(intent, cart, SESSION["offers"], period_spent=SESSION["period_spent"])
    SESSION["decisions"][cart_id] = dec
    return dec.model_dump(mode="json")


@app.tool()
def request_approval(cart_id: str, approved: bool) -> dict:
    if approved:
        SESSION["approved"].add(cart_id)
    bus.publish("approval.recorded", "user", {"cart_id": cart_id, "approved": approved},
                mandate_ref=SESSION["carts"][cart_id].intent_mandate_id)
    return {"cart_id": cart_id, "approved": approved}


@app.tool()
def execute_payment(cart_id: str) -> dict:
    cart = SESSION["carts"][cart_id]
    dec = SESSION["decisions"].get(cart_id)
    if dec is None:
        raise ValueError("evaluate_policy must run before payment")
    if dec.result == "REJECT":
        raise ValueError("policy rejected this cart")
    if dec.result == "ESCALATE" and cart_id not in SESSION["approved"]:
        raise ValueError("cart requires user approval before payment")
    receipt = rails_mod.get_rail(cart.selected_rail).charge(cart)
    order = order_store.create(cart, receipt)
    SESSION["period_spent"] += cart.total.amount
    return order.model_dump(mode="json")


@app.tool()
def advance_order(order_id: str) -> dict:
    return order_store.advance(order_id).model_dump(mode="json")


@app.tool()
def get_order(order_id: str) -> dict:
    return order_store.get(order_id).model_dump(mode="json")


@app.tool()
def cancel_order(order_id: str) -> dict:
    return order_store.cancel(order_id).model_dump(mode="json")


@app.tool()
def create_return(order_id: str, reason: str, returns_window_days: int = 30) -> dict:
    return order_store.request_return(order_id, reason, returns_window_days).model_dump(mode="json")


@app.tool()
def get_audit_trail(mandate_ref: str | None = None) -> list[dict]:
    return [e.model_dump(mode="json") for e in bus.trail(mandate_ref)]


def run() -> None:
    app.run()


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_server.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opayai/server.py tests/test_server.py
git commit -m "feat: opayai-mcp server exposing the commerce tool surface"
```

---

### Task 10: LLM front door [C]

**Files:**
- Create: `src/opayai/front_door.py`
- Create: `tests/test_front_door.py`

**Interfaces:**
- Consumes: `Constraint`, `Money`, `SpendingLimit` (Task 1).
- Produces: `parse_prompt(prompt, persona, client=None) -> tuple[Constraint, SpendingLimit]`. When `client is None` (tests/offline) it uses a deterministic `heuristic_parse`. With a real Anthropic client it asks Claude for structured JSON and falls back to the heuristic on any error. Model id read from `OPAYAI_MODEL` env, default `"claude-sonnet-5"` (verify the current id against the claude-api skill before the live demo).

- [ ] **Step 1: Write the failing test**

Create `tests/test_front_door.py`:

```python
from decimal import Decimal
from opayai.data import load_persona
from opayai.front_door import heuristic_parse, parse_prompt


def test_heuristic_extracts_budget_and_requirements():
    c, limit = heuristic_parse(
        "Find me the best monitor under $300 that works with my MacBook, "
        "arrives tomorrow, and has good return terms. Buy it if you're confident.",
        load_persona())
    assert c.max_total.amount == Decimal("300")
    assert c.category == "monitor"
    assert "free_returns" in c.hard_requirements
    assert "compat:macbook" in c.hard_requirements
    assert limit.per_transaction.amount >= Decimal("300")


def test_parse_prompt_offline_uses_heuristic():
    c, _ = parse_prompt("cheap monitor under $150", load_persona(), client=None)
    assert c.max_total.amount == Decimal("150")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_front_door.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opayai.front_door'`

- [ ] **Step 3: Write `src/opayai/front_door.py`**

```python
from __future__ import annotations
import json
import os
import re
from decimal import Decimal
from opayai.types import Constraint, Money, SpendingLimit

_CATEGORIES = ["monitor", "keyboard", "mouse", "laptop", "headphones", "hub"]


def heuristic_parse(prompt: str, persona: dict) -> tuple[Constraint, SpendingLimit]:
    text = prompt.lower()
    m = re.search(r"\$?\s*(\d+(?:\.\d+)?)", text)
    budget = Decimal(m.group(1)) if m else Decimal(str(persona["defaults"]["budget"]["amount"]))
    category = next((c for c in _CATEGORIES if c in text), "monitor")
    reqs: list[str] = []
    if "return" in text:
        reqs.append("free_returns")
    if "macbook" in text or "mac" in text:
        reqs.append("compat:macbook")
    if "tomorrow" in text:
        reqs.append("arrives_by:2026-07-12")
    constraint = Constraint(max_total=Money(amount=budget), category=category,
                            hard_requirements=reqs)
    limit = SpendingLimit(
        per_transaction=Money(amount=budget + Decimal("50")),
        per_period=Money(amount=budget * Decimal("3")))
    return constraint, limit


def parse_prompt(prompt: str, persona: dict, client=None) -> tuple[Constraint, SpendingLimit]:
    if client is None:
        return heuristic_parse(prompt, persona)
    model = os.environ.get("OPAYAI_MODEL", "claude-sonnet-5")
    schema_hint = (
        'Return ONLY JSON: {"category": str, "max_total": number, '
        '"hard_requirements": [str], "per_transaction": number, "per_period": number}. '
        'hard_requirements use tokens: "free_returns", "compat:macbook", "arrives_by:YYYY-MM-DD". '
        "Use only the regular hyphen (-)."
    )
    try:
        msg = client.messages.create(
            model=model, max_tokens=400,
            messages=[{"role": "user",
                       "content": f"{schema_hint}\nPersona: {json.dumps(persona)}\nPrompt: {prompt}"}])
        raw = msg.content[0].text
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        constraint = Constraint(
            max_total=Money(amount=Decimal(str(data["max_total"]))),
            category=data["category"], hard_requirements=data.get("hard_requirements", []))
        limit = SpendingLimit(
            per_transaction=Money(amount=Decimal(str(data["per_transaction"]))),
            per_period=Money(amount=Decimal(str(data["per_period"]))))
        return constraint, limit
    except Exception:
        return heuristic_parse(prompt, persona)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_front_door.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/opayai/front_door.py tests/test_front_door.py
git commit -m "feat: LLM front door with offline heuristic fallback"
```

---

### Task 11: CLI host + live event renderer + demo [C]

**Files:**
- Create: `src/opayai/cli.py`
- Create: `README.md`
- Create: `tests/test_cli.py`

**Interfaces:**
- Consumes: `server` tool functions (Task 9), `front_door.parse_prompt` (Task 10), `data.load_persona` (Task 3), `bus` (Task 4).
- Produces: `run_flow(prompt, auto_pick, approve, client=None) -> dict` that drives discover -> decide -> approve -> purchase -> track -> resolve in-process (calling the Task 9 tool functions directly), rendering each event with `rich`. `auto_pick(offers, constraint) -> list[str]` selects offers satisfying hard requirements. `main()` is a `typer` entrypoint. `approve` is a callback `(cart, decision) -> bool` (CLI prompts; tests inject a stub).

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli.py`:

```python
from opayai import server
from opayai.cli import run_flow


def setup_function():
    server.reset_session()


def test_run_flow_completes_purchase_and_return():
    result = run_flow(
        prompt="Find me the best monitor under $300 that works with my MacBook, "
               "arrives tomorrow, and has good return terms. Buy it if you're confident.",
        approve=lambda cart, decision: True,
        do_return=True,
        client=None)
    assert result["order"]["status"] in ("RETURN_REQUESTED",)
    assert result["decision"]["result"] in ("AUTO_APPROVE", "ESCALATE")
    assert result["receipt_reference"].startswith(("x402_", "card_"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opayai.cli'`

- [ ] **Step 3: Write `src/opayai/cli.py`**

```python
from __future__ import annotations
from decimal import Decimal
from typing import Callable
import typer
from rich.console import Console
from opayai import server
from opayai.data import load_persona
from opayai.events import bus
from opayai.front_door import parse_prompt
from opayai.types import Constraint

console = Console()


def auto_pick(offers: list[dict], constraint: Constraint) -> list[str]:
    reqs = constraint.hard_requirements
    def ok(o: dict) -> bool:
        if "free_returns" in reqs and not o["free_returns"]:
            return False
        for r in reqs:
            if r.startswith("compat:") and r.split(":", 1)[1] not in o["specs"].get("compat", []):
                return False
            if r.startswith("arrives_by:") and o["delivery_est_date"] > r.split(":", 1)[1]:
                return False
        return o["stock_available"] and Decimal(o["price"]["amount"]) <= constraint.max_total.amount
    ranked = sorted((o for o in offers if ok(o)), key=lambda o: -o["rating"])
    return [ranked[0]["id"]] if ranked else []


def _render(event) -> None:
    console.print(f"[dim]#{event.seq}[/dim] [bold cyan]{event.type}[/bold cyan] "
                  f"[magenta]{event.actor}[/magenta] {event.payload}")


def run_flow(prompt: str, approve: Callable[[dict, dict], bool],
             do_return: bool = False, client=None) -> dict:
    bus.subscribe(_render)
    persona = load_persona()
    constraint, limit = parse_prompt(prompt, persona, client=client)
    intent = server.create_intent_mandate(
        user_id=persona["id"], category=constraint.category,
        max_total=str(constraint.max_total.amount),
        hard_requirements=constraint.hard_requirements,
        per_transaction=str(limit.per_transaction.amount),
        per_period=str(limit.per_period.amount))
    offers = server.search_offers(category=constraint.category,
                                  max_price=str(constraint.max_total.amount))
    picked = auto_pick(offers, constraint)
    cart = server.propose_cart(intent_id=intent["id"], offer_ids=picked,
                               rail="x402", rationale="best rated within constraints")
    decision = server.evaluate_policy(cart_id=cart["id"])
    if decision["result"] == "REJECT":
        return {"intent": intent, "cart": cart, "decision": decision, "order": None}
    if decision["result"] == "ESCALATE":
        server.request_approval(cart_id=cart["id"], approved=approve(cart, decision))
    order = server.execute_payment(cart_id=cart["id"])
    receipt_ref = order["receipt"]["rail_reference"]
    server.advance_order(order["id"]); server.advance_order(order["id"])  # -> DELIVERED
    if do_return:
        order = server.create_return(order_id=order["id"], reason="changed my mind",
                                     returns_window_days=30)
    return {"intent": intent, "cart": cart, "decision": decision,
            "order": order, "receipt_reference": receipt_ref}


def main(prompt: str = typer.Argument(
        "Find me the best monitor under $300 that works with my MacBook, "
        "arrives tomorrow, and has good return terms. Buy it if you're confident."),
        do_return: bool = typer.Option(False, "--return")) -> None:
    def approve(cart: dict, decision: dict) -> bool:
        console.print(f"[yellow]APPROVAL NEEDED[/yellow] total={cart['total']['amount']} "
                      f"rail={cart['selected_rail']}")
        return typer.confirm("Approve this purchase?")
    result = run_flow(prompt, approve=approve, do_return=do_return, client=None)
    console.rule("[bold green]RESULT")
    if result["order"]:
        console.print(f"Order [bold]{result['order']['id']}[/bold] "
                      f"status=[green]{result['order']['status']}[/green]")
    else:
        console.print(f"[red]No purchase[/red] - policy {result['decision']['result']}")


if __name__ == "__main__":
    typer.run(main)
```

- [ ] **Step 4: Write `README.md`**

```markdown
# opayai-mcp

Agent commerce backbone: prompt -> signed, policy-checked purchase across pluggable
payment rails, with an approval gate and an audit trail. MCP server + CLI demo.

## Setup

    pip install -e ".[dev]"

## Run the demo

    python -m opayai.cli --return

## Run as an MCP server (stdio)

    python -m opayai.server

Register `opayai-mcp` -> command `python -m opayai.server` in any MCP host.

## Test

    pytest -v

## Flow

discover -> decide -> approve -> purchase -> track -> resolve. Every step publishes to
one event bus that is both the live view and the audit trail.
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (1 test)

- [ ] **Step 6: Run the full suite and the demo**

Run: `pytest -v`
Expected: PASS (all tests)
Run: `python -m opayai.cli --return`
Expected: event stream prints, ends with an order in `RETURN_REQUESTED`.

- [ ] **Step 7: Commit**

```bash
git add src/opayai/cli.py README.md tests/test_cli.py
git commit -m "feat: CLI host, live event renderer, end-to-end demo"
```

---

## Self-Review

**Spec coverage:**
- Agent-readable offers -> Task 3 (`offers.json`, `Offer`, `search_offers`). Covered.
- Preference-aware inputs (persona, conversations, orders) -> Task 3 loaders; persona used in front door (Task 10). Covered.
- Agent-ready payment flows (mandate backbone + pluggable rails) -> Tasks 5, 7, 9. Covered.
- Approval flows, spending limits, audit trails -> Tasks 4, 6, 9 (`request_approval` + escalate gate in `execute_payment`). Covered.
- Checkout proposals / receipts / what the user agreed to -> Cart mandate (Task 5), Receipt (Task 7), audit trail (Task 4/9). Covered.
- After purchase: tracking, exceptions, returns, feedback loop -> Task 8 (state machine, cancel, returns); `period_spent` accumulation (Task 9). Covered. (Persona mutation feedback loop is a listed stretch goal, not core.)
- Clear agent steps discover->decide->approve->purchase->track->resolve -> Task 11 `run_flow`. Covered.
- Generality (MCP + 2 rails) -> Tasks 7, 9. Covered.
- Hybrid LLM boundary -> Task 10 front door only; deterministic thereafter. Covered.

**Placeholder scan:** No TBD/TODO; every code step is complete and runnable. The only external-verify note is the Claude model id (Task 10), intentionally flagged.

**Type consistency:** `create_intent_mandate`/`propose_cart`/`evaluate_policy` signatures consistent across Tasks 5, 6, 9. `charge(cart, now)` consistent Tasks 7/9. `OrderStore` methods consistent Tasks 8/9/11. Event `publish(type, actor, payload, mandate_ref)` consistent everywhere. `Offer` fields consistent Tasks 1/3/6/11.

**Parallelization note:** After Tasks 1-2 (done together), A owns 4-6, B owns 7-8, C owns 3 then 9-11. C's Task 9 depends on A and B being merged; sequence C's integration (9-11) after A/B land, or stub against the frozen interfaces in the meantime.
