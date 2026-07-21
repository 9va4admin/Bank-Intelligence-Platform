"""
VaultTransitSigner — HSM signing via HashiCorp Vault Transit engine.

Satisfies AuditEvent.sign(hsm) interface: hsm.sign(bytes) -> bytes

Architecture choice (CLAUDE.md §2.7 and §11):
  Vault Transit is the right interface for ASTRA because:
  1. Vault is already in the mandatory stack — zero new Docker images.
  2. "No software-held private keys" — the signing key lives in Vault (which
     in production uses a FIPS 140-2 Level 3 HSM as its seal/backend).
  3. Application code stays vendor-neutral — one HTTP call to Vault's Transit
     API, regardless of which HSM appliance is underneath.
  4. No PKCS#11 vendor library in Docker images (avoids bank CAB burden).

In production, Vault is configured with:
    vault secrets enable transit
    vault write -f transit/keys/astra-audit-key type=rsa-4096

The key name is read from config_service at worker startup
(config key: "hsm.transit_key_name").

from_env() is the construction entry point — uses VAULT_ADDR and VAULT_TOKEN
from the environment (the only two env vars allowed per secrets-vault.md;
injected by Vault agent sidecar, same convention as config_service.py).
"""
from __future__ import annotations

import base64
import os
from typing import Any

import structlog

try:
    import hvac
except ImportError:
    hvac = None  # type: ignore[assignment]

from shared.audit.audit_event import HSMSigningError

log = structlog.get_logger()


class VaultTransitSigner:
    """
    Signs bytes via Vault Transit. Thread-safe (stateless per call).
    """

    def __init__(self, vault_client: Any, key_name: str) -> None:
        self._vault = vault_client
        self._key_name = key_name

    def sign(self, data: bytes) -> bytes:
        """
        Sign `data` using Vault Transit and return the raw signature bytes.

        Vault returns "vault:v1:<base64-encoded-signature>" — the prefix is
        stripped and the base64 decoded to raw bytes before returning.

        Raises HSMSigningError on any Vault error.
        """
        b64_input = base64.b64encode(data).decode()
        try:
            response = self._vault.secrets.transit.sign_data(
                name=self._key_name,
                hash_input=b64_input,
            )
            sig_str = response["data"]["signature"]   # "vault:v1:<base64>"
        except HSMSigningError:
            raise
        except Exception as exc:
            raise HSMSigningError(f"Vault Transit signing failed: {exc}") from exc

        try:
            sig_b64 = sig_str.split(":")[-1]
            return base64.b64decode(sig_b64)
        except Exception as exc:
            raise HSMSigningError(f"Failed to decode Vault Transit signature: {exc}") from exc

    @classmethod
    def from_env(cls, key_name: str) -> "VaultTransitSigner":
        """
        Construct from VAULT_ADDR and VAULT_TOKEN environment variables.

        These are the only two env vars allowed in application code per
        secrets-vault.md — they are injected by the Vault agent sidecar at
        pod startup, not set by application code.

        Raises KeyError if either env var is absent.
        Raises ImportError if hvac is not installed.
        """
        if hvac is None:
            raise ImportError("hvac is not installed — pip install hvac")

        vault_addr = os.environ["VAULT_ADDR"]
        vault_token = os.environ["VAULT_TOKEN"]
        client = hvac.Client(url=vault_addr, token=vault_token)
        log.info("vault_transit_signer.client_constructed", key_name=key_name)
        return cls(vault_client=client, key_name=key_name)
