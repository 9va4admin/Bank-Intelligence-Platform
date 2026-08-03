"""
Tests for shared/sb_connector/ — Agency → SB adapter layer.

TDD RED phase: these tests must FAIL before implementation is written.
"""
import pytest
from unittest.mock import AsyncMock, patch

# --------------------------------------------------------------------------- #
# Imports that will fail until implementation is written (RED confirmation)
# --------------------------------------------------------------------------- #
from shared.sb_connector.base import (
    SBConnectorBase,
    SBSubmissionResult,
    SBInwardBatch,
    get_connector_for_type,
)
from shared.sb_connector.sftp_generic import SFTPGenericConnector
from shared.sb_connector.bancs_api import BANCSApiConnector
from shared.sb_connector.nelito_api import NelitApiConnector
from shared.sb_connector.exceptions import (
    SBConnectorUnavailableError,
    SBSubmissionRejectedError,
    SBConnectorAuthError,
)


# --------------------------------------------------------------------------- #
# SBSubmissionResult model
# --------------------------------------------------------------------------- #
class TestSBSubmissionResult:
    def test_success_result(self):
        r = SBSubmissionResult(success=True, reference_number="SB-REF-001", latency_ms=142)
        assert r.success is True
        assert r.reference_number == "SB-REF-001"
        assert r.latency_ms == 142
        assert r.error_code is None
        assert r.error_message is None

    def test_failure_result(self):
        r = SBSubmissionResult(
            success=False,
            error_code="SB_CONN_TIMEOUT",
            error_message="Connection timed out after 30s",
        )
        assert r.success is False
        assert r.reference_number is None
        assert r.error_code == "SB_CONN_TIMEOUT"

    def test_result_is_frozen(self):
        r = SBSubmissionResult(success=True)
        with pytest.raises(Exception):
            r.success = False  # type: ignore[misc]


class TestSBInwardBatch:
    def test_inward_batch_fields(self):
        batch = SBInwardBatch(
            session_id="sess-001",
            sb_bank_id="saraswat-coop",
            instruments=[
                {"instrument_id": "I001", "original_ngch_ts": "2026-07-05T10:00:00Z"},
                {"instrument_id": "I002", "original_ngch_ts": "2026-07-05T10:01:00Z"},
            ],
            received_at="2026-07-05T10:05:00Z",
        )
        assert batch.session_id == "sess-001"
        assert len(batch.instruments) == 2
        assert batch.instruments[0]["instrument_id"] == "I001"

    def test_inward_batch_frozen(self):
        batch = SBInwardBatch(
            session_id="s", sb_bank_id="bank", instruments=[], received_at="2026-07-05T10:00:00Z"
        )
        with pytest.raises(Exception):
            batch.session_id = "other"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# get_connector_for_type factory
# --------------------------------------------------------------------------- #
class TestGetConnectorForType:
    def test_sftp_generic_returns_sftp_connector(self):
        c = get_connector_for_type("SFTP_GENERIC", "cosmos-agency", "saraswat-coop")
        assert isinstance(c, SFTPGenericConnector)
        assert c.agency_id == "cosmos-agency"
        assert c.sb_bank_id == "saraswat-coop"

    def test_bancs_api_returns_bancs_connector(self):
        c = get_connector_for_type("BANCS_API", "agency-id", "sb-id")
        assert isinstance(c, BANCSApiConnector)

    def test_nelito_api_returns_nelito_connector(self):
        c = get_connector_for_type("NELITO_API", "agency-id", "sb-id")
        assert isinstance(c, NelitApiConnector)

    def test_unknown_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown connector_type"):
            get_connector_for_type("UNKNOWN_TYPE", "a", "b")

    def test_all_return_subclass_of_base(self):
        for ctype in ["SFTP_GENERIC", "BANCS_API", "NELITO_API"]:
            c = get_connector_for_type(ctype, "agency", "sb")
            assert isinstance(c, SBConnectorBase)


