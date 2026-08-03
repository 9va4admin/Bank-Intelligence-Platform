"""
Tests for shared/hsm/vault_transit_signer.py

VaultTransitSigner wraps HashiCorp Vault Transit engine.
Vault Transit signs bytes via the FIPS 140-2 Level 3 HSM — the private
key never leaves Vault, satisfying CLAUDE.md §11 "no software-held private keys".

Interface contract (what AuditEvent.sign(hsm) expects):
    hsm.sign(bytes) -> bytes

Tests use a mock Vault client — no real Vault needed.
"""
import base64
import pytest
from unittest.mock import MagicMock, patch


class TestVaultTransitSignerImport:

    def test_import(self):
        from shared.hsm.vault_transit_signer import VaultTransitSigner
        assert VaultTransitSigner is not None

    def test_hsm_signing_error_importable(self):
        from shared.audit.audit_event import HSMSigningError
        assert HSMSigningError is not None


class TestVaultTransitSignerSign:

    def _make_signer(self, mock_vault=None):
        from shared.hsm.vault_transit_signer import VaultTransitSigner
        if mock_vault is None:
            mock_vault = MagicMock()
        return VaultTransitSigner(vault_client=mock_vault, key_name="astra-audit-key")

    def test_sign_returns_bytes(self):
        raw_sig = b"\x01\x02\x03\x04"
        mock_vault = MagicMock()
        mock_vault.secrets.transit.sign_data.return_value = {
            "data": {"signature": f"vault:v1:{base64.b64encode(raw_sig).decode()}"}
        }
        signer = self._make_signer(mock_vault)
        result = signer.sign(b"hello world")
        assert isinstance(result, bytes)

    def test_sign_strips_vault_prefix_and_decodes_b64(self):
        raw_sig = b"\xDE\xAD\xBE\xEF"
        mock_vault = MagicMock()
        mock_vault.secrets.transit.sign_data.return_value = {
            "data": {"signature": f"vault:v1:{base64.b64encode(raw_sig).decode()}"}
        }
        signer = self._make_signer(mock_vault)
        result = signer.sign(b"some data")
        assert result == raw_sig

    def test_sign_passes_base64_encoded_data_to_vault(self):
        raw_sig = b"\x00\x01"
        mock_vault = MagicMock()
        mock_vault.secrets.transit.sign_data.return_value = {
            "data": {"signature": f"vault:v1:{base64.b64encode(raw_sig).decode()}"}
        }
        signer = self._make_signer(mock_vault)
        data = b"canonical audit bytes"
        signer.sign(data)
        call_kwargs = mock_vault.secrets.transit.sign_data.call_args[1]
        assert call_kwargs["hash_input"] == base64.b64encode(data).decode()
        assert call_kwargs["name"] == "astra-audit-key"

    def test_sign_vault_error_raises_hsm_signing_error(self):
        from shared.audit.audit_event import HSMSigningError
        mock_vault = MagicMock()
        mock_vault.secrets.transit.sign_data.side_effect = RuntimeError("Vault unreachable")
        signer = self._make_signer(mock_vault)
        with pytest.raises(HSMSigningError):
            signer.sign(b"data")

    def test_sign_missing_data_key_raises_hsm_signing_error(self):
        from shared.audit.audit_event import HSMSigningError
        mock_vault = MagicMock()
        mock_vault.secrets.transit.sign_data.return_value = {}  # no "data" key
        signer = self._make_signer(mock_vault)
        with pytest.raises(HSMSigningError):
            signer.sign(b"data")

    def test_sign_uses_correct_key_name(self):
        from shared.hsm.vault_transit_signer import VaultTransitSigner
        raw_sig = b"\x00"
        mock_vault = MagicMock()
        mock_vault.secrets.transit.sign_data.return_value = {
            "data": {"signature": f"vault:v1:{base64.b64encode(raw_sig).decode()}"}
        }
        signer = VaultTransitSigner(vault_client=mock_vault, key_name="custom-key")
        signer.sign(b"data")
        assert mock_vault.secrets.transit.sign_data.call_args[1]["name"] == "custom-key"

    def test_sign_different_data_called_with_different_b64(self):
        raw_sig = b"\x01"
        mock_vault = MagicMock()
        mock_vault.secrets.transit.sign_data.return_value = {
            "data": {"signature": f"vault:v1:{base64.b64encode(raw_sig).decode()}"}
        }
        signer = self._make_signer(mock_vault)
        signer.sign(b"first")
        signer.sign(b"second")
        calls = mock_vault.secrets.transit.sign_data.call_args_list
        assert calls[0][1]["hash_input"] != calls[1][1]["hash_input"]


