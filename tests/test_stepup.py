from opayai.signing import device_signer
from opayai.stepup import authorize, challenge


def test_authorize_succeeds_and_reports_device_key():
    res = authorize("cm_1", "289.00", "im_1")
    assert res["authorized"] is True
    assert res["device_pubkey"] == device_signer().verify_key_hex


def test_device_signature_is_bound_to_cart_and_amount():
    dev = device_signer()
    payload = challenge("cm_1", "289.00", "nonce1")
    sig = dev.sign_bytes(payload)
    assert dev.verify_bytes(payload, sig) is True
    # a signature for one purchase cannot be replayed for a different amount
    assert dev.verify_bytes(challenge("cm_1", "999.00", "nonce1"), sig) is False
    # nor for a different cart
    assert dev.verify_bytes(challenge("cm_2", "289.00", "nonce1"), sig) is False
