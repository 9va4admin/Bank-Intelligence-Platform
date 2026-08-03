"""
Tests for validate_ifsc Temporal activity.

Design:
  - IFSC found in registry (ACTIVE) → PROCEED
  - IFSC not found → HUMAN_REVIEW (WRONGLY_DELIVERED candidate, URRBCH 36)
  - IFSC found but INACTIVE / PENDING → HUMAN_REVIEW (closed/unapproved branch)
  - Repository raises exception → HUMAN_REVIEW (degraded)
  - No DB connector → HUMAN_REVIEW (degraded)
  - SMB-scoped check: IFSC belongs to the named SMB → PROCEED
  - SMB-scoped check: IFSC exists but under wrong SMB → HUMAN_REVIEW
"""
import pytest
from unittest.mock import AsyncMock, patch


def _make_input(**kwargs):
    from modules.cts.workflows.activities.ifsc_validator import IFSCValidatorInput
    defaults = dict(
        instrument_id="INST001",
        bank_id="saraswat-coop",
        ifsc_to_validate="SARB0000001",
        smb_id=None,
    )
    defaults.update(kwargs)
    return IFSCValidatorInput(**defaults)


def _make_entry(status="ACTIVE", bank_type="SB", smb_id=None):
    from modules.cts.ifsc.models import IFSCEntry
    from datetime import date
    return IFSCEntry(
        id="uuid-001",
        bank_id="saraswat-coop",
        bank_type=bank_type,
        smb_id=smb_id,
        ifsc_code="SARB0000001",
        branch_name="Main Branch",
        branch_city="Mumbai",
        micr_code="400084001",
        is_active=(status == "ACTIVE"),
        effective_from=date(2026, 1, 1),
        effective_till=None,
        status=status,
        created_by="admin@saraswat.in",
        approved_by="itadmin@saraswat.in" if status == "ACTIVE" else None,
    )


class TestValidateIFSC:
    @pytest.mark.asyncio
    async def test_active_ifsc_in_registry_proceeds(self):
        from modules.cts.workflows.activities.ifsc_validator import validate_ifsc
        repo = AsyncMock()
        repo.lookup_ifsc = AsyncMock(return_value=_make_entry(status="ACTIVE"))
        result = await validate_ifsc(_make_input(), repo=repo)
        assert result.outcome == "PROCEED"
        assert result.degraded is False

    @pytest.mark.asyncio
    async def test_ifsc_not_in_registry_human_review(self):
        from modules.cts.workflows.activities.ifsc_validator import validate_ifsc
        repo = AsyncMock()
        repo.lookup_ifsc = AsyncMock(return_value=None)
        result = await validate_ifsc(_make_input(ifsc_to_validate="SBIN0001234"), repo=repo)
        assert result.outcome == "HUMAN_REVIEW"
        assert result.reason == "IFSC_NOT_IN_REGISTRY"
        assert result.return_reason_code == "36"  # WRONGLY_DELIVERED

    @pytest.mark.asyncio
    async def test_inactive_ifsc_human_review(self):
        from modules.cts.workflows.activities.ifsc_validator import validate_ifsc
        repo = AsyncMock()
        repo.lookup_ifsc = AsyncMock(return_value=_make_entry(status="INACTIVE"))
        result = await validate_ifsc(_make_input(), repo=repo)
        assert result.outcome == "HUMAN_REVIEW"
        assert result.reason == "IFSC_BRANCH_INACTIVE"

    @pytest.mark.asyncio
    async def test_pending_ifsc_human_review(self):
        from modules.cts.workflows.activities.ifsc_validator import validate_ifsc
        repo = AsyncMock()
        repo.lookup_ifsc = AsyncMock(return_value=_make_entry(status="PENDING"))
        result = await validate_ifsc(_make_input(), repo=repo)
        assert result.outcome == "HUMAN_REVIEW"
        assert result.reason == "IFSC_NOT_YET_APPROVED"

    @pytest.mark.asyncio
    async def test_db_exception_degrades_gracefully(self):
        from modules.cts.workflows.activities.ifsc_validator import validate_ifsc
        repo = AsyncMock()
        repo.lookup_ifsc = AsyncMock(side_effect=Exception("DB connection lost"))
        result = await validate_ifsc(_make_input(), repo=repo)
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True
        assert result.reason == "IFSC_REGISTRY_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_no_repo_degrades_gracefully(self):
        from modules.cts.workflows.activities.ifsc_validator import validate_ifsc
        result = await validate_ifsc(_make_input(), repo=None)
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_smb_scoped_ifsc_found_proceeds(self):
        from modules.cts.workflows.activities.ifsc_validator import validate_ifsc
        repo = AsyncMock()
        repo.lookup_ifsc = AsyncMock(
            return_value=_make_entry(status="ACTIVE", bank_type="SMB", smb_id="smb-001")
        )
        result = await validate_ifsc(_make_input(smb_id="smb-001"), repo=repo)
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_smb_scoped_ifsc_missing_human_review(self):
        """IFSC not found under this SMB (even if it exists for a different SMB)."""
        from modules.cts.workflows.activities.ifsc_validator import validate_ifsc
        repo = AsyncMock()
        repo.lookup_ifsc = AsyncMock(return_value=None)
        result = await validate_ifsc(_make_input(smb_id="smb-999"), repo=repo)
        assert result.outcome == "HUMAN_REVIEW"
        assert result.return_reason_code == "36"

    @pytest.mark.asyncio
    async def test_proceed_result_has_no_return_code(self):
        from modules.cts.workflows.activities.ifsc_validator import validate_ifsc
        repo = AsyncMock()
        repo.lookup_ifsc = AsyncMock(return_value=_make_entry())
        result = await validate_ifsc(_make_input(), repo=repo)
        assert result.return_reason_code is None

    @pytest.mark.asyncio
    async def test_bank_id_always_scoped_in_lookup(self):
        """validate_ifsc must pass bank_id to repo.lookup_ifsc — no cross-bank leakage."""
        from modules.cts.workflows.activities.ifsc_validator import validate_ifsc
        repo = AsyncMock()
        repo.lookup_ifsc = AsyncMock(return_value=_make_entry())
        await validate_ifsc(_make_input(bank_id="some-bank"), repo=repo)
        call_kwargs = repo.lookup_ifsc.call_args
        # bank_id must be the first positional arg or a keyword arg
        args, kwargs = call_kwargs
        assert "some-bank" in args or kwargs.get("bank_id") == "some-bank"
