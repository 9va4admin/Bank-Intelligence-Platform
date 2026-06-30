# Tests for MICRPrefixRouter are in test_sub_member.py (consolidated)
# This file covers lines not reached there.
from tests.modules.cts.sub_member.test_sub_member import *  # noqa: F401,F403
import pytest


def _make_smb(prefix="400002"):
    from modules.cts.sub_member.models import SubMemberBank
    return SubMemberBank(
        sub_member_id="vasavi-coop",
        bank_name="Vasavi Co-op",
        sponsor_bank_id="SVCB-001",
        micr_prefix=prefix,
        ifsc_prefix="VASB",
        branch_manager_email="bm@vasavi.bank",
        ops_head_email="ops@vasavi.bank",
        gm_email="gm@vasavi.bank",
        return_rate_threshold=0.15,
        soft_hold_threshold=0.25,
    )


class TestMICRPrefixRouterMissingBranches:
    def test_identify_no_routing_number_returns_direct(self):
        """Covers line 30: empty MICR band → PrincipalTag.DIRECT, None."""
        from modules.cts.sub_member.router import MICRPrefixRouter
        from modules.cts.sub_member.models import PrincipalTag
        router = MICRPrefixRouter({})
        tag, smb = router.identify("")
        assert tag == PrincipalTag.DIRECT
        assert smb is None

    def test_extract_routing_number_fallback_token(self):
        """Covers lines 51-52: no transit symbol → falls back to first token."""
        from modules.cts.sub_member.router import MICRPrefixRouter
        router = MICRPrefixRouter({})
        result = router._extract_routing_number("400002 123456")
        assert result == "400002"

    def test_extract_routing_number_empty_band_returns_none(self):
        """Covers line 52 else: whitespace-only band → None."""
        from modules.cts.sub_member.router import MICRPrefixRouter
        router = MICRPrefixRouter({})
        result = router._extract_routing_number("   ")
        assert result is None

    @pytest.mark.asyncio
    async def test_from_config_service_success(self):
        """Covers lines 68-75: from_config_service happy path builds table."""
        from modules.cts.sub_member.router import MICRPrefixRouter
        from modules.cts.sub_member.models import PrincipalTag
        from unittest.mock import AsyncMock
        smb = _make_smb("400002")
        mock_cfg = AsyncMock()
        mock_cfg.get = AsyncMock(return_value={
            "400002": {
                "sub_member_id": smb.sub_member_id,
                "bank_name": smb.bank_name,
                "sponsor_bank_id": smb.sponsor_bank_id,
                "micr_prefix": smb.micr_prefix,
                "ifsc_prefix": smb.ifsc_prefix,
                "branch_manager_email": smb.branch_manager_email,
                "ops_head_email": smb.ops_head_email,
                "gm_email": smb.gm_email,
                "return_rate_threshold": smb.return_rate_threshold,
                "soft_hold_threshold": smb.soft_hold_threshold,
            }
        })
        router = await MICRPrefixRouter.from_config_service("test-bank", mock_cfg)
        assert router.lookup("400002") is not None

    @pytest.mark.asyncio
    async def test_from_config_service_exception_returns_empty_router(self):
        """Covers lines 76-82: config exception → empty router, logs warning."""
        from modules.cts.sub_member.router import MICRPrefixRouter
        from modules.cts.sub_member.models import PrincipalTag
        from unittest.mock import AsyncMock
        mock_cfg = AsyncMock()
        mock_cfg.get = AsyncMock(side_effect=RuntimeError("config service down"))
        router = await MICRPrefixRouter.from_config_service("test-bank", mock_cfg)
        tag, smb = router.identify("400002⑆")
        assert tag == PrincipalTag.DIRECT
        assert smb is None


class TestSubMemberModelsMissingBranches:
    def test_stp_rate_zero_when_total_received_zero(self):
        """Covers line 61: stp_rate returns 0.0 when total_received is zero."""
        from modules.cts.sub_member.models import SubMemberBatchLedger
        ledger = SubMemberBatchLedger(
            sub_member_id="vasavi-coop",
            session_date="2026-06-24",
            clearing_session="MORNING",
            total_received=0,
            stp_pass=0,
        )
        assert ledger.stp_rate == 0.0


class TestSubMemberActivitiesMissingBranches:
    @pytest.mark.asyncio
    async def test_shield_status_soft_hold_sets_risk_event(self):
        """Covers lines 133-135: SOFT_HOLD → risk_event_id, immudb_event_written."""
        from modules.cts.sub_member.activities import check_return_rate_shield
        result = await check_return_rate_shield(
            bank_id="test-bank",
            sub_member_id="vasavi-coop",
            session_date="2026-06-24",
            clearing_session="MORNING",
            mock_shield_status="SOFT_HOLD",
        )
        assert result["risk_event_id"].startswith("RISK-")
        assert result["immudb_event_written"] is True
        assert result["escalation_queued"] is False

    @pytest.mark.asyncio
    async def test_shield_status_hard_stop_sets_escalation(self):
        """Covers lines 137-138: HARD_STOP → escalation_queued."""
        from modules.cts.sub_member.activities import check_return_rate_shield
        result = await check_return_rate_shield(
            bank_id="test-bank",
            sub_member_id="vasavi-coop",
            session_date="2026-06-24",
            clearing_session="MORNING",
            mock_shield_status="HARD_STOP",
        )
        assert result["escalation_queued"] is True
        assert result["immudb_event_written"] is True
