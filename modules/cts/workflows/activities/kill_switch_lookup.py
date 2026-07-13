"""
Kill-switch status lookup activity — wraps VisionAIKillSwitch.check().

Unlike a stateless client binding (ngch_adapter, immudb_client, etc.), the
kill-switch mode is time-varying, per-call data: cheque_workflow.py's
dual-checkpoint design (alteration.py checkpoint 1, decision.py checkpoint 2)
depends on resolving it FRESH at each checkpoint, specifically to catch an
activation that happens mid-flight during the ~120s Vision LLM call. Reusing
one lookup across both checkpoints would defeat the backstop entirely.
"""
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from modules.cts.kill_switch.vision_ai_kill_switch import VisionAIKillSwitch

log = structlog.get_logger()


class KillSwitchLookupInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    smb_id: Optional[str] = None


class KillSwitchLookupResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    mode: str                      # "NONE" | "KP" | "KC"
    scope: Optional[str] = None    # "GLOBAL" | "SB_OWN" | "SMB"
    smb_id: Optional[str] = None


@activity.defn
async def get_kill_switch_status(
    inp: KillSwitchLookupInput,
    config_service=None,
) -> KillSwitchLookupResult:
    """
    Resolve the effective RBI kill-switch mode for this instrument.

    Fail-open on any lookup error — VisionAIKillSwitch itself already
    defaults to NONE on a missing or unreadable config key, matching the
    documented "missing key = NONE" semantics in vision_ai_kill_switch.py.
    """
    checker = VisionAIKillSwitch(config_service)
    status = await checker.check(bank_id=inp.bank_id, smb_id=inp.smb_id)
    log.info(
        "kill_switch_lookup.resolved",
        bank_id=inp.bank_id,
        smb_id=inp.smb_id,
        mode=status.mode.value,
        scope=status.scope.value if status.scope else None,
    )
    return KillSwitchLookupResult(
        mode=status.mode.value,
        scope=status.scope.value if status.scope else None,
        smb_id=status.smb_id,
    )
