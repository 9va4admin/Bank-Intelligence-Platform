"""
VisionAIKillSwitch — RBI-mandated operational kill-switch for CTS Vision AI.

Two modes:
  KP (Kill Partial)  — Vision AI (Qwen2-VL) still runs; STP decisions suppressed.
                        All outcomes forced to HUMAN_REVIEW at synthesise_decision.
                        Use when AI behaviour is suspicious but you still want
                        advisory scores visible to the human reviewer.

  KC (Kill Complete) — Vision AI (Qwen2-VL) bypassed entirely at detect_alteration.
                        No Qwen2-VL call made; no GPU cycles consumed.
                        Cheque reaches human review with only OCR + MICR data.
                        Use when Vision AI is clearly misbehaving.

Three scopes (most restrictive wins):
  GLOBAL  — affects ALL instruments (SB own + every SMB under this ASTRA instance)
  SB_OWN  — affects only the Sponsor Bank's own instruments; SMBs unaffected
  SMB     — affects one specific Sub-Member Bank only; SB own + other SMBs unaffected

Hierarchy: NONE < KP < KC
  If global=KC and smb-specific=KP → effective mode is KC (global is more restrictive).
  If global=KP and smb-specific=KC → effective mode is KC (smb is more restrictive).
  Most specific scope that produced the effective mode is reported for audit trail.

Config keys (Layer 3 — hot-reload, maker-checker, Immudb-audited):
  cts.vision_ai.kill_mode.global          → "NONE" | "KP" | "KC"
  cts.vision_ai.kill_mode.sb_own          → "NONE" | "KP" | "KC"
  cts.vision_ai.kill_mode.smb.{smb_id}   → "NONE" | "KP" | "KC"

Missing key is treated as NONE (fail-open: never restrict AI when config is absent).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import structlog

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Public enums and status dataclass
# ---------------------------------------------------------------------------

_MODE_ORDER: dict[str, int] = {"NONE": 0, "KP": 1, "KC": 2}


class KillMode(str, Enum):
    NONE = "NONE"
    KP = "KP"
    KC = "KC"


class KillScope(str, Enum):
    GLOBAL = "GLOBAL"
    SB_OWN = "SB_OWN"
    SMB = "SMB"


@dataclass(frozen=True)
class KillSwitchStatus:
    mode: KillMode
    scope: Optional[KillScope] = None
    smb_id: Optional[str] = None  # populated only when scope == SMB

    @property
    def is_active(self) -> bool:
        return self.mode != KillMode.NONE

    @property
    def blocks_vision_ai(self) -> bool:
        """KC only — Qwen2-VL call must be skipped."""
        return self.mode == KillMode.KC

    @property
    def blocks_stp(self) -> bool:
        """KP and KC both block STP — all outcomes forced to HUMAN_REVIEW."""
        return self.mode in (KillMode.KP, KillMode.KC)


# ---------------------------------------------------------------------------
# Kill-switch checker
# ---------------------------------------------------------------------------

class VisionAIKillSwitch:
    """
    Resolve the effective kill-switch mode for a given instrument.

    Accepts any object with an async `get(key: str) -> str` method — typically
    the config_service singleton, but a mock in tests.
    """

    def __init__(self, config_service) -> None:
        self._config = config_service

    async def check(
        self,
        bank_id: str,
        smb_id: Optional[str] = None,
    ) -> KillSwitchStatus:
        """
        Return the effective KillSwitchStatus for this instrument.

        smb_id=None  → SB's own instrument → global vs sb_own compared
        smb_id set   → SMB instrument      → global vs smb-specific compared
        """
        global_mode = await self._safe_get_mode("cts.vision_ai.kill_mode.global")

        if smb_id is not None:
            return await self._resolve_smb(global_mode, smb_id)
        return await self._resolve_sb_own(global_mode, bank_id)

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    async def _resolve_sb_own(self, global_mode: KillMode, bank_id: str) -> KillSwitchStatus:
        sb_own_mode = await self._safe_get_mode("cts.vision_ai.kill_mode.sb_own")
        effective = _more_restrictive(global_mode, sb_own_mode)

        if effective == KillMode.NONE:
            return KillSwitchStatus(mode=KillMode.NONE)

        # Report the scope that produced the effective (most restrictive) mode.
        # When both are equally restrictive, prefer SB_OWN (more specific).
        if _MODE_ORDER[sb_own_mode.value] >= _MODE_ORDER[global_mode.value]:
            scope = KillScope.SB_OWN
        else:
            scope = KillScope.GLOBAL

        log.info(
            "kill_switch.resolved",
            scope=scope.value,
            mode=effective.value,
            bank_id=bank_id,
        )
        return KillSwitchStatus(mode=effective, scope=scope)

    async def _resolve_smb(self, global_mode: KillMode, smb_id: str) -> KillSwitchStatus:
        smb_mode = await self._safe_get_mode(f"cts.vision_ai.kill_mode.smb.{smb_id}")
        effective = _more_restrictive(global_mode, smb_mode)

        if effective == KillMode.NONE:
            return KillSwitchStatus(mode=KillMode.NONE)

        # Report the scope that produced the effective mode.
        # When both are equally restrictive, prefer SMB (more specific).
        if _MODE_ORDER[smb_mode.value] >= _MODE_ORDER[global_mode.value]:
            scope = KillScope.SMB
            reported_smb_id = smb_id
        else:
            scope = KillScope.GLOBAL
            reported_smb_id = None

        log.info(
            "kill_switch.resolved",
            scope=scope.value,
            mode=effective.value,
            smb_id=smb_id,
        )
        return KillSwitchStatus(mode=effective, scope=scope, smb_id=reported_smb_id)

    async def _safe_get_mode(self, key: str) -> KillMode:
        """Fetch a kill mode value; return NONE on any error (fail-open)."""
        try:
            raw = await self._config.get(key)
            return KillMode(raw)
        except Exception:
            return KillMode.NONE


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _more_restrictive(a: KillMode, b: KillMode) -> KillMode:
    """Return whichever kill mode is more restrictive (higher in NONE < KP < KC)."""
    return a if _MODE_ORDER[a.value] >= _MODE_ORDER[b.value] else b
