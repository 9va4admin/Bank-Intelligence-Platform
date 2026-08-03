"""Tests for modules/cts/workflows/activities/kill_switch_lookup.py"""
import pytest


class _FakeConfigService:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    async def get(self, key: str) -> str:
        return self._values[key]


class TestGetKillSwitchStatus:
    @pytest.mark.asyncio
    async def test_none_mode_when_no_config_set(self):
        from modules.cts.workflows.activities.kill_switch_lookup import (
            KillSwitchLookupInput, get_kill_switch_status,
        )
        result = await get_kill_switch_status(
            KillSwitchLookupInput(bank_id="saraswat-coop"),
            config_service=_FakeConfigService({}),
        )
        assert result.mode == "NONE"
        assert result.scope is None

    @pytest.mark.asyncio
    async def test_sb_own_kc_mode_resolved(self):
        from modules.cts.workflows.activities.kill_switch_lookup import (
            KillSwitchLookupInput, get_kill_switch_status,
        )
        result = await get_kill_switch_status(
            KillSwitchLookupInput(bank_id="saraswat-coop"),
            config_service=_FakeConfigService({
                "cts.vision_ai.kill_mode.global": "NONE",
                "cts.vision_ai.kill_mode.sb_own": "KC",
            }),
        )
        assert result.mode == "KC"
        assert result.scope == "SB_OWN"

    @pytest.mark.asyncio
    async def test_global_more_restrictive_than_smb_wins(self):
        from modules.cts.workflows.activities.kill_switch_lookup import (
            KillSwitchLookupInput, get_kill_switch_status,
        )
        result = await get_kill_switch_status(
            KillSwitchLookupInput(bank_id="saraswat-coop", smb_id="smb-42"),
            config_service=_FakeConfigService({
                "cts.vision_ai.kill_mode.global": "KC",
                "cts.vision_ai.kill_mode.smb.smb-42": "KP",
            }),
        )
        assert result.mode == "KC"
        assert result.scope == "GLOBAL"

    @pytest.mark.asyncio
    async def test_smb_specific_mode_resolved_with_smb_id(self):
        from modules.cts.workflows.activities.kill_switch_lookup import (
            KillSwitchLookupInput, get_kill_switch_status,
        )
        result = await get_kill_switch_status(
            KillSwitchLookupInput(bank_id="saraswat-coop", smb_id="smb-42"),
            config_service=_FakeConfigService({
                "cts.vision_ai.kill_mode.global": "NONE",
                "cts.vision_ai.kill_mode.smb.smb-42": "KP",
            }),
        )
        assert result.mode == "KP"
        assert result.scope == "SMB"
        assert result.smb_id == "smb-42"

    @pytest.mark.asyncio
    async def test_fails_open_to_none_on_lookup_error(self):
        """config_service.get() raising must never block the workflow — the
        underlying VisionAIKillSwitch already fails open per its own docs."""
        from modules.cts.workflows.activities.kill_switch_lookup import (
            KillSwitchLookupInput, get_kill_switch_status,
        )

        class _BoomConfigService:
            async def get(self, key: str) -> str:
                raise RuntimeError("config service unreachable")

        result = await get_kill_switch_status(
            KillSwitchLookupInput(bank_id="saraswat-coop"),
            config_service=_BoomConfigService(),
        )
        assert result.mode == "NONE"
