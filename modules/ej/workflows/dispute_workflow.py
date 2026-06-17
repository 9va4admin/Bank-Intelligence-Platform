"""
DisputeResolutionWorkflow: match EJ → fetch CCTV → auto-resolve or escalate.

CCTV evidence is required before any auto-resolution decision.
Workflow ID: ej-dispute-{bank_id}-{npci_claim_id}
"""
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class EJDisputeInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    atm_id: str
    npci_claim_id: str
    claim_amount: float
    claim_timestamp: str
    claim_type: str


class EJDisputeResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                        # "AUTO_RESOLVED" | "ESCALATED_TO_HUMAN"
    bank_id: str
    npci_claim_id: str
    matched_canonical_hash: Optional[str] = None
    cctv_object_key: Optional[str] = None


class DisputeResolutionWorkflow:
    def workflow_id(self, bank_id: str, npci_claim_id: str) -> str:
        return f"ej-dispute-{bank_id}-{npci_claim_id}"

    async def run_with_mocks(
        self,
        inp: EJDisputeInput,
        mock_results: dict,
    ) -> EJDisputeResult:
        match_result = mock_results["dispute_match"]
        cctv_result = mock_results["cctv_extract"]

        # Auto-resolution requires both: EJ match AND CCTV evidence
        has_match = match_result.outcome == "MATCHED"
        has_cctv = cctv_result.outcome == "EXTRACTED"

        if has_match and has_cctv:
            log.info(
                "dispute.auto_resolved",
                claim_id=inp.npci_claim_id,
                bank_id=inp.bank_id,
                canonical_hash=match_result.matched_canonical_hash,
            )
            return EJDisputeResult(
                outcome="AUTO_RESOLVED",
                bank_id=inp.bank_id,
                npci_claim_id=inp.npci_claim_id,
                matched_canonical_hash=match_result.matched_canonical_hash,
                cctv_object_key=cctv_result.object_key,
            )

        log.info(
            "dispute.escalated",
            claim_id=inp.npci_claim_id,
            bank_id=inp.bank_id,
            has_match=has_match,
            has_cctv=has_cctv,
        )
        return EJDisputeResult(
            outcome="ESCALATED_TO_HUMAN",
            bank_id=inp.bank_id,
            npci_claim_id=inp.npci_claim_id,
            matched_canonical_hash=match_result.matched_canonical_hash if has_match else None,
            cctv_object_key=cctv_result.object_key if has_cctv else None,
        )
