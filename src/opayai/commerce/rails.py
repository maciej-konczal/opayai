from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Literal, Protocol


class RailNotImplemented(Exception):
    pass


@dataclass
class RailSession:
    id: str
    amount: int
    status: Literal["pending", "confirmed", "rejected", "declined"] = "pending"
    decline_once: bool = False


class PaymentRail(Protocol):
    id: str
    def init(self, cart_total: int) -> RailSession: ...
    def status(self, session_id: str) -> str: ...
    def refund(self, payment_id: str) -> dict: ...


class BlikLiteRail:
    id = "blik_lite"

    def __init__(self):
        self.sessions: dict[str, RailSession] = {}
        self.counter = 0

    def init(self, cart_total: int) -> RailSession:
        self.counter += 1
        session = RailSession(id=f"blik_{self.counter:04d}", amount=cart_total)
        self.sessions[session.id] = session
        return session

    def status(self, session_id: str) -> str:
        return self.sessions[session_id].status

    def decide(self, session_id: str, decision: str) -> RailSession:
        session = self.sessions[session_id]
        if decision == "confirm" and session.decline_once:
            session.decline_once = False
            session.status = "declined"
        elif decision == "confirm":
            session.status = "confirmed"
        else:
            session.status = "rejected"
        return session

    def refund(self, payment_id: str) -> dict:
        return {"refund_id": f"ref_{payment_id}", "status": "issued"}


class CardSptStub:
    id = "card_spt_stub"
    def init(self, cart_total: int) -> RailSession:
        raise RailNotImplemented("Card is an adapter slot in this demo.")
    def status(self, session_id: str) -> str: raise RailNotImplemented("Card is not implemented.")
    def refund(self, payment_id: str) -> dict: raise RailNotImplemented("Card is not implemented.")


class UsdcStub(CardSptStub):
    id = "usdc_stub"


def lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()
