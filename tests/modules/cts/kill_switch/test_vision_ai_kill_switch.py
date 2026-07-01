"""
Tests for modules/cts/kill_switch/vision_ai_kill_switch.py

Kill-switch hierarchy:
  NONE  < KP (Kill Partial)  < KC (Kill Complete)
  Most restrictive mode wins across scopes.

Scopes:
  GLOBAL  — all instruments processed by this ASTRA instance (SB own + every SMB)
  SB_OWN  — only SB's own instruments (not its SMBs)
  SMB     — one specific SMB only

Resolution for SB instrument  (smb_id=None):   max(global, sb_own)
Resolution for SMB instrument (smb_id set):     max(global, smb_specific)
"""
import pytest
from unittest.mock import AsyncMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(global_mode="NONE", sb_own_mode="NONE", smb_modes: dict | None = None):
    """
    Return an AsyncMock config_service with pre-set kill_mode values.

    Modes set to "NONE" simulate an unconfigured key (config_service raises an
    exception for missing keys; kill switch must default to NONE in that case).
    Uses plain Exception — no shared.config import needed in tests.
    """
    smb_modes = smb_modes or {}

    async def _get(key: str) -> str:
        if key == "cts.vision_ai.kill_mode.global":
            if global_mode == "NONE":
                raise Exception(f"Config key not found: {key}")
            return global_mode
        if key == "cts.vision_ai.kill_mode.sb_own":
            if sb_own_mode == "NONE":
                raise Exception(f"Config key not found: {key}")
            return sb_own_mode
        for smb_id, mode in smb_modes.items():
            if key == f"cts.vision_ai.kill_mode.smb.{smb_id}":
                if mode == "NONE":
                    raise Exception(f"Config key not found: {key}")
                return mode
        raise Exception(f"Config key not found: {key}")

    mock = AsyncMock()
    mock.get = AsyncMock(side_effect=_get)
    return mock


# ---------------------------------------------------------------------------
# KillMode enum and KillSwitchStatus properties
# ---------------------------------------------------------------------------

