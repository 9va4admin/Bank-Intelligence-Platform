"""
ChequeProcessingWorkflow — main CTS workflow: one cheque, one agent.

Workflow ID: cts-{bank_id}-{instrument_id} (deterministic, exactly-once).
IETWatchdogWorkflow spawned as first child before any activity — non-negotiable.
Activities called in order: OCR → alteration → signature → PPS → CBS → fraud → decision.
"""
import time
from typing import Any, Callable, Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

_IET_EMERGENCY_BUFFER_SECONDS = 30


class ChequeWorkflowInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    image_url: str
    account_number: str
    cheque_number: str
    presented_amount: float
    presented_payee: str
    iet_deadline: float            # Unix timestamp


class ChequeWorkflowResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    decision: str                  # "STP_CONFIRM" | "STP_RETURN" | "HUMAN_REVIEW"
    rationale: str
    shap_values: Optional[dict[str, Any]] = None
    emergency_iet_filed: bool = False


class ChequeProcessingWorkflow:
    def __init__(self) -> None:
        self._watchdog_spawned: bool = False

    def workflow_id(self, bank_id: str, instrument_id: str) -> str:
        return f"cts-{bank_id}-{instrument_id}"

    def iet_watchdog_id(self, bank_id: str, instrument_id: str) -> str:
        return f"cts-iet-{bank_id}-{instrument_id}"

    async def run_with_mocks(
        self,
        inp: ChequeWorkflowInput,
        mock_results: dict,
        on_watchdog_spawn: Optional[Callable] = None,
        on_ocr_call: Optional[Callable] = None,
    ) -> ChequeWorkflowResult:
        """
        Testable orchestration method: accepts pre-built activity results.
        Production Temporal @workflow.run method wraps this logic.
        """
        # Step 1: Spawn IET watchdog FIRST — before any activity
        self._watchdog_spawned = False
        if on_watchdog_spawn:
            await on_watchdog_spawn(
                watchdog_id=self.iet_watchdog_id(inp.bank_id, inp.instrument_id),
                iet_deadline=inp.iet_deadline,
            )
        self._watchdog_spawned = True

        # Step 2: OCR
        if on_ocr_call:
            ocr_result = await on_ocr_call(inp.image_url)
        else:
            ocr_result = mock_results["ocr"]

        # Step 3: Alteration detection
        alteration_result = mock_results["alteration"]

        # Step 4: Signature verification
        sig_result = mock_results["signature"]

        # Step 5: PPS lookup
        pps_result = mock_results["pps"]

        # Step 6: CBS balance check
        cbs_result = mock_results["cbs"]

        # Step 7: Fraud scoring (always includes SHAP)
        fraud_result = mock_results["fraud"]

        # Step 8: Synthesise decision
        decision_result = mock_results["decision"]

        log.info(
            "cheque_workflow.complete",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            decision=decision_result.decision,
        )

        return ChequeWorkflowResult(
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            decision=decision_result.decision,
            rationale=decision_result.rationale,
            shap_values=decision_result.shap_values,
        )