# --------------------------------------------------------------------------- #
# SBConnectorBase ABC enforcement
# --------------------------------------------------------------------------- #
class TestSBConnectorBaseABC:
    def test_cannot_instantiate_base_directly(self):
        with pytest.raises(TypeError):
            SBConnectorBase("a", "b")  # type: ignore[abstract]

    def test_concrete_must_implement_submit_lot(self):
        class Incomplete(SBConnectorBase):
            async def ping(self): ...
            async def fetch_inward_instruments(self, session_id): ...
            # missing submit_lot
        with pytest.raises(TypeError):
            Incomplete("a", "b")  # type: ignore[abstract]

    def test_concrete_must_implement_ping(self):
        class Incomplete(SBConnectorBase):
            async def submit_lot(self, lot_path, count, session_id): ...
            async def fetch_inward_instruments(self, session_id): ...
            # missing ping
        with pytest.raises(TypeError):
            Incomplete("a", "b")  # type: ignore[abstract]


# --------------------------------------------------------------------------- #
# SFTPGenericConnector
# --------------------------------------------------------------------------- #
class TestSFTPGenericConnector:
    def _make(self) -> SFTPGenericConnector:
        return SFTPGenericConnector(agency_id="cosmos-agency", sb_bank_id="saraswat-coop")

    @pytest.mark.asyncio
    async def test_ping_success(self):
        c = self._make()
        with patch.object(c, "_sftp_connect", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = True
            result = await c.ping()
        assert isinstance(result, SBSubmissionResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_ping_connection_failure(self):
        c = self._make()
        with patch.object(c, "_sftp_connect", new_callable=AsyncMock,
                          side_effect=Exception("Connection refused")):
            result = await c.ping()
        assert result.success is False
        assert result.error_code == "SFTP_PING_FAILED"

    @pytest.mark.asyncio
    async def test_submit_lot_success(self):
        c = self._make()
        with patch.object(c, "_sftp_upload", new_callable=AsyncMock,
                          return_value="SB-SFTP-REF-9901"):
            result = await c.submit_lot("/tmp/lot_001.cts", 50, "sess-2026-001")
        assert result.success is True
        assert result.reference_number == "SB-SFTP-REF-9901"

    @pytest.mark.asyncio
    async def test_submit_lot_upload_failure_returns_failure_result(self):
        c = self._make()
        with patch.object(c, "_sftp_upload", new_callable=AsyncMock,
                          side_effect=Exception("SFTP timeout")):
            result = await c.submit_lot("/tmp/lot_001.cts", 50, "sess-001")
        assert result.success is False
        assert result.error_code == "SFTP_UPLOAD_FAILED"

    @pytest.mark.asyncio
    async def test_fetch_inward_returns_list(self):
        c = self._make()
        with patch.object(c, "_sftp_list_inward", new_callable=AsyncMock,
                          return_value=[{"instrument_id": "X001"}]):
            instruments = await c.fetch_inward_instruments("sess-001")
        assert isinstance(instruments, list)
        assert instruments[0]["instrument_id"] == "X001"

    @pytest.mark.asyncio
    async def test_fetch_inward_empty_returns_empty_list(self):
        c = self._make()
        with patch.object(c, "_sftp_list_inward", new_callable=AsyncMock, return_value=[]):
            instruments = await c.fetch_inward_instruments("sess-001")
        assert instruments == []

    def test_sftp_connector_stores_ids(self):
        c = SFTPGenericConnector("agency-x", "sb-y")
        assert c.agency_id == "agency-x"
        assert c.sb_bank_id == "sb-y"


# --------------------------------------------------------------------------- #
# BANCSApiConnector
# --------------------------------------------------------------------------- #
class TestBANCSApiConnector:
    def _make(self) -> BANCSApiConnector:
        return BANCSApiConnector(agency_id="cosmos-agency", sb_bank_id="bancs-sb")

    @pytest.mark.asyncio
    async def test_ping_success(self):
        c = self._make()
        with patch.object(c, "_http_ping", new_callable=AsyncMock, return_value=True):
            result = await c.ping()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_ping_failure(self):
        c = self._make()
        with patch.object(c, "_http_ping", new_callable=AsyncMock,
                          side_effect=Exception("HTTP 503")):
            result = await c.ping()
        assert result.success is False
        assert result.error_code == "BANCS_PING_FAILED"

    @pytest.mark.asyncio
    async def test_submit_lot_success(self):
        c = self._make()
        with patch.object(c, "_http_post_lot", new_callable=AsyncMock,
                          return_value={"reference_id": "BANCS-REF-42", "status": "ACCEPTED"}):
            result = await c.submit_lot("/tmp/lot.cts", 30, "sess-bancs-001")
        assert result.success is True
        assert result.reference_number == "BANCS-REF-42"

    @pytest.mark.asyncio
    async def test_submit_lot_rejected_raises_submission_error(self):
        c = self._make()
        with patch.object(c, "_http_post_lot", new_callable=AsyncMock,
                          return_value={"reference_id": None, "status": "REJECTED",
                                        "error": "LIMIT_EXCEEDED"}):
            result = await c.submit_lot("/tmp/lot.cts", 30, "sess-bancs-001")
        assert result.success is False
        assert result.error_code == "BANCS_SUBMISSION_REJECTED"

    @pytest.mark.asyncio
    async def test_fetch_inward_returns_list(self):
        c = self._make()
        with patch.object(c, "_http_get_inward", new_callable=AsyncMock,
                          return_value=[{"instrument_id": "BANCS-I001"}]):
            instruments = await c.fetch_inward_instruments("sess-001")
        assert instruments[0]["instrument_id"] == "BANCS-I001"


# --------------------------------------------------------------------------- #
# NelitApiConnector
# --------------------------------------------------------------------------- #
class TestNelitApiConnector:
    def _make(self) -> NelitApiConnector:
        return NelitApiConnector(agency_id="cosmos-agency", sb_bank_id="nelito-sb")

    @pytest.mark.asyncio
    async def test_ping_success(self):
        c = self._make()
        with patch.object(c, "_nelito_ping", new_callable=AsyncMock, return_value=True):
            result = await c.ping()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_ping_failure(self):
        c = self._make()
        with patch.object(c, "_nelito_ping", new_callable=AsyncMock,
                          side_effect=Exception("Auth failed")):
            result = await c.ping()
        assert result.success is False
        assert result.error_code == "NELITO_PING_FAILED"

    @pytest.mark.asyncio
    async def test_submit_lot_success(self):
        c = self._make()
        with patch.object(c, "_nelito_submit", new_callable=AsyncMock,
                          return_value={"txn_id": "NLT-0099", "ack": True}):
            result = await c.submit_lot("/tmp/lot.cts", 25, "sess-001")
        assert result.success is True
        assert result.reference_number == "NLT-0099"

    @pytest.mark.asyncio
    async def test_submit_lot_auth_failure(self):
        c = self._make()
        with patch.object(c, "_nelito_submit", new_callable=AsyncMock,
                          side_effect=Exception("401 Unauthorized")):
            result = await c.submit_lot("/tmp/lot.cts", 25, "sess-001")
        assert result.success is False
        assert result.error_code == "NELITO_UPLOAD_FAILED"

    @pytest.mark.asyncio
    async def test_fetch_inward_returns_list(self):
        c = self._make()
        with patch.object(c, "_nelito_fetch_inward", new_callable=AsyncMock,
                          return_value=[{"instrument_id": "NLT-I001"}]):
            instruments = await c.fetch_inward_instruments("sess-001")
        assert instruments[0]["instrument_id"] == "NLT-I001"


# --------------------------------------------------------------------------- #
# Exception hierarchy
# --------------------------------------------------------------------------- #
class TestExceptions:
    def test_unavailable_is_runtime_error(self):
        e = SBConnectorUnavailableError("saraswat-coop", "SFTP_GENERIC", "Connection refused")
        assert isinstance(e, RuntimeError)
        assert "saraswat-coop" in str(e)

    def test_rejected_carries_error_code(self):
        e = SBSubmissionRejectedError("LIMIT_EXCEEDED", "Lot size exceeded SB limit")
        assert isinstance(e, RuntimeError)
        assert e.error_code == "LIMIT_EXCEEDED"

    def test_auth_error_is_runtime_error(self):
        e = SBConnectorAuthError("saraswat-coop", "Token expired")
        assert isinstance(e, RuntimeError)
        assert "saraswat-coop" in str(e)

    def test_rejected_is_subclass_of_unavailable(self):
        # Rejected is a distinct error — NOT a subclass of Unavailable
        assert not issubclass(SBSubmissionRejectedError, SBConnectorUnavailableError)

    def test_auth_error_is_subclass_of_unavailable(self):
        assert issubclass(SBConnectorAuthError, SBConnectorUnavailableError)