class TestKillMode:
    def test_kill_mode_values_exist(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode
        assert KillMode.NONE.value == "NONE"
        assert KillMode.KP.value == "KP"
        assert KillMode.KC.value == "KC"

    def test_kill_scope_values_exist(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillScope
        assert KillScope.GLOBAL.value == "GLOBAL"
        assert KillScope.SB_OWN.value == "SB_OWN"
        assert KillScope.SMB.value == "SMB"

    def test_status_is_active_false_for_none(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillSwitchStatus
        s = KillSwitchStatus(mode=KillMode.NONE)
        assert s.is_active is False

    def test_status_is_active_true_for_kp(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, KillSwitchStatus
        s = KillSwitchStatus(mode=KillMode.KP, scope=KillScope.GLOBAL)
        assert s.is_active is True

    def test_status_is_active_true_for_kc(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, KillSwitchStatus
        s = KillSwitchStatus(mode=KillMode.KC, scope=KillScope.GLOBAL)
        assert s.is_active is True

    def test_blocks_vision_ai_only_for_kc(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, KillSwitchStatus
        assert KillSwitchStatus(mode=KillMode.KC, scope=KillScope.GLOBAL).blocks_vision_ai is True
        assert KillSwitchStatus(mode=KillMode.KP, scope=KillScope.GLOBAL).blocks_vision_ai is False
        assert KillSwitchStatus(mode=KillMode.NONE).blocks_vision_ai is False

    def test_blocks_stp_for_kp_and_kc(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, KillSwitchStatus
        assert KillSwitchStatus(mode=KillMode.KP, scope=KillScope.GLOBAL).blocks_stp is True
        assert KillSwitchStatus(mode=KillMode.KC, scope=KillScope.GLOBAL).blocks_stp is True
        assert KillSwitchStatus(mode=KillMode.NONE).blocks_stp is False


# ---------------------------------------------------------------------------
# No kill-switch active
# ---------------------------------------------------------------------------

class TestNoKillSwitch:
    @pytest.mark.asyncio
    async def test_all_none_returns_none_mode_for_sb_instrument(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config())
        status = await ks.check(bank_id="sbi", smb_id=None)
        assert status.mode == KillMode.NONE
        assert status.is_active is False

    @pytest.mark.asyncio
    async def test_all_none_returns_none_mode_for_smb_instrument(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config())
        status = await ks.check(bank_id="sbi", smb_id="ucb-001")
        assert status.mode == KillMode.NONE
        assert status.is_active is False

    @pytest.mark.asyncio
    async def test_missing_config_key_defaults_to_none(self):
        """ConfigKeyNotFoundError from config_service == kill switch not configured == NONE."""
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config())
        status = await ks.check(bank_id="hdfc", smb_id=None)
        assert status.mode == KillMode.NONE


# ---------------------------------------------------------------------------
# GLOBAL scope
# ---------------------------------------------------------------------------

class TestGlobalKillSwitch:
    @pytest.mark.asyncio
    async def test_global_kp_applies_to_sb_instrument(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config(global_mode="KP"))
        status = await ks.check(bank_id="sbi", smb_id=None)
        assert status.mode == KillMode.KP
        assert status.scope == KillScope.GLOBAL

    @pytest.mark.asyncio
    async def test_global_kp_applies_to_smb_instrument(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config(global_mode="KP"))
        status = await ks.check(bank_id="sbi", smb_id="ucb-001")
        assert status.mode == KillMode.KP
        assert status.scope == KillScope.GLOBAL

    @pytest.mark.asyncio
    async def test_global_kc_applies_to_sb_instrument(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config(global_mode="KC"))
        status = await ks.check(bank_id="sbi", smb_id=None)
        assert status.mode == KillMode.KC
        assert status.scope == KillScope.GLOBAL

    @pytest.mark.asyncio
    async def test_global_kc_applies_to_smb_instrument(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config(global_mode="KC"))
        status = await ks.check(bank_id="sbi", smb_id="ucb-002")
        assert status.mode == KillMode.KC
        assert status.scope == KillScope.GLOBAL


# ---------------------------------------------------------------------------
# SB_OWN scope
# ---------------------------------------------------------------------------

class TestSBOwnKillSwitch:
    @pytest.mark.asyncio
    async def test_sb_own_kp_applies_to_sb_instrument(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config(sb_own_mode="KP"))
        status = await ks.check(bank_id="sbi", smb_id=None)
        assert status.mode == KillMode.KP
        assert status.scope == KillScope.SB_OWN

    @pytest.mark.asyncio
    async def test_sb_own_kp_does_not_apply_to_smb_instrument(self):
        """SB_OWN kill switch must not bleed into SMB instruments."""
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config(sb_own_mode="KC"))
        status = await ks.check(bank_id="sbi", smb_id="ucb-001")
        assert status.mode == KillMode.NONE

    @pytest.mark.asyncio
    async def test_sb_own_kc_applies_to_sb_instrument(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config(sb_own_mode="KC"))
        status = await ks.check(bank_id="sbi", smb_id=None)
        assert status.mode == KillMode.KC
        assert status.scope == KillScope.SB_OWN


# ---------------------------------------------------------------------------
# SMB scope
# ---------------------------------------------------------------------------

class TestSMBKillSwitch:
    @pytest.mark.asyncio
    async def test_smb_kp_applies_only_to_that_smb(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config(smb_modes={"ucb-001": "KP"}))
        status = await ks.check(bank_id="sbi", smb_id="ucb-001")
        assert status.mode == KillMode.KP
        assert status.scope == KillScope.SMB
        assert status.smb_id == "ucb-001"

    @pytest.mark.asyncio
    async def test_smb_kp_does_not_apply_to_different_smb(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config(smb_modes={"ucb-001": "KP"}))
        status = await ks.check(bank_id="sbi", smb_id="ucb-002")
        assert status.mode == KillMode.NONE

    @pytest.mark.asyncio
    async def test_smb_kc_applies_only_to_that_smb(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config(smb_modes={"ucb-001": "KC"}))
        status = await ks.check(bank_id="sbi", smb_id="ucb-001")
        assert status.mode == KillMode.KC
        assert status.scope == KillScope.SMB

    @pytest.mark.asyncio
    async def test_smb_kp_does_not_apply_to_sb_own_instrument(self):
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config(smb_modes={"ucb-001": "KC"}))
        status = await ks.check(bank_id="sbi", smb_id=None)
        assert status.mode == KillMode.NONE


# ---------------------------------------------------------------------------
# Hierarchy — most restrictive wins
# ---------------------------------------------------------------------------

class TestKillSwitchHierarchy:
    @pytest.mark.asyncio
    async def test_global_kc_beats_smb_kp_for_smb_instrument(self):
        """Global KC > SMB KP — KC is more restrictive, must win."""
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config(global_mode="KC", smb_modes={"ucb-001": "KP"}))
        status = await ks.check(bank_id="sbi", smb_id="ucb-001")
        assert status.mode == KillMode.KC
        assert status.scope == KillScope.GLOBAL

    @pytest.mark.asyncio
    async def test_smb_kc_beats_global_kp_for_smb_instrument(self):
        """SMB KC > Global KP — SMB-specific is more restrictive, must win."""
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config(global_mode="KP", smb_modes={"ucb-001": "KC"}))
        status = await ks.check(bank_id="sbi", smb_id="ucb-001")
        assert status.mode == KillMode.KC
        assert status.scope == KillScope.SMB

    @pytest.mark.asyncio
    async def test_global_kc_beats_sb_own_kp(self):
        """Global KC > SB_OWN KP — KC must win for SB instrument."""
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config(global_mode="KC", sb_own_mode="KP"))
        status = await ks.check(bank_id="sbi", smb_id=None)
        assert status.mode == KillMode.KC
        assert status.scope == KillScope.GLOBAL

    @pytest.mark.asyncio
    async def test_sb_own_kc_beats_global_kp(self):
        """SB_OWN KC > Global KP — SB_OWN is more restrictive for SB instrument."""
        from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, VisionAIKillSwitch
        ks = VisionAIKillSwitch(_make_config(global_mode="KP", sb_own_mode="KC"))
        status = await ks.check(bank_id="sbi", smb_id=None)
        assert status.mode == KillMode.KC
        assert status.scope == KillScope.SB_OWN
