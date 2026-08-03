"""
Tests for IFSCRepository — lookup, list, create, approve, deactivate.

All DB calls are stubbed via an AsyncMock connection so no real
YugabyteDB is required.  The repository is a thin query layer — we
verify it (a) builds the right SQL inputs and (b) maps rows correctly.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import date


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_row(**kwargs):
    """Minimal asyncpg-style row dict for IFSCEntry mapping."""
    defaults = {
        "id": "uuid-001",
        "bank_id": "saraswat-coop",
        "bank_type": "SB",
        "smb_id": None,
        "ifsc_code": "SARB0000001",
        "branch_name": "Main Branch",
        "branch_city": "Mumbai",
        "micr_code": "400084001",
        "is_active": True,
        "effective_from": date(2026, 1, 1),
        "effective_till": None,
        "status": "ACTIVE",
        "created_by": "admin@saraswat.in",
        "approved_by": "itadmin@saraswat.in",
    }
    defaults.update(kwargs)
    return defaults


def _make_repo(rows=None, fetchrow_return=None):
    """Return an IFSCRepository with a stubbed async DB connection."""
    from modules.cts.ifsc.repository import IFSCRepository
    db = AsyncMock()
    db.fetch = AsyncMock(return_value=rows or [])
    db.fetchrow = AsyncMock(return_value=fetchrow_return)
    db.execute = AsyncMock(return_value="INSERT 1")
    return IFSCRepository(db=db), db


# ── lookup_ifsc ───────────────────────────────────────────────────────────────

class TestLookupIFSC:
    @pytest.mark.asyncio
    async def test_found_active_sb_entry(self):
        row = _make_row()
        repo, db = _make_repo(fetchrow_return=row)
        entry = await repo.lookup_ifsc("saraswat-coop", "SARB0000001")
        assert entry is not None
        assert entry.ifsc_code == "SARB0000001"
        assert entry.status == "ACTIVE"
        assert entry.bank_type == "SB"

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        repo, db = _make_repo(fetchrow_return=None)
        entry = await repo.lookup_ifsc("saraswat-coop", "SBIN0000001")
        assert entry is None

    @pytest.mark.asyncio
    async def test_found_smb_entry(self):
        row = _make_row(bank_type="SMB", smb_id="smb-001", ifsc_code="SOMUCB0001")
        repo, db = _make_repo(fetchrow_return=row)
        entry = await repo.lookup_ifsc("saraswat-coop", "SOMUCB0001", smb_id="smb-001")
        assert entry is not None
        assert entry.bank_type == "SMB"
        assert entry.smb_id == "smb-001"

    @pytest.mark.asyncio
    async def test_inactive_entry_not_returned(self):
        """lookup_ifsc with active_only=True (default) must skip INACTIVE entries."""
        repo, db = _make_repo(fetchrow_return=None)  # DB returns nothing
        entry = await repo.lookup_ifsc("saraswat-coop", "SARB0000099")
        assert entry is None

    @pytest.mark.asyncio
    async def test_bank_id_is_always_scoped(self):
        """Query must always include bank_id — multi-tenant isolation."""
        row = _make_row()
        repo, db = _make_repo(fetchrow_return=row)
        await repo.lookup_ifsc("saraswat-coop", "SARB0000001")
        call_args = db.fetchrow.call_args
        # The query string (first positional arg) must contain $bank_id param
        query = call_args[0][0]
        assert "bank_id" in query


# ── list_ifsc ─────────────────────────────────────────────────────────────────

class TestListIFSC:
    @pytest.mark.asyncio
    async def test_returns_all_active_for_bank(self):
        rows = [_make_row(), _make_row(ifsc_code="SARB0000002", id="uuid-002")]
        repo, _ = _make_repo(rows=rows)
        entries = await repo.list_ifsc("saraswat-coop")
        assert len(entries) == 2

    @pytest.mark.asyncio
    async def test_filter_by_bank_type_sb(self):
        rows = [_make_row()]
        repo, db = _make_repo(rows=rows)
        entries = await repo.list_ifsc("saraswat-coop", bank_type="SB")
        assert len(entries) == 1
        query = db.fetch.call_args[0][0]
        assert "bank_type" in query

    @pytest.mark.asyncio
    async def test_filter_by_smb_id(self):
        rows = [_make_row(bank_type="SMB", smb_id="smb-001")]
        repo, db = _make_repo(rows=rows)
        entries = await repo.list_ifsc("saraswat-coop", smb_id="smb-001")
        assert len(entries) == 1
        query = db.fetch.call_args[0][0]
        assert "smb_id" in query

    @pytest.mark.asyncio
    async def test_empty_list_when_no_entries(self):
        repo, _ = _make_repo(rows=[])
        entries = await repo.list_ifsc("other-bank")
        assert entries == []

    @pytest.mark.asyncio
    async def test_include_pending_when_active_only_false(self):
        rows = [_make_row(status="PENDING", is_active=False)]
        repo, db = _make_repo(rows=rows)
        entries = await repo.list_ifsc("saraswat-coop", active_only=False)
        assert len(entries) == 1


# ── create_ifsc ───────────────────────────────────────────────────────────────

class TestCreateIFSC:
    @pytest.mark.asyncio
    async def test_creates_entry_with_pending_status(self):
        from modules.cts.ifsc.models import IFSCCreateRequest
        new_row = _make_row(status="PENDING", is_active=False, approved_by=None)
        repo, db = _make_repo(fetchrow_return=new_row)
        req = IFSCCreateRequest(
            bank_type="SB",
            smb_id=None,
            ifsc_code="SARB0000099",
            branch_name="Test Branch",
            branch_city="Pune",
            micr_code="411084001",
            effective_from=date(2026, 7, 30),
        )
        entry = await repo.create_ifsc("saraswat-coop", req, created_by="ops@saraswat.in")
        assert entry.status == "PENDING"
        assert db.fetchrow.called

    @pytest.mark.asyncio
    async def test_smb_entry_requires_smb_id(self):
        from modules.cts.ifsc.models import IFSCCreateRequest
        new_row = _make_row(bank_type="SMB", smb_id="smb-001", status="PENDING")
        repo, _ = _make_repo(fetchrow_return=new_row)
        req = IFSCCreateRequest(
            bank_type="SMB",
            smb_id="smb-001",
            ifsc_code="SOMU0000099",  # 4 alpha + 7 alphanumeric = 11 chars
            branch_name="SMB Branch",
            branch_city="Kolhapur",
        )
        entry = await repo.create_ifsc("saraswat-coop", req, created_by="ops@saraswat.in")
        assert entry.bank_type == "SMB"
        assert entry.smb_id == "smb-001"


# ── approve_ifsc ──────────────────────────────────────────────────────────────

class TestApproveIFSC:
    @pytest.mark.asyncio
    async def test_sets_status_active_and_approved_by(self):
        approved_row = _make_row(status="ACTIVE", approved_by="itadmin@saraswat.in")
        repo, db = _make_repo(fetchrow_return=approved_row)
        entry = await repo.approve_ifsc("uuid-001", approved_by="itadmin@saraswat.in")
        assert entry.status == "ACTIVE"
        assert entry.approved_by == "itadmin@saraswat.in"
        assert db.fetchrow.called

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        repo, _ = _make_repo(fetchrow_return=None)
        entry = await repo.approve_ifsc("nonexistent-uuid", approved_by="itadmin@saraswat.in")
        assert entry is None


# ── deactivate_ifsc ───────────────────────────────────────────────────────────

class TestDeactivateIFSC:
    @pytest.mark.asyncio
    async def test_sets_status_inactive(self):
        deactivated_row = _make_row(status="INACTIVE", is_active=False)
        repo, db = _make_repo(fetchrow_return=deactivated_row)
        entry = await repo.deactivate_ifsc("uuid-001", updated_by="itadmin@saraswat.in")
        assert entry.status == "INACTIVE"
        assert entry.is_active is False

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        repo, _ = _make_repo(fetchrow_return=None)
        entry = await repo.deactivate_ifsc("ghost-uuid", updated_by="itadmin@saraswat.in")
        assert entry is None
