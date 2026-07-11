from __future__ import annotations
import json
from nacl.signing import SigningKey
from nacl.exceptions import BadSignatureError
from pydantic import BaseModel

_DEMO_SEED = bytes.fromhex(
    "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"
)
# Separate key = the user's registered device credential (passkey). In a real
# system this key lives on the device and never leaves it; here we simulate both
# the device (signs) and the relying party (verifies) for the human-present step-up.
_DEVICE_SEED = bytes.fromhex(
    "ffeeddccbbaa99887766554433221100ffeeddccbbaa99887766554433221100"
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

    def sign_bytes(self, payload: bytes) -> str:
        return self._sk.sign(payload).signature.hex()

    def verify_bytes(self, payload: bytes, signature_hex: str) -> bool:
        try:
            self._sk.verify_key.verify(payload, bytes.fromhex(signature_hex))
            return True
        except (BadSignatureError, ValueError):
            return False


_default: Signer | None = None
_device: Signer | None = None


def default_signer() -> Signer:
    global _default
    if _default is None:
        _default = Signer(SigningKey(_DEMO_SEED))
    return _default


def device_signer() -> Signer:
    """The user's registered device credential (passkey) for human-present step-up."""
    global _device
    if _device is None:
        _device = Signer(SigningKey(_DEVICE_SEED))
    return _device
