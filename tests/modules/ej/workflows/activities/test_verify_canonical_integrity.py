"""
TDD — RED phase: tests for modules/ej/workflows/activities/verify_canonical_integrity.py

EJ Canonical Integrity Verification (Gemini Fix D):
  - After store_canonical writes to YugabyteDB, verify the record links back to raw log
  - Orphaned canonical records (no raw log in MinIO) → EJ_INTEGRITY_FAIL + PARSE_FAILED
  - Mismatched hash (canonical_hash in DB ≠ hash of stored raw log) → INTEGRITY_FAILED
  - Happy path → INTEGRITY_OK — proceed to trigger_dispute_check
  - Called between store_canonical (step 5) and trigger_dispute_check (step 6)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_integrity_input(**kwargs):
    from modules.ej.workflows.activities.verify_canonical_integrity import (
        EJIntegrityCheckInput,
    )
    return EJIntegrityCheckInput(
        canonical_hash=kwargs.get("canonical_hash", "abc123deadbeef"),
        raw_log_hash=kwargs.get("raw_log_hash", "rawlog456"),
        atm_id=kwargs.get("atm_id", "ATM-001"),
        bank_id=kwargs.get("bank_id", "test-bank"),
    )


# ---------------------------------------------------------------------------
# EJIntegrityCheckInput model
# ---------------------------------------------------------------------------

class TestEJIntegrityCheckInput:
    def test_input_fields(self):
        from modules.ej.workflows.activities.verify_canonical_integrity import (
            EJIntegrityCheckInput,
        )
        inp = EJIntegrityCheckInput(
            canonical_hash="abc123",
            raw_log_hash="rawlog789",
            atm_id="ATM-007",
            bank_id="hdfc-bank",
        )
        assert inp.canonical_hash == "abc123"
        assert inp.raw_log_hash == "rawlog789"
        assert inp.atm_id == "ATM-007"
        assert inp.bank_id == "hdfc-bank"

    def test_input_is_frozen(self):
        inp = _make_integrity_input()
        with pytest.raises(Exception):
            inp.canonical_hash = "tampered"


# ---------------------------------------------------------------------------
# EJIntegrityResult model
# ---------------------------------------------------------------------------

class TestEJIntegrityResult:
    def test_result_ok_fields(self):
        from modules.ej.workflows.activities.verify_canonical_integrity import (
            EJIntegrityResult,
        )
        r = EJIntegrityResult(
            outcome="INTEGRITY_OK",
            canonical_hash="abc123",
            raw_log_hash="rawlog456",
            bank_id="test-bank",
        )
        assert r.outcome == "INTEGRITY_OK"
        assert r.failure_reason is None

    def test_result_failed_carries_reason(self):
        from modules.ej.workflows.activities.verify_canonical_integrity import (
            EJIntegrityResult,
        )
        r = EJIntegrityResult(
            outcome="INTEGRITY_FAILED",
            canonical_hash="abc123",
            raw_log_hash="rawlog456",
            bank_id="test-bank",
            failure_reason="RAW_LOG_NOT_FOUND",
        )
        assert r.outcome == "INTEGRITY_FAILED"
        assert r.failure_reason == "RAW_LOG_NOT_FOUND"


# ---------------------------------------------------------------------------
# verify_canonical_integrity activity — happy path
# ---------------------------------------------------------------------------

class TestVerifyCanonicalIntegrityHappyPath:
    @pytest.mark.asyncio
    async def test_integrity_ok_when_canonical_hash_matches_stored_hash(self):
        """DB confirms canonical_hash exists and links to matching raw_log_hash."""
        from modules.ej.workflows.activities.verify_canonical_integrity import (
            verify_canonical_integrity,
        )
        db_client = MagicMock()
        # DB returns the row linking canonical_hash → raw_log_hash
        db_client.fetch_canonical_record = AsyncMock(return_value={
            "canonical_hash": "abc123deadbeef",
            "raw_log_hash": "rawlog456",
            "bank_id": "test-bank",
            "atm_id": "ATM-001",
        })

        inp = _make_integrity_input(canonical_hash="abc123deadbeef", raw_log_hash="rawlog456")
        result = await verify_canonical_integrity(inp, db_client=db_client)

        assert result.outcome == "INTEGRITY_OK"
        assert result.failure_reason is None

    @pytest.mark.asyncio
    async def test_db_is_queried_with_canonical_hash_and_bank_id(self):
        """Ensures multi-tenancy: bank_id always in the DB lookup."""
        from modules.ej.workflows.activities.verify_canonical_integrity import (
            verify_canonical_integrity,
        )
        db_client = MagicMock()
        db_client.fetch_canonical_record = AsyncMock(return_value={
            "canonical_hash": "hash-xyz",
            "raw_log_hash": "rawlog-abc",
            "bank_id": "kotak-mah",
            "atm_id": "ATM-K01",
        })

        inp = _make_integrity_input(
            canonical_hash="hash-xyz",
            raw_log_hash="rawlog-abc",
            bank_id="kotak-mah",
        )
        await verify_canonical_integrity(inp, db_client=db_client)

        db_client.fetch_canonical_record.assert_called_once()
        call_kwargs = db_client.fetch_canonical_record.call_args
        # bank_id must be in the query to prevent cross-bank reads
        assert "kotak-mah" in str(call_kwargs)


# ---------------------------------------------------------------------------
# verify_canonical_integrity activity — orphan detection
# ---------------------------------------------------------------------------

class TestVerifyCanonicalIntegrityOrphanDetection:
    @pytest.mark.asyncio
    async def test_integrity_failed_when_canonical_record_not_in_db(self):
        """Orphaned state: store_canonical reported success but record missing from DB."""
        from modules.ej.workflows.activities.verify_canonical_integrity import (
            verify_canonical_integrity,
        )
        db_client = MagicMock()
        # DB finds no record — orphaned
        db_client.fetch_canonical_record = AsyncMock(return_value=None)

        inp = _make_integrity_input()
        result = await verify_canonical_integrity(inp, db_client=db_client)

        assert result.outcome == "INTEGRITY_FAILED"
        assert result.failure_reason == "CANONICAL_RECORD_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_integrity_failed_when_raw_log_hash_mismatches(self):
        """
        DB has canonical record but raw_log_hash doesn't match expected.
        Could indicate: partition split in YugabyteDB, partial write, or corruption.
        """
        from modules.ej.workflows.activities.verify_canonical_integrity import (
            verify_canonical_integrity,
        )
        db_client = MagicMock()
        # DB returns wrong raw_log_hash
        db_client.fetch_canonical_record = AsyncMock(return_value={
            "canonical_hash": "abc123deadbeef",
            "raw_log_hash": "DIFFERENT_HASH",   # mismatch!
            "bank_id": "test-bank",
            "atm_id": "ATM-001",
        })

        inp = _make_integrity_input(canonical_hash="abc123deadbeef", raw_log_hash="rawlog456")
        result = await verify_canonical_integrity(inp, db_client=db_client)

        assert result.outcome == "INTEGRITY_FAILED"
        assert result.failure_reason == "RAW_LOG_HASH_MISMATCH"

    @pytest.mark.asyncio
    async def test_integrity_failed_when_bank_id_mismatches(self):
        """Cross-bank isolation check: canonical record exists but belongs to wrong bank."""
        from modules.ej.workflows.activities.verify_canonical_integrity import (
            verify_canonical_integrity,
        )
        db_client = MagicMock()
        # DB returns record with wrong bank_id (should never happen if query is correct)
        db_client.fetch_canonical_record = AsyncMock(return_value={
            "canonical_hash": "abc123deadbeef",
            "raw_log_hash": "rawlog456",
            "bank_id": "WRONG-BANK",   # isolation violation!
            "atm_id": "ATM-001",
        })

        inp = _make_integrity_input(bank_id="test-bank")
        result = await verify_canonical_integrity(inp, db_client=db_client)

        assert result.outcome == "INTEGRITY_FAILED"
        assert result.failure_reason == "BANK_ID_MISMATCH"


# ---------------------------------------------------------------------------
# verify_canonical_integrity activity — DB failure graceful degradation
# ---------------------------------------------------------------------------

class TestVerifyCanonicalIntegrityDBFailure:
    @pytest.mark.asyncio
    async def test_db_unavailable_returns_integrity_failed_not_raises(self):
        """DB timeout/error → INTEGRITY_FAILED with DB_UNAVAILABLE reason (not a crash)."""
        from modules.ej.workflows.activities.verify_canonical_integrity import (
            verify_canonical_integrity,
        )
        db_client = MagicMock()
        db_client.fetch_canonical_record = AsyncMock(
            side_effect=Exception("DB connection timeout")
        )

        inp = _make_integrity_input()
        result = await verify_canonical_integrity(inp, db_client=db_client)

        assert result.outcome == "INTEGRITY_FAILED"
        assert result.failure_reason == "DB_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_db_failure_does_not_raise_exception(self):
        """Activity must never let DB exceptions bubble up (Temporal handles retries)."""
        from modules.ej.workflows.activities.verify_canonical_integrity import (
            verify_canonical_integrity,
        )
        db_client = MagicMock()
        db_client.fetch_canonical_record = AsyncMock(
            side_effect=RuntimeError("YugabyteDB node unavailable")
        )

        inp = _make_integrity_input()
        # Must not raise
        result = await verify_canonical_integrity(inp, db_client=db_client)
        assert result.outcome == "INTEGRITY_FAILED"


# ---------------------------------------------------------------------------
# EJIntegrityError — raised by workflow when integrity check fails
# ---------------------------------------------------------------------------

class TestEJIntegrityError:
    def test_error_is_exception(self):
        from modules.ej.workflows.activities.verify_canonical_integrity import (
            EJIntegrityError,
        )
        err = EJIntegrityError(
            canonical_hash="abc123",
            failure_reason="RAW_LOG_NOT_FOUND",
            bank_id="test-bank",
        )
        assert isinstance(err, Exception)
        assert err.canonical_hash == "abc123"
        assert err.failure_reason == "RAW_LOG_NOT_FOUND"

    def test_error_message_contains_hash_and_reason(self):
        from modules.ej.workflows.activities.verify_canonical_integrity import (
            EJIntegrityError,
        )
        err = EJIntegrityError(
            canonical_hash="deadbeef1234",
            failure_reason="CANONICAL_RECORD_NOT_FOUND",
            bank_id="sbi-main",
        )
        msg = str(err)
        assert "deadbeef1234" in msg
        assert "CANONICAL_RECORD_NOT_FOUND" in msg


# ---------------------------------------------------------------------------
# Normalise workflow — integrity check wired between store_canonical and trigger_dispute
# ---------------------------------------------------------------------------

class TestNormalisationWorkflowIntegrityWiring:
    @pytest.mark.asyncio
    async def test_integrity_check_called_after_store_canonical(self):
        """
        EJNormalisationWorkflow.run_with_mocks must call verify_canonical_integrity
        between store_canonical (step 5) and trigger_dispute_check (step 6).
        """
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow, EJNormalisationInput
        from modules.ej.workflows.activities.store_canonical import EJStoreCanonicalResult
        from modules.ej.workflows.activities.verify_canonical_integrity import EJIntegrityResult

        call_order = []

        mock_store = MagicMock()
        mock_store.outcome = "STORED"
        mock_store.canonical_hash = "abc123"
        mock_store.bank_id = "test-bank"

        mock_integrity = MagicMock()
        mock_integrity.outcome = "INTEGRITY_OK"

        workflow = EJNormalisationWorkflow()
        inp = EJNormalisationInput(
            raw_log="[EJ LOG DATA]",
            raw_log_hash="rawlog456",
            atm_id="ATM-001",
            bank_id="test-bank",
            oem_fingerprint="NCR_APTRA",
            source="edge_agent",
        )

        # Build mock_results that includes the new verify_canonical_integrity key
        from types import SimpleNamespace

        fingerprint_r = SimpleNamespace(oem_fingerprint="NCR_APTRA", outcome="RECOGNISED")
        parse_r = SimpleNamespace(
            outcome="NORMALISED",
            canonical_hash="abc123",
            canonical_record={"txn_count": 5},
        )
        validate_r = SimpleNamespace(outcome="VALID")

        mock_results = {
            "ingest": SimpleNamespace(outcome="STORED", minio_key="ej/test-bank/raw/rawlog456"),
            "fingerprint": fingerprint_r,
            "llm_parse": parse_r,
            "validate": validate_r,
            "store_canonical": mock_store,
            "verify_canonical_integrity": mock_integrity,  # NEW — must be consumed
            "trigger_dispute_check": SimpleNamespace(outcome="PUBLISHED"),
            "update_atm_health": SimpleNamespace(outcome="UPDATED"),
            "write_audit": SimpleNamespace(outcome="WRITTEN"),
        }

        result = await workflow.run_with_mocks(inp, mock_results)

        # Workflow must succeed and use the integrity result
        assert result.outcome == "NORMALISED"

    @pytest.mark.asyncio
    async def test_integrity_failure_stops_workflow_before_dispute_trigger(self):
        """
        If verify_canonical_integrity returns INTEGRITY_FAILED, the workflow
        must NOT call trigger_dispute_check and must return INTEGRITY_FAILED outcome.
        """
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow, EJNormalisationInput
        from types import SimpleNamespace

        workflow = EJNormalisationWorkflow()
        inp = EJNormalisationInput(
            raw_log="[EJ LOG DATA]",
            raw_log_hash="rawlog456",
            atm_id="ATM-001",
            bank_id="test-bank",
            oem_fingerprint="NCR_APTRA",
            source="edge_agent",
        )

        fingerprint_r = SimpleNamespace(oem_fingerprint="NCR_APTRA", outcome="RECOGNISED")
        parse_r = SimpleNamespace(
            outcome="NORMALISED",
            canonical_hash="abc123",
            canonical_record={"txn_count": 5},
        )
        validate_r = SimpleNamespace(outcome="VALID")
        store_r = SimpleNamespace(outcome="STORED", canonical_hash="abc123", bank_id="test-bank")
        # Integrity check FAILED
        integrity_r = SimpleNamespace(
            outcome="INTEGRITY_FAILED",
            failure_reason="CANONICAL_RECORD_NOT_FOUND",
        )

        mock_results = {
            "ingest": SimpleNamespace(outcome="STORED", minio_key="ej/test-bank/raw/rawlog456"),
            "fingerprint": fingerprint_r,
            "llm_parse": parse_r,
            "validate": validate_r,
            "store_canonical": store_r,
            "verify_canonical_integrity": integrity_r,
            "trigger_dispute_check": SimpleNamespace(outcome="PUBLISHED"),
            "update_atm_health": SimpleNamespace(outcome="UPDATED"),
            "write_audit": SimpleNamespace(outcome="WRITTEN"),
        }

        result = await workflow.run_with_mocks(inp, mock_results)

        # Workflow aborts at integrity check — must NOT be NORMALISED
        assert result.outcome == "INTEGRITY_FAILED"
        # Dispute check must NOT have been triggered
        assert result.dispute_check_triggered is False