class TestVaultTransitSignerFromEnv:

    def test_from_env_constructs_with_vault_addr_and_token(self):
        from shared.hsm.vault_transit_signer import VaultTransitSigner
        with patch.dict("os.environ", {"VAULT_ADDR": "https://vault:8200", "VAULT_TOKEN": "s.test"}):
            with patch("shared.hsm.vault_transit_signer.hvac") as mock_hvac:
                mock_hvac.Client.return_value = MagicMock()
                signer = VaultTransitSigner.from_env("astra-audit-key")
                mock_hvac.Client.assert_called_once_with(
                    url="https://vault:8200",
                    token="s.test",
                )
                assert isinstance(signer, VaultTransitSigner)

    def test_from_env_missing_vault_addr_raises(self):
        from shared.hsm.vault_transit_signer import VaultTransitSigner
        with patch.dict("os.environ", {}, clear=True):
            # VAULT_ADDR not set — should raise KeyError or similar
            with pytest.raises((KeyError, Exception)):
                VaultTransitSigner.from_env("astra-audit-key")

    def test_from_env_sets_key_name(self):
        from shared.hsm.vault_transit_signer import VaultTransitSigner
        with patch.dict("os.environ", {"VAULT_ADDR": "https://vault:8200", "VAULT_TOKEN": "s.tok"}):
            with patch("shared.hsm.vault_transit_signer.hvac") as mock_hvac:
                mock_hvac.Client.return_value = MagicMock()
                signer = VaultTransitSigner.from_env("my-key")
                assert signer._key_name == "my-key"


class TestVaultTransitSignerAuditEventIntegration:
    """Verify the signer satisfies AuditEvent.sign(hsm) interface."""

    def test_audit_event_sign_with_vault_transit_signer(self):
        from shared.audit.audit_event import AuditEvent, AuditEventType
        from shared.hsm.vault_transit_signer import VaultTransitSigner

        raw_sig = b"\xAB\xCD\xEF"
        mock_vault = MagicMock()
        mock_vault.secrets.transit.sign_data.return_value = {
            "data": {"signature": f"vault:v1:{base64.b64encode(raw_sig).decode()}"}
        }
        signer = VaultTransitSigner(vault_client=mock_vault, key_name="astra-audit-key")

        event = AuditEvent(
            event_type=AuditEventType.CTS_NGCH_FILED,
            bank_id="test-bank",
            payload={"decision": "CONFIRM"},
        )
        signed = event.sign(signer)
        assert signed.signature == raw_sig
        assert signed.bank_id == "test-bank"

    def test_signed_event_signature_is_deterministic_bytes(self):
        from shared.audit.audit_event import AuditEvent, AuditEventType
        from shared.hsm.vault_transit_signer import VaultTransitSigner

        raw_sig = b"\x01\x23\x45\x67"
        mock_vault = MagicMock()
        mock_vault.secrets.transit.sign_data.return_value = {
            "data": {"signature": f"vault:v1:{base64.b64encode(raw_sig).decode()}"}
        }
        signer = VaultTransitSigner(vault_client=mock_vault, key_name="key")
        event = AuditEvent(
            event_type=AuditEventType.CTS_DECISION,
            bank_id="b",
            payload={},
        )
        signed = event.sign(signer)
        assert isinstance(signed.signature, bytes)
        assert len(signed.signature) == 4
