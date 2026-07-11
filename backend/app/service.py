from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .crypto import challenge_b64, demo_assertion, now_iso, verify_demo_assertion
from .ledger import Ledger
from .models import (CartMandate, Constraints, EvidenceBundle, IntentMandate,
                     LineItem, Offer, PaymentMandate, Purchase, PurchaseException,
                     WebAuthnSigning)
from .policy import PolicyBlock, check_policy
from .rails import BlikLiteRail, CardSptStub, RailNotImplemented, UsdcStub, lan_ip
from .seed import OFFERS
from .store import Store


class MandateLoopService:
    def __init__(self, state_dir: Path):
        self.store = Store(state_dir / "state.json")
        self.ledger = Ledger(state_dir / "ledger.jsonl")
        self.offers = {offer.sku: offer for offer in OFFERS}
        self.rails = {"blik_lite": BlikLiteRail(), "card_spt_stub": CardSptStub(), "usdc_stub": UsdcStub()}

    def _event(self, actor: str, type_: str, purchase_id: str | None = None, **payload: Any) -> None:
        if purchase_id:
            payload["purchase_id"] = purchase_id
        self.ledger.append(actor, type_, payload)

    def _policy(self, intent: IntentMandate, action: str, purchase_id: str,
                offer: Offer | None = None, amount: int = 0, rail: str | None = None) -> None:
        ok, clause, detail = check_policy(intent, action, offer, amount, rail)
        self._event("policy", "policy_pass" if ok else "policy_block", purchase_id,
                    clause=clause, action=action, detail=detail)
        if not ok:
            raise PolicyBlock(clause, detail)

    def _find_offer(self, sku: str) -> Offer:
        if sku not in self.offers:
            raise ValueError("Unknown SKU")
        return self.offers[sku]

    @staticmethod
    def _expiry(hours: int = 24) -> str:
        return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()

    @staticmethod
    def parse_intent(text: str) -> Constraints:
        """Deliberately small, deterministic form fallback; no offer selection."""
        normalized = text.lower()
        categories = ["winter_tires"] if any(token in normalized for token in ("opon", "tire", "winter")) else ["monitors"]
        amount = 160000 if "1600" in normalized else 120000 if "1200" in normalized else 150000
        return_days = 14
        for candidate in (30, 14, 7):
            if str(candidate) in normalized and ("zwrot" in normalized or "return" in normalized):
                return_days = candidate
                break
        return Constraints(max_total=amount, categories=categories, min_return_window_days=return_days,
                           expiry=MandateLoopService._expiry())

    def draft_intent(self, description: str, agent_id: str = "webapp") -> IntentMandate:
        intent = IntentMandate(id=self.store.next_id("im"), agent_id=agent_id,
                               description=description, constraints=self.parse_intent(description))
        self.store.intents[intent.id] = intent
        self._event("agent", "intent_drafted", intent_id=intent.id, description=description)
        self.store.save()
        return intent

    def create_intent(self, description: str, constraints: Constraints, agent_id: str = "webapp") -> IntentMandate:
        intent = IntentMandate(id=self.store.next_id("im"), agent_id=agent_id,
                               description=description, constraints=constraints)
        self.store.intents[intent.id] = intent
        self._event("user", "intent_drafted", intent_id=intent.id, description=description)
        self.store.save()
        return intent

    def signing_options(self, context_id: str, context_type: str) -> dict[str, Any]:
        body, intent_id, purchase_id = self._signing_body(context_id, context_type)
        context = {"body": body, "context_type": context_type, "intent_id": intent_id, "purchase_id": purchase_id}
        self.store.signing_contexts[f"{context_type}:{context_id}"] = context
        return {"auth_mode": "demo_key", "challenge": challenge_b64(body), "context_id": context_id,
                "context_type": context_type, "body": body, "user_verification": "required"}

    def verify_signing(self, context_id: str, context_type: str, assertion: dict[str, Any]) -> WebAuthnSigning:
        key = f"{context_type}:{context_id}"
        context = self.store.signing_contexts.get(key)
        if not context:
            raise ValueError("Signing context expired; request a new challenge.")
        body = context["body"]
        supplied = assertion.get("assertion_b64") or demo_assertion(body)
        verified = verify_demo_assertion(body, supplied)
        signing = WebAuthnSigning(credential_id=assertion.get("credential_id", "demo-device"),
                                  assertion_b64=supplied, verified=verified, signed_at=now_iso())
        if not verified:
            raise ValueError("Approval assertion did not verify.")
        if context_type == "intent":
            intent = self.store.intents[context_id]
            intent.signing, intent.status = signing, "open"
            self._event("user", "webauthn_signed", intent_id=intent.id, context="intent", verified=True)
        elif context_type == "cart":
            purchase = self.store.purchases[context["purchase_id"]]
            assert purchase.cart
            purchase.cart.signing, purchase.status = signing, "cart_signed"
            self._event("user", "webauthn_signed", purchase.id, context="cart", verified=True)
        elif context_type == "resolution":
            purchase = self.store.purchases[context["purchase_id"]]
            if not purchase.exception:
                raise ValueError("No pending resolution to approve.")
            purchase.resolution = {"signing": signing.model_dump(mode="json"), "approved_at": now_iso()}
            purchase.exception.resolution_status = "approved"
            purchase.status, purchase.order_status = "return_requested", "return_requested"
            self._event("user", "webauthn_signed", purchase.id, context="resolution", verified=True)
            self._event("merchant", "notification", purchase.id, message="Zwrot zaakceptowany. Kod nadania: ML-RETURN-482913")
        else:
            raise ValueError("Unsupported signing context.")
        self.store.save()
        return signing

    def _signing_body(self, context_id: str, context_type: str) -> tuple[dict[str, Any], str, str | None]:
        if context_type == "intent":
            intent = self.store.intents[context_id]
            return intent.constraints.model_dump(mode="json"), intent.id, None
        if context_type == "cart":
            purchase = self.store.purchases[context_id]
            if not purchase.cart:
                raise ValueError("Cart proposal does not exist.")
            return purchase.cart.model_dump(mode="json", exclude={"signing"}), purchase.intent_id, purchase.id
        if context_type == "resolution":
            purchase = self.store.purchases[context_id]
            body = {"purchase_id": purchase.id, "exception": purchase.exception.model_dump(mode="json") if purchase.exception else None,
                    "resolution": "full_return"}
            return body, purchase.intent_id, purchase.id
        raise ValueError("Unsupported signing context.")

    def search_products(self, query: str = "", category: str | None = None,
                        max_price: int | None = None, intent_id: str | None = None) -> dict[str, Any]:
        intent = self.store.intents.get(intent_id) if intent_id else self._latest_open_intent()
        visible, filtered = [], []
        for offer in self.offers.values():
            if category and offer.category != category:
                continue
            if query and query.lower() not in (offer.title + " " + offer.category + " " + str(offer.attributes)).lower():
                continue
            if max_price is not None and offer.price > max_price:
                continue
            clause = None
            if intent:
                allowed, clause_id, _ = check_policy(intent, "search", offer, offer.price)
                if not allowed:
                    clause = clause_id
            if offer.stock <= 0:
                clause = clause or "out_of_stock"
            if clause:
                filtered.append({"offer": offer.model_dump(mode="json"), "violated_clause": clause})
            else:
                visible.append(offer.model_dump(mode="json"))
        return {"offers": visible, "filtered_out": filtered}

    def request_purchase(self, intent_id: str, sku: str, qty: int, agent_id: str, client_info: str = "") -> Purchase:
        intent = self.store.intents[intent_id]
        offer = self._find_offer(sku)
        purchase_id = self.store.next_id("pur")
        amount = offer.price * qty
        self._policy(intent, "checkout_proposal", purchase_id, offer, amount)
        if offer.stock < qty:
            self._event("policy", "policy_block", purchase_id, clause="out_of_stock", action="checkout_proposal", detail="Insufficient stock")
            raise PolicyBlock("out_of_stock", "Insufficient stock")
        item = LineItem(sku=offer.sku, title=offer.title, qty=qty, unit_price=offer.price)
        delivery = (datetime.now(timezone.utc).date() + timedelta(days=offer.delivery_estimate_days)).isoformat()
        cart = CartMandate(id=self.store.next_id("cm"), parent_intent_id=intent.id, line_items=[item],
                           totals={"subtotal": amount, "tax": 0, "shipping": 0, "total": amount},
                           delivery_method=offer.delivery_method, delivery_promise=delivery,
                           return_policy_snapshot=dict(offer.return_policy))
        proposal = {"sku": sku, "qty": qty, "totals": cart.totals, "delivery_method": cart.delivery_method,
                    "delivery_promise": delivery, "return_policy": cart.return_policy_snapshot,
                    "accepted_rails": intent.constraints.allowed_rails}
        purchase = Purchase(id=purchase_id, intent_id=intent.id, status="awaiting_human_authorization",
                            proposal=proposal, cart=cart,
                            agent_attribution={"agent_id": agent_id, "client_info": client_info or agent_id})
        self.store.purchases[purchase.id] = purchase
        self._event("agent", "proposal_ready", purchase.id, intent_id=intent.id, sku=sku, total=amount)
        self._event("system", "notification", purchase.id, message="Nowa prośba o zakup czeka na zatwierdzenie w panelu.")
        self.store.save()
        return purchase

    def select_rail(self, purchase_id: str, rail: str, base_url: str) -> dict[str, Any]:
        purchase = self.store.purchases[purchase_id]
        if not purchase.cart or not purchase.cart.signing or not purchase.cart.signing.verified:
            raise PolicyBlock("cart_not_signed", "A human must sign this exact cart before payment.")
        intent = self.store.intents[purchase.intent_id]
        offer = self._find_offer(purchase.cart.line_items[0].sku)
        self._policy(intent, "payment_init", purchase.id, offer, purchase.cart.totals["total"], rail)
        try:
            session = self.rails[rail].init(purchase.cart.totals["total"])
        except RailNotImplemented:
            raise
        payment = PaymentMandate(id=self.store.next_id("pm"), cart_mandate_id=purchase.cart.id, rail=rail,
                                 rail_ref=session.id, amount=session.amount)
        purchase.payment, purchase.status, purchase.order_status = payment, "payment_pending", "payment_pending"
        self._event("rail", "payment_attempt", purchase.id, payment_id=payment.id, session_id=session.id, result="pending")
        self.store.save()
        return {"payment": payment.model_dump(mode="json"), "pay_url": f"{base_url}/pay/blik/{session.id}"}

    def blik_decision(self, session_id: str, decision: str) -> Purchase:
        rail = self.rails["blik_lite"]
        session = rail.decide(session_id, decision)
        purchase = next(p for p in self.store.purchases.values() if p.payment and p.payment.rail_ref == session_id)
        assert purchase.payment and purchase.cart
        payment = purchase.payment
        if session.status == "confirmed":
            payment.status = "succeeded"
            payment.attempts.append({"ts": now_iso(), "result": "confirmed", "detail": "BLIK confirmation on phone"})
            purchase.status, purchase.order_status = "tracking", "paid"
            purchase.order = {"id": self.store.next_id("ord"), "status": "paid", "line_items_shipped": [item.model_dump() for item in purchase.cart.line_items]}
            intent = self.store.intents[purchase.intent_id]
            intent.spent_total += payment.amount
            self._event("rail", "payment_confirmed", purchase.id, payment_id=payment.id, session_id=session_id)
            self._event("merchant", "status_change", purchase.id, order_status="paid")
            self._event("merchant", "notification", purchase.id, message="Płatność BLIK potwierdzona. Zamówienie przyjęte.")
        else:
            payment.status = "failed"
            payment.attempts.append({"ts": now_iso(), "result": session.status, "detail": "BLIK phone decision"})
            purchase.status, purchase.order_status = "await_retry", "payment_failed"
            self._event("rail", "payment_failed", purchase.id, payment_id=payment.id, result=session.status)
            self._event("system", "notification", purchase.id, message="Płatność odrzucona — spróbować ponownie?")
        self.store.save()
        return purchase

    def retry_payment(self, purchase_id: str, base_url: str) -> dict[str, Any]:
        purchase = self.store.purchases[purchase_id]
        if not purchase.payment or purchase.payment.status != "failed":
            raise ValueError("Only a failed payment can be retried.")
        previous = purchase.payment
        session = self.rails["blik_lite"].init(previous.amount)
        previous.rail_ref, previous.status = session.id, "pending"
        purchase.status, purchase.order_status = "payment_pending", "payment_pending"
        self._event("rail", "payment_attempt", purchase.id, payment_id=previous.id, session_id=session.id, result="retry_pending")
        self.store.save()
        return {"payment": previous.model_dump(mode="json"), "pay_url": f"{base_url}/pay/blik/{session.id}"}

    def advance(self, order_id: str) -> Purchase:
        purchase = next(p for p in self.store.purchases.values() if p.order and p.order["id"] == order_id)
        if purchase.order_status == "paid":
            purchase.order_status, purchase.status, purchase.order["status"] = "shipped", "tracking", "shipped"
            self._event("merchant", "status_change", purchase.id, order_status="shipped")
        elif purchase.order_status == "shipped":
            purchase.order_status, purchase.order["status"] = "in_paczkomat", "in_paczkomat"
            self._event("merchant", "status_change", purchase.id, order_status="in_paczkomat", locker_id="WAW117M", pickup_code="482913")
            self._event("merchant", "notification", purchase.id, message="Paczkomat WAW117M · kod odbioru 482913")
        elif purchase.order_status == "in_paczkomat":
            purchase.order_status, purchase.order["status"] = "picked_up", "picked_up"
            self._event("user", "status_change", purchase.id, order_status="picked_up")
            self._verify_delivery(purchase)
        elif purchase.order_status == "return_requested":
            purchase.order_status, purchase.status = "return_in_transit", "resolving"
            self._event("merchant", "status_change", purchase.id, order_status="return_in_transit")
        elif purchase.order_status == "return_in_transit":
            assert purchase.payment
            refund = self.rails["blik_lite"].refund(purchase.payment.id)
            purchase.payment.status = "refunded"
            purchase.order_status, purchase.status = "closed_refunded", "closed"
            purchase.order["status"] = "closed_refunded"
            if purchase.exception:
                purchase.exception.resolution_status = "resolved"
            self._event("rail", "refund_issued", purchase.id, **refund, amount=purchase.payment.amount)
        else:
            raise ValueError(f"No demo transition from {purchase.order_status}")
        self.store.save()
        return purchase

    def _verify_delivery(self, purchase: Purchase) -> None:
        assert purchase.cart and purchase.order
        expected = [item.model_dump(mode="json") for item in purchase.cart.line_items]
        observed = purchase.order["line_items_shipped"]
        if expected != observed:
            exception = PurchaseException(id=self.store.next_id("exc"), order_id=purchase.order["id"], type="ITEM_MISMATCH",
                                          evidence={"expected": expected, "observed": observed}, proposed_resolution="full_return")
            purchase.exception, purchase.order_status, purchase.status = exception, "exception", "resolution_proposed"
            self._event("system", "exception_detected", purchase.id, exception_type="ITEM_MISMATCH", expected=expected, observed=observed)
            self._event("system", "notification", purchase.id, message="Wykryto niezgodny produkt. Proponujemy pełny zwrot.")
        else:
            purchase.status = "verifying"
            self._event("system", "delivery_verified", purchase.id, result="match")
            self._event("system", "notification", purchase.id, message="Produkt zgodny z mandatem. Zostawiasz produkt?")

    def request_return(self, purchase_id: str, reason: str) -> Purchase:
        purchase = self.store.purchases[purchase_id]
        if not purchase.exception and purchase.order_status != "picked_up":
            raise PolicyBlock("return_not_available", "Return is available after pickup or for a detected exception.")
        intent = self.store.intents[purchase.intent_id]
        self._policy(intent, "return_resolution", purchase.id)
        purchase.status = "awaiting_human_authorization"
        purchase.resolution = {"reason": reason, "proposed_resolution": "full_return"}
        self._event("agent", "resolution_proposed", purchase.id, reason=reason, resolution="full_return")
        self.store.save()
        return purchase

    def approve_resolution(self, purchase_id: str) -> dict[str, Any]:
        purchase = self.store.purchases[purchase_id]
        if not purchase.exception:
            expected = purchase.cart.line_items if purchase.cart else []
            purchase.exception = PurchaseException(id=self.store.next_id("exc"), order_id=purchase.order["id"] if purchase.order else "", type="USER_REPORTED",
                                                   evidence={"expected": [item.model_dump() for item in expected], "observed": []}, proposed_resolution="full_return")
        return self.signing_options(purchase_id, "resolution")

    def confirm_satisfied(self, purchase_id: str) -> Purchase:
        purchase = self.store.purchases[purchase_id]
        if purchase.order_status != "picked_up" or purchase.exception:
            raise ValueError("Cannot accept an unresolved purchase.")
        purchase.status, purchase.order_status = "closed", "closed_accepted"
        intent = self.store.intents[purchase.intent_id]
        intent.status = "fulfilled"
        self._event("user", "status_change", purchase.id, order_status="closed_accepted")
        self.store.save()
        return purchase

    def revoke_intent(self, intent_id: str) -> IntentMandate:
        intent = self.store.intents[intent_id]
        intent.status = "revoked"
        self._event("user", "revoked", intent_id=intent.id)
        self.store.save()
        return intent

    def inject_fault(self, order_id: str, type_: str) -> None:
        purchase = next(p for p in self.store.purchases.values() if p.order and p.order["id"] == order_id)
        if type_ == "decline_payment":
            if not purchase.payment:
                raise ValueError("Select BLIK before arming a payment decline.")
            self.rails["blik_lite"].sessions[purchase.payment.rail_ref].decline_once = True
        elif type_ == "wrong_item":
            assert purchase.order
            purchase.order["line_items_shipped"] = [{"sku": "MON-WRONG-24", "title": "Inny produkt", "qty": 1, "unit_price": 1}]
        else:
            raise ValueError("Unknown demo fault")
        self._event("system", "demo_fault_armed", purchase.id, fault=type_)
        self.store.save()

    def evidence(self, purchase_id: str) -> EvidenceBundle:
        purchase = self.store.purchases[purchase_id]
        events = self.ledger.for_purchase(purchase_id)
        return EvidenceBundle(bundle_id=self.store.next_id("evb"), generated_at=now_iso(),
                              intent_mandate=self.store.intents[purchase.intent_id], cart_mandate=purchase.cart,
                              payment_mandate=purchase.payment, order_event_log=events,
                              hash_chain_valid=self.ledger.verify(), exception=purchase.exception,
                              diff=purchase.exception.evidence if purchase.exception else None,
                              resolution_actions=[event for event in events if event.type in {"resolution_proposed", "refund_issued", "webauthn_signed"}],
                              agent_attribution=purchase.agent_attribution)

    def _latest_open_intent(self) -> IntentMandate | None:
        candidates = [intent for intent in self.store.intents.values() if intent.status == "open"]
        return candidates[-1] if candidates else None
