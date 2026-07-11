from __future__ import annotations

import base64
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .crypto import (canonical_json, challenge_b64, challenge_for, demo_assertion,
                     now_iso, verify_demo_assertion)
from .ledger import Ledger
from .models import (CartMandate, Constraints, EvidenceBundle, IntentMandate,
                     LineItem, Offer, PaymentMandate, Purchase, PurchaseException,
                     WebAuthnSigning)
from .policy import PolicyBlock, check_policy
from .rails import BlikLiteRail, CardSptStub, RailNotImplemented, UsdcStub, lan_ip
from .seed import OFFERS
from .store import Store

from webauthn import (generate_authentication_options, generate_registration_options,
                      options_to_json, verify_authentication_response,
                      verify_registration_response)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.structs import (AuthenticatorAttachment,
                                     AuthenticatorSelectionCriteria,
                                     PublicKeyCredentialDescriptor,
                                     ResidentKeyRequirement,
                                     UserVerificationRequirement)


class OPayAIService:
    def __init__(self, state_dir: Path):
        self.store = Store(state_dir / "state.json")
        self.ledger = Ledger(state_dir / "ledger.jsonl")
        self.offers = {offer.sku: offer for offer in OFFERS}
        self.rails = {"blik_lite": BlikLiteRail(), "card_spt_stub": CardSptStub(), "usdc_stub": UsdcStub()}
        self.auth_mode = os.getenv("AUTH_MODE", "demo_key").lower()
        if self.auth_mode not in {"demo_key", "webauthn"}:
            raise ValueError("AUTH_MODE must be demo_key or webauthn")
        self.rp_id = os.getenv("WEBAUTHN_RP_ID", "localhost")
        configured_origin = os.getenv("WEBAUTHN_ORIGIN")
        self.expected_origin = configured_origin or ["http://localhost:5173", "http://localhost:8000"]
        self._payment_lock = threading.Lock()

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
                           expiry=OPayAIService._expiry())

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
        if self.auth_mode == "demo_key":
            return {"auth_mode": "demo_key", "challenge": challenge_b64(body), "context_id": context_id,
                    "context_type": context_type, "body": body, "user_verification": "required"}
        if not self.store.webauthn_credentials:
            return {"auth_mode": "webauthn", "registration_required": True,
                    "context_id": context_id, "context_type": context_type}
        descriptors = [PublicKeyCredentialDescriptor(id=self._b64decode(value["credential_id"]))
                       for value in self.store.webauthn_credentials.values()]
        options = generate_authentication_options(
            rp_id=self.rp_id, challenge=challenge_for(body), allow_credentials=descriptors,
            user_verification=UserVerificationRequirement.REQUIRED)
        return {"auth_mode": "webauthn", "registration_required": False,
                "options": json.loads(options_to_json(options)), "context_id": context_id,
                "context_type": context_type, "body": body}

    def registration_options(self) -> dict[str, Any]:
        if self.auth_mode == "demo_key":
            return {"auth_mode": "demo_key", "credential_id": "demo-device",
                    "message": "Demo key is active; no platform enrollment is needed."}
        options = generate_registration_options(
            rp_id=self.rp_id, rp_name="OPayAI", user_name="user_demo",
            user_id=b"user_demo", user_display_name="OPayAI Demo User",
            authenticator_selection=AuthenticatorSelectionCriteria(
                authenticator_attachment=AuthenticatorAttachment.PLATFORM,
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED),
            exclude_credentials=[PublicKeyCredentialDescriptor(id=self._b64decode(value["credential_id"]))
                                 for value in self.store.webauthn_credentials.values()])
        self.store.registration_challenge = base64.b64encode(options.challenge).decode()
        return {"auth_mode": "webauthn", "options": json.loads(options_to_json(options))}

    def verify_registration(self, credential: dict[str, Any]) -> dict[str, Any]:
        if self.auth_mode == "demo_key":
            return {"verified": True, "credential_id": "demo-device", "auth_mode": "demo_key"}
        if not self.store.registration_challenge:
            raise ValueError("Registration challenge expired; request new options.")
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=base64.b64decode(self.store.registration_challenge),
            expected_rp_id=self.rp_id, expected_origin=self.expected_origin,
            require_user_verification=True)
        credential_id = bytes_to_base64url(verification.credential_id)
        self.store.webauthn_credentials[credential_id] = {
            "credential_id": credential_id,
            "public_key_b64": base64.b64encode(verification.credential_public_key).decode(),
            "sign_count": verification.sign_count,
            "aaguid": verification.aaguid,
        }
        self.store.registration_challenge = None
        self.store.save()
        self._event("user", "webauthn_registered", credential_id=credential_id,
                    user_verified=verification.user_verified)
        return {"verified": True, "credential_id": credential_id, "auth_mode": "webauthn"}

    def verify_signing(self, context_id: str, context_type: str, assertion: dict[str, Any]) -> WebAuthnSigning:
        key = f"{context_type}:{context_id}"
        context = self.store.signing_contexts.get(key)
        if not context:
            raise ValueError("Signing context expired; request a new challenge.")
        body = context["body"]
        signed_at = now_iso()
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        body_hash = challenge_b64(body)
        if self.auth_mode == "demo_key":
            supplied = assertion.get("assertion_b64") or demo_assertion(body)
            verified = verify_demo_assertion(body, supplied)
            signing = WebAuthnSigning(
                method="demo_key", credential_id=assertion.get("credential_id", "demo-device"),
                assertion_b64=supplied, body_hash=body_hash, verified=verified,
                signed_at=signed_at, expires_at=expires_at)
        else:
            credential_id = assertion.get("id", "")
            stored = self.store.webauthn_credentials.get(credential_id)
            if not stored:
                raise ValueError("Unknown WebAuthn credential.")
            verification = verify_authentication_response(
                credential=assertion, expected_challenge=challenge_for(body),
                expected_rp_id=self.rp_id, expected_origin=self.expected_origin,
                credential_public_key=base64.b64decode(stored["public_key_b64"]),
                credential_current_sign_count=stored["sign_count"],
                require_user_verification=True)
            stored["sign_count"] = verification.new_sign_count
            supplied = base64.b64encode(canonical_json(assertion).encode()).decode()
            verified = verification.user_verified
            signing = WebAuthnSigning(
                method="webauthn", credential_id=credential_id,
                assertion_b64=supplied, body_hash=body_hash, verified=verified,
                signed_at=signed_at, expires_at=expires_at)
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
            self._event("merchant", "notification", purchase.id, message="Return approved. Shipping code: OPAY-RETURN-482913")
        else:
            raise ValueError("Unsupported signing context.")
        self.store.signing_contexts.pop(key, None)
        self.store.save()
        return signing

    @staticmethod
    def _b64decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

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
        self._event("system", "notification", purchase.id, message="A new purchase request is waiting for your approval.")
        self.store.save()
        return purchase

    def select_rail(self, purchase_id: str, rail: str, base_url: str) -> dict[str, Any]:
        purchase = self.store.purchases[purchase_id]
        offer = self._assert_current_cart_authorization(purchase)
        intent = self.store.intents[purchase.intent_id]
        assert purchase.cart
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

    def blik_decision(self, session_id: str, decision: str, channel: str = "phone_page") -> Purchase:
        with self._payment_lock:
            rail = self.rails["blik_lite"]
            purchase = next(
                p for p in self.store.purchases.values()
                if p.payment and p.payment.rail_ref == session_id)
            assert purchase.payment and purchase.cart
            payment = purchase.payment
            if payment.status != "pending":
                raise PolicyBlock("payment_not_pending", "This BLIK session is no longer pending.")
            if decision == "confirm":
                offer = self._assert_current_cart_authorization(purchase)
                intent = self.store.intents[purchase.intent_id]
                self._policy(intent, "payment_confirm", purchase.id, offer,
                             purchase.cart.totals["total"], payment.rail)
            session = rail.decide(session_id, decision)
            if session.status == "confirmed":
                payment.status = "succeeded"
                payment.attempts.append({"ts": now_iso(), "result": "confirmed", "detail": f"BLIK confirmation via {channel}"})
                purchase.status, purchase.order_status = "tracking", "paid"
                purchase.order = {"id": self.store.next_id("ord"), "status": "paid", "line_items_shipped": [item.model_dump() for item in purchase.cart.line_items]}
                intent = self.store.intents[purchase.intent_id]
                intent.spent_total += payment.amount
                offer.stock -= purchase.cart.line_items[0].qty
                self._event("rail", "payment_confirmed", purchase.id, payment_id=payment.id,
                            session_id=session_id, channel=channel)
                self._event("merchant", "status_change", purchase.id, order_status="paid")
                self._event("merchant", "notification", purchase.id, message="BLIK payment confirmed. Order accepted.")
            else:
                payment.status = "failed"
                payment.attempts.append({"ts": now_iso(), "result": session.status, "detail": "BLIK phone decision"})
                purchase.status, purchase.order_status = "await_retry", "payment_failed"
                self._event("rail", "payment_failed", purchase.id, payment_id=payment.id, result=session.status)
                self._event("system", "notification", purchase.id, message="Payment declined. Would you like to try again?")
            self.store.save()
            return purchase

    def _assert_current_cart_authorization(self, purchase: Purchase, require_stock: bool = True) -> Offer:
        if not purchase.cart or not purchase.cart.signing or not purchase.cart.signing.verified:
            raise PolicyBlock("cart_not_signed", "A human must sign this exact cart before payment.")
        signing = purchase.cart.signing
        if datetime.fromisoformat(signing.expires_at) < datetime.now(timezone.utc):
            raise PolicyBlock("cart_authorization_expired", "The exact-cart authorization has expired.")
        body = purchase.cart.model_dump(mode="json", exclude={"signing"})
        if signing.body_hash != challenge_b64(body):
            raise PolicyBlock("cart_authorization_mismatch", "The signed cart changed after authorization.")
        if purchase.cart.totals != purchase.proposal.get("totals"):
            raise PolicyBlock("proposal_drift", "Signed cart totals differ from the checkout proposal.")
        if len(purchase.cart.line_items) != 1:
            raise PolicyBlock("cart_integrity", "The demo cart must contain exactly one line item.")
        item = purchase.cart.line_items[0]
        offer = self._find_offer(item.sku)
        expected_total = item.unit_price * item.qty
        if item.unit_price != offer.price or purchase.cart.totals["total"] != expected_total:
            raise PolicyBlock("price_drift", "The signed item price no longer matches the merchant offer.")
        if require_stock and offer.stock < item.qty:
            raise PolicyBlock("out_of_stock", "Insufficient stock at payment time.")
        return offer

    def confirm_blik_in_chat(self, purchase_id: str, code: str) -> Purchase:
        if len(code) != 6 or not code.isdigit():
            raise ValueError("BLIK code must contain exactly six digits.")
        purchase = self.store.purchases[purchase_id]
        if not purchase.payment or purchase.payment.status != "pending":
            raise PolicyBlock("payment_not_pending", "There is no pending BLIK session to confirm.")
        if purchase.payment.rail != "blik_lite":
            raise PolicyBlock("rail_not_allowed", "Only BLIK Lite supports an in-chat code prompt.")
        self._event("user", "blik_code_entered", purchase.id,
                    session_id=purchase.payment.rail_ref, code_hint=f"••••{code[-2:]}")
        return self.blik_decision(purchase.payment.rail_ref, "confirm", channel="in_chat_prompt")

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

    def merchant_confirm_checkout(self, purchase_id: str) -> dict[str, Any]:
        purchase = self.store.purchases[purchase_id]
        intent = self.store.intents[purchase.intent_id]
        offer = self._assert_current_cart_authorization(purchase, require_stock=False)
        if not purchase.payment or purchase.payment.status != "succeeded":
            raise PolicyBlock("payment_not_succeeded", "Merchant requires a succeeded payment mandate.")
        # Budget was consumed exactly once when BLIK succeeded; confirmation
        # re-checks category/rail without charging the cumulative limit again.
        self._policy(intent, "merchant_checkout_confirm", purchase.id, offer,
                     rail=purchase.payment.rail)
        if not purchase.order:
            raise ValueError("Payment succeeded but no merchant order was created.")
        return {"proposal_id": purchase.id, "order": purchase.order,
                "cart_signature_verified": True, "payment_verified": True}

    def merchant_create_return(self, purchase_id: str, reason: str) -> dict[str, Any]:
        purchase = self.store.purchases[purchase_id]
        intent = self.store.intents[purchase.intent_id]
        signing = (purchase.resolution or {}).get("signing")
        if not signing or not signing.get("verified"):
            raise PolicyBlock("resolution_not_signed", "A human must sign the resolution before return creation.")
        self._policy(intent, "merchant_return", purchase.id)
        if purchase.order_status not in {"return_requested", "return_in_transit"}:
            raise PolicyBlock("return_not_available", "Order is not in an approved return state.")
        return {"return_id": f"ret_{purchase.id}", "reason": reason,
                "locker_dropoff_code": "OPAY-RETURN-482913"}

    def merchant_refund(self, purchase_id: str) -> dict[str, Any]:
        purchase = self.store.purchases[purchase_id]
        intent = self.store.intents[purchase.intent_id]
        self._policy(intent, "merchant_refund", purchase.id)
        if purchase.order_status != "return_in_transit":
            raise PolicyBlock("refund_not_available", "Refund requires a returned parcel in transit.")
        return self._issue_refund(purchase)

    def advance(self, order_id: str) -> Purchase:
        purchase = next(p for p in self.store.purchases.values() if p.order and p.order["id"] == order_id)
        if purchase.order_status == "paid":
            purchase.order_status, purchase.status, purchase.order["status"] = "shipped", "tracking", "shipped"
            self._event("merchant", "status_change", purchase.id, order_status="shipped")
        elif purchase.order_status == "shipped":
            purchase.order_status, purchase.order["status"] = "in_paczkomat", "in_paczkomat"
            self._event("merchant", "status_change", purchase.id, order_status="in_paczkomat", locker_id="WAW117M", pickup_code="482913")
            self._event("merchant", "notification", purchase.id, message="Parcel locker WAW117M · pickup code 482913")
        elif purchase.order_status == "in_paczkomat":
            purchase.order_status, purchase.order["status"] = "picked_up", "picked_up"
            self._event("user", "status_change", purchase.id, order_status="picked_up")
            self._verify_delivery(purchase)
        elif purchase.order_status == "return_requested":
            purchase.order_status, purchase.status = "return_in_transit", "resolving"
            self._event("merchant", "status_change", purchase.id, order_status="return_in_transit")
        elif purchase.order_status == "return_in_transit":
            self._issue_refund(purchase)
        else:
            raise ValueError(f"No demo transition from {purchase.order_status}")
        self.store.save()
        return purchase

    def _issue_refund(self, purchase: Purchase) -> dict[str, Any]:
        assert purchase.payment and purchase.order
        refund = self.rails["blik_lite"].refund(purchase.payment.id)
        purchase.payment.status = "refunded"
        purchase.order_status, purchase.status = "closed_refunded", "closed"
        purchase.order["status"] = "closed_refunded"
        if purchase.exception:
            purchase.exception.resolution_status = "resolved"
        self._event("rail", "refund_issued", purchase.id, **refund, amount=purchase.payment.amount)
        self.store.save()
        return {**refund, "amount": purchase.payment.amount, "currency": "PLN"}

    def _verify_delivery(self, purchase: Purchase) -> None:
        assert purchase.cart and purchase.order
        expected = [item.model_dump(mode="json") for item in purchase.cart.line_items]
        observed = purchase.order["line_items_shipped"]
        if expected != observed:
            exception = PurchaseException(id=self.store.next_id("exc"), order_id=purchase.order["id"], type="ITEM_MISMATCH",
                                          evidence={"expected": expected, "observed": observed}, proposed_resolution="full_return")
            purchase.exception, purchase.order_status, purchase.status = exception, "exception", "resolution_proposed"
            self._event("system", "exception_detected", purchase.id, exception_type="ITEM_MISMATCH", expected=expected, observed=observed)
            self._event("system", "notification", purchase.id, message="Wrong item detected. A full return is recommended.")
        else:
            purchase.status = "verifying"
            self._event("system", "delivery_verified", purchase.id, result="match")
            self._event("system", "notification", purchase.id, message="The product matches your mandate. Would you like to keep it?")

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

    def inject_fault(self, target_id: str, type_: str) -> None:
        purchase = self.store.purchases.get(target_id)
        if purchase is None:
            purchase = next(p for p in self.store.purchases.values()
                            if p.order and p.order["id"] == target_id)
        if type_ == "decline_payment":
            if not purchase.payment:
                raise ValueError("Select BLIK before arming a payment decline.")
            self.rails["blik_lite"].sessions[purchase.payment.rail_ref].decline_once = True
        elif type_ == "wrong_item":
            assert purchase.order
            purchase.order["line_items_shipped"] = [{"sku": "MON-WRONG-24", "title": "Wrong product", "qty": 1, "unit_price": 1}]
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
