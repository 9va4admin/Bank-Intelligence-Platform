"""
Tests for SMBVaultPushIngestWorkflow.

Triggered when a new CBS push file lands in the Agency's SFTP ingestion path.
Covers: happy paths for all 3 file types, parse failure, validate failure,
audit always written, idempotency key format.
"""
import pytest

from modules.cts.workflows.smb_vault_push_workflow import (
    SMBVaultPushInput,
    SMBVaultPushResult,
    SMBVaultPushWorkflow,
)
from modules.cts.smb_ingest.models import SMBPushFileType


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def workflow():
    return SMBVaultPushWorkflow()


def _inp(file_type=SMBPushFileType.STOP_PAYMENTS, file_hash="abc123def456"):
    return SMBVaultPushInput(
        agency_id="agency-saraswat",
        smb_id="testucb",
        file_type=file_type,
        file_path="/smb-ingest/testucb/stop_payments/20260705_120000.csv",
        file_hash=file_hash,
    )


# ── Workflow ID ───────────────────────────────────────────────────────────

class TestWorkflowId:
    def test_id_format(self, workflow):
        wid = workflow.workflow_id("agency-saraswat", "testucb", "abc123def456")
        assert wid == "cts-smb-push-agency-saraswat-testucb-abc123def456"

    def test_id_is_idempotent(self, workflow):
        wid1 = workflow.workflow_id("agency-saraswat", "testucb", "abc123def456")
        wid2 = workflow.workflow_id("agency-saraswat", "testucb", "abc123def456")
        assert wid1 == wid2


# ── SMBVaultPushInput ─────────────────────────────────────────────────────

class TestSMBVaultPushInput:
    def test_required_fields(self):
        inp = _inp()
        assert inp.agency_id == "agency-saraswat"
        assert inp.smb_id == "testucb"
        assert inp.file_type == SMBPushFileType.STOP_PAYMENTS
        assert inp.file_hash == "abc123def456"

    def test_frozen(self):
        inp = _inp()
        with pytest.raises(Exception):
            inp.smb_id = "other"

    def test_all_file_types_accepted(self):
        for ft in [SMBPushFileType.STOP_PAYMENTS, SMBPushFileType.PPS_ENTRIES, SMBPushFileType.SIGNATURES]:
            inp = _inp(file_type=ft)
            assert inp.file_type == ft


# ── Happy path — STOP_PAYMENTS ────────────────────────────────────────────

class TestStopPaymentsHappyPath:
    @pytest.mark.asyncio
    async def test_vault_updated_outcome(self, workflow):
        inp = _inp(SMBPushFileType.STOP_PAYMENTS)
        result = await workflow.run_with_mocks(inp, {
            "parse_and_validate": {"records": [{"cheque": "000123"}], "record_count": 1},
            "update_vault": {"updated_count": 1, "bloom_updated": True},
            "audit": {"written": True},
        })
        assert result.outcome == "VAULT_UPDATED"

    @pytest.mark.asyncio
    async def test_records_processed_count(self, workflow):
        inp = _inp(SMBPushFileType.STOP_PAYMENTS)
        result = await workflow.run_with_mocks(inp, {
            "parse_and_validate": {"records": [{}, {}, {}], "record_count": 3},
            "update_vault": {"updated_count": 3, "bloom_updated": True},
            "audit": {"written": True},
        })
        assert result.records_processed == 3

    @pytest.mark.asyncio
    async def test_audit_written_on_success(self, workflow):
        inp = _inp(SMBPushFileType.STOP_PAYMENTS)
        result = await workflow.run_with_mocks(inp, {
            "parse_and_validate": {"records": [{}], "record_count": 1},
            "update_vault": {"updated_count": 1, "bloom_updated": True},
            "audit": {"written": True},
        })
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_smb_id_in_result(self, workflow):
        inp = _inp(SMBPushFileType.STOP_PAYMENTS)
        result = await workflow.run_with_mocks(inp, {
            "parse_and_validate": {"records": [{}], "record_count": 1},
            "update_vault": {"updated_count": 1, "bloom_updated": True},
            "audit": {"written": True},
        })
        assert result.smb_id == "testucb"
        assert result.agency_id == "agency-saraswat"


# ── Happy path — PPS_ENTRIES ──────────────────────────────────────────────

