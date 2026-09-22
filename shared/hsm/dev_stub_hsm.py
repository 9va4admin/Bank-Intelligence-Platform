"""
DevStubHSMSigner — DEV/TEST STAND-IN, NOT A REAL HSM.

No Vault Transit key is provisioned in the dev stack, so VaultTransitSigner.from_env() fails and
_build_hsm_signer() falls back to None — which crashed NGCHSigner.sign_micr()/sign_image() with
'NoneType' object has no attribute 'sign'. This gives the same sign(data: bytes) -> bytes contract
(256-byte output, matching FIPS 140-2 Level 3 RSA-2048 PKCS#1v15 raw signature length) with a
deterministic, non-cryptographic HMAC in place of a real signature, so a decided cheque can complete
end to end in dev. Refuses to run unless ASTRA_ENV=development, so it can never front a real bank.
"""
import hashlib
import hmac
import os

_DEV_KEY = b"astra-dev-hsm-stub-key-not-for-production-use"


class DevStubHSMSigner:
    def __init__(self) -> None:
        if os.environ.get("ASTRA_ENV", "").lower() != "development":
            raise RuntimeError("DevStubHSMSigner may only run with ASTRA_ENV=development")

    def sign(self, data: bytes) -> bytes:
        """Deterministic 256-byte stand-in signature — never a real HSM signature."""
        out = b""
        counter = 0
        while len(out) < 256:
            out += hmac.new(_DEV_KEY, data + counter.to_bytes(4, "big"), hashlib.sha256).digest()
            counter += 1
        return out[:256]
