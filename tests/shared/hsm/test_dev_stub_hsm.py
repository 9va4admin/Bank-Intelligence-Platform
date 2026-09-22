"""DevStubHSMSigner — dev/test stand-in for VaultTransitSigner (no Vault Transit key configured in dev)."""
import os

import pytest

from shared.hsm.dev_stub_hsm import DevStubHSMSigner


def test_sign_returns_256_bytes(monkeypatch):
    monkeypatch.setenv("ASTRA_ENV", "development")
    signer = DevStubHSMSigner()
    sig = signer.sign(b"some cheque data")
    assert isinstance(sig, bytes) and len(sig) == 256


def test_sign_is_deterministic_for_same_input(monkeypatch):
    monkeypatch.setenv("ASTRA_ENV", "development")
    signer = DevStubHSMSigner()
    assert signer.sign(b"x") == signer.sign(b"x")
    assert signer.sign(b"x") != signer.sign(b"y")


def test_refuses_outside_development(monkeypatch):
    monkeypatch.setenv("ASTRA_ENV", "production")
    with pytest.raises(RuntimeError):
        DevStubHSMSigner()


def test_refuses_when_env_unset(monkeypatch):
    monkeypatch.delenv("ASTRA_ENV", raising=False)
    with pytest.raises(RuntimeError):
        DevStubHSMSigner()
