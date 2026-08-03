"""
Phase E — Allocation mode tests.

AllocationService wraps LockService and applies the configured allocation_mode
(SELF | HYBRID | AUTO) to determine whether a reviewer may claim an instrument
and how auto-assignment works.
"""
import pytest
from unittest.mock import AsyncMock


def _make_lock_service(locked_by=None):
    svc = AsyncMock()
    svc.acquire_lock = AsyncMock(return_value=locked_by is None or locked_by == "reviewer-1")
    svc.release_lock = AsyncMock()
    svc.get_lock_holder = AsyncMock(return_value=locked_by)
    return svc


def _cfg(mode="SELF", lock_ttl=10):
    return {"allocation_mode": mode, "allocation_lock_ttl_minutes": lock_ttl}


# ---------------------------------------------------------------------------
# 1. AllocationService importable
# ---------------------------------------------------------------------------

class TestAllocationServiceInit:
    def test_allocation_service_importable(self):
        from modules.cts.allocation.allocation_service import AllocationService
        assert AllocationService is not None

    def test_allocation_service_instantiable(self):
        from modules.cts.allocation.allocation_service import AllocationService
        lock_svc = _make_lock_service()
        svc = AllocationService(lock_service=lock_svc)
        assert svc is not None


# ---------------------------------------------------------------------------
# 2. SELF mode — reviewer must actively claim
# ---------------------------------------------------------------------------

class TestSelfMode:
    @pytest.mark.asyncio
    async def test_self_mode_claim_succeeds(self):
        from modules.cts.allocation.allocation_service import AllocationService
        lock_svc = _make_lock_service()
        svc = AllocationService(lock_service=lock_svc)
        result = await svc.claim("INST001", "reviewer-1", _cfg("SELF"))
        assert result.claimed is True
        assert result.reviewer_id == "reviewer-1"

    @pytest.mark.asyncio
    async def test_self_mode_claim_fails_when_locked_by_other(self):
        from modules.cts.allocation.allocation_service import AllocationService
        lock_svc = AsyncMock()
        lock_svc.acquire_lock = AsyncMock(return_value=False)
        lock_svc.get_lock_holder = AsyncMock(return_value="reviewer-1")
        svc = AllocationService(lock_service=lock_svc)
        result = await svc.claim("INST001", "reviewer-2", _cfg("SELF"))
        assert result.claimed is False
        assert result.held_by == "reviewer-1"

    @pytest.mark.asyncio
    async def test_self_mode_unclaim_releases_lock(self):
        from modules.cts.allocation.allocation_service import AllocationService
        lock_svc = _make_lock_service()
        svc = AllocationService(lock_service=lock_svc)
        await svc.unclaim("INST001", "reviewer-1", _cfg("SELF"))
        lock_svc.release_lock.assert_awaited_once_with("INST001", "reviewer-1")


# ---------------------------------------------------------------------------
# 3. HYBRID mode — claim OR auto-assign after timeout
# ---------------------------------------------------------------------------

class TestHybridMode:
    @pytest.mark.asyncio
    async def test_hybrid_mode_manual_claim_succeeds(self):
        from modules.cts.allocation.allocation_service import AllocationService
        lock_svc = _make_lock_service()
        svc = AllocationService(lock_service=lock_svc)
        result = await svc.claim("INST001", "reviewer-1", _cfg("HYBRID"))
        assert result.claimed is True
        assert result.reviewer_id == "reviewer-1"

    @pytest.mark.asyncio
    async def test_hybrid_mode_auto_assign_when_unclaimed(self):
        """In HYBRID, auto_assign() picks from available reviewers when unclaimed."""
        from modules.cts.allocation.allocation_service import AllocationService
        lock_svc = _make_lock_service(locked_by=None)
        svc = AllocationService(lock_service=lock_svc)
        available = ["reviewer-A", "reviewer-B", "reviewer-C"]
        result = await svc.auto_assign("INST001", available, _cfg("HYBRID"))
        assert result.claimed is True
        assert result.reviewer_id in available

    @pytest.mark.asyncio
    async def test_hybrid_mode_auto_assign_skips_already_claimed(self):
        """auto_assign must not overwrite an existing manual claim."""
        from modules.cts.allocation.allocation_service import AllocationService
        lock_svc = AsyncMock()
        lock_svc.get_lock_holder = AsyncMock(return_value="reviewer-1")
        lock_svc.acquire_lock = AsyncMock(return_value=False)
        svc = AllocationService(lock_service=lock_svc)
        result = await svc.auto_assign("INST001", ["reviewer-A"], _cfg("HYBRID"))
        assert result.claimed is False
        assert result.held_by == "reviewer-1"


# ---------------------------------------------------------------------------
# 4. AUTO mode — instruments auto-assigned; no manual claim
# ---------------------------------------------------------------------------

class TestAutoMode:
    @pytest.mark.asyncio
    async def test_auto_mode_auto_assign_picks_reviewer(self):
        from modules.cts.allocation.allocation_service import AllocationService
        lock_svc = _make_lock_service(locked_by=None)
        svc = AllocationService(lock_service=lock_svc)
        available = ["reviewer-A", "reviewer-B"]
        result = await svc.auto_assign("INST001", available, _cfg("AUTO"))
        assert result.claimed is True
        assert result.reviewer_id in available

    @pytest.mark.asyncio
    async def test_auto_mode_empty_pool_returns_unclaimed(self):
        """No reviewers available → instrument stays unclaimed, never crashes."""
        from modules.cts.allocation.allocation_service import AllocationService
        lock_svc = _make_lock_service(locked_by=None)
        svc = AllocationService(lock_service=lock_svc)
        result = await svc.auto_assign("INST001", [], _cfg("AUTO"))
        assert result.claimed is False
        assert result.reviewer_id is None


# ---------------------------------------------------------------------------
# 5. AllocationResult schema
# ---------------------------------------------------------------------------

class TestAllocationResult:
    def test_allocation_result_importable(self):
        from modules.cts.allocation.allocation_service import AllocationResult
        assert AllocationResult is not None

    def test_claimed_true_result(self):
        from modules.cts.allocation.allocation_service import AllocationResult
        r = AllocationResult(claimed=True, reviewer_id="reviewer-1")
        assert r.claimed is True
        assert r.reviewer_id == "reviewer-1"
        assert r.held_by is None

    def test_claimed_false_result(self):
        from modules.cts.allocation.allocation_service import AllocationResult
        r = AllocationResult(claimed=False, held_by="reviewer-1")
        assert r.claimed is False
        assert r.reviewer_id is None
        assert r.held_by == "reviewer-1"

    def test_unclaimed_empty_pool_result(self):
        from modules.cts.allocation.allocation_service import AllocationResult
        r = AllocationResult(claimed=False)
        assert r.claimed is False
        assert r.reviewer_id is None
        assert r.held_by is None