class TestPPSEntriesHappyPath:
    @pytest.mark.asyncio
    async def test_vault_updated_for_pps(self, workflow):
        inp = _inp(SMBPushFileType.PPS_ENTRIES)
        result = await workflow.run_with_mocks(inp, {
            "parse_and_validate": {"records": [{}, {}], "record_count": 2},
            "update_vault": {"updated_count": 2, "bloom_updated": False},
            "audit": {"written": True},
        })
        assert result.outcome == "VAULT_UPDATED"
        assert result.records_processed == 2

    @pytest.mark.asyncio
    async def test_file_type_in_result(self, workflow):
        inp = _inp(SMBPushFileType.PPS_ENTRIES)
        result = await workflow.run_with_mocks(inp, {
            "parse_and_validate": {"records": [{}], "record_count": 1},
            "update_vault": {"updated_count": 1, "bloom_updated": False},
            "audit": {"written": True},
        })
        assert result.file_type == SMBPushFileType.PPS_ENTRIES


# ── Happy path — SIGNATURES ───────────────────────────────────────────────

class TestSignaturesHappyPath:
    @pytest.mark.asyncio
    async def test_vault_updated_for_signatures(self, workflow):
        inp = _inp(SMBPushFileType.SIGNATURES)
        result = await workflow.run_with_mocks(inp, {
            "parse_and_validate": {"records": [{}, {}, {}, {}], "record_count": 4},
            "update_vault": {"updated_count": 4, "bloom_updated": False},
            "audit": {"written": True},
        })
        assert result.outcome == "VAULT_UPDATED"
        assert result.records_processed == 4


# ── Parse failure ─────────────────────────────────────────────────────────

class TestParseFailure:
    @pytest.mark.asyncio
    async def test_parse_failed_outcome(self, workflow):
        inp = _inp()
        result = await workflow.run_with_mocks(inp, {
            "parse_and_validate": {"error": "MISSING_COLUMN:amount", "records": [], "record_count": 0},
            "audit": {"written": True},
        })
        assert result.outcome == "PARSE_FAILED"

    @pytest.mark.asyncio
    async def test_audit_written_on_parse_failure(self, workflow):
        inp = _inp()
        result = await workflow.run_with_mocks(inp, {
            "parse_and_validate": {"error": "EMPTY_FILE", "records": [], "record_count": 0},
            "audit": {"written": True},
        })
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_records_processed_zero_on_parse_failure(self, workflow):
        inp = _inp()
        result = await workflow.run_with_mocks(inp, {
            "parse_and_validate": {"error": "UNKNOWN_FORMAT", "records": [], "record_count": 0},
            "audit": {"written": True},
        })
        assert result.records_processed == 0

    @pytest.mark.asyncio
    async def test_failure_reason_set_on_parse_error(self, workflow):
        inp = _inp()
        result = await workflow.run_with_mocks(inp, {
            "parse_and_validate": {"error": "MISSING_COLUMN:cheque_number", "records": [], "record_count": 0},
            "audit": {"written": True},
        })
        assert result.failure_reason is not None
        assert "MISSING_COLUMN" in result.failure_reason


# ── Vault update failure ──────────────────────────────────────────────────

class TestVaultUpdateFailure:
    @pytest.mark.asyncio
    async def test_validate_failed_outcome(self, workflow):
        inp = _inp()
        result = await workflow.run_with_mocks(inp, {
            "parse_and_validate": {"records": [{}], "record_count": 1},
            "update_vault": {"error": "REDIS_UNAVAILABLE", "updated_count": 0},
            "audit": {"written": True},
        })
        assert result.outcome == "VAULT_UPDATE_FAILED"

    @pytest.mark.asyncio
    async def test_audit_written_on_vault_failure(self, workflow):
        inp = _inp()
        result = await workflow.run_with_mocks(inp, {
            "parse_and_validate": {"records": [{}], "record_count": 1},
            "update_vault": {"error": "REDIS_TIMEOUT", "updated_count": 0},
            "audit": {"written": True},
        })
        assert result.audit_written is True


# ── Idempotency (duplicate file hash) ─────────────────────────────────────

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_duplicate_file_hash_already_processed(self, workflow):
        inp = _inp(file_hash="already-seen-hash")
        result = await workflow.run_with_mocks(inp, {
            "parse_and_validate": {"records": [], "record_count": 0, "duplicate": True},
            "audit": {"written": True},
        })
        assert result.outcome == "DUPLICATE_SKIPPED"

    @pytest.mark.asyncio
    async def test_duplicate_audit_still_written(self, workflow):
        inp = _inp(file_hash="already-seen-hash")
        result = await workflow.run_with_mocks(inp, {
            "parse_and_validate": {"records": [], "record_count": 0, "duplicate": True},
            "audit": {"written": True},
        })
        assert result.audit_written is True
