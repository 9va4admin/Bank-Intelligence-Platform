"""
SignatureOrchestrator — top-level pipeline for MSV validation.

Routes cheques to single-sig or multi-sig validation based on operation_type.
Performs: detect signatures → embed → assign → BRE evaluate.

Operation type routing:
  Single-sig:  S (Savings), E (Equity), F (Fixed), A (Auto-loan)
  Multi-sig:   J (Joint), JAS (Joint-Any-Signatory), L (Limited Co.),
               T (Trust), P (Partnership)
  Unknown:     AMBER + UNKNOWN_OPERATION_TYPE

Graceful degradation:
  Detector unavailable → AMBER + DETECTOR_UNAVAILABLE
  No enrolled signatories → AMBER + NO_SIGNATORIES_ENROLLED
  Embedding model unavailable → AMBER + EMBEDDING_MODEL_UNAVAILABLE
"""
from __future__ import annotations

import structlog
from opentelemetry import trace

from modules.msv.ai.embedding_model import EmbeddingModelUnavailableError
from modules.msv.ai.signature_detector import SignatureDetectorUnavailableError
from modules.msv.mandates.assignment import assign_signatures
from modules.msv.mandates.bre_engine import BREEngine
from modules.msv.mandates.models import (
    AccountMandateMeta,
    MSVInput,
    MSVOutcome,
    MSVOutput,
)

log = structlog.get_logger()
tracer = trace.get_tracer("astra.msv.orchestrator")

_SINGLE_SIG_TYPES: frozenset[str] = frozenset({"S", "E", "F", "A"})
_MULTI_SIG_TYPES: frozenset[str] = frozenset({"J", "JAS", "L", "T", "P"})


class SignatureOrchestrator:
    """
    Main entry point for MSV validation.

    Args:
        detector:             SignatureDetector — finds signature regions on cheque image
        embedding_model:      SignatureEmbeddingModel — converts image bytes → 512-dim vector
        registry:             SignatoryRegistry — loads enrolled signatory embeddings
        bre_engine:           BREEngine — evaluates mandate rules
        single_sig_validator: Validator for single-signatory accounts (S/E/F/A)
    """

    def __init__(
        self,
        detector,
        embedding_model,
        registry,
        bre_engine: BREEngine,
        single_sig_validator,
    ) -> None:
        self._detector = detector
        self._model = embedding_model
        self._registry = registry
        self._bre = bre_engine
        self._single_sig = single_sig_validator

    async def validate(
        self,
        inp: MSVInput,
        meta: AccountMandateMeta,
    ) -> MSVOutput:
        """
        Validate cheque signatures against enrolled mandate.

        Returns:
            MSVOutput with outcome GREEN / AMBER / RED + confidence + reason
        """
        with tracer.start_as_current_span("msv.orchestrator.validate") as span:
            span.set_attribute("bank_id", inp.bank_id)
            span.set_attribute("instrument_id", inp.instrument_id)
            span.set_attribute("operation_type", meta.operation_type)

            op_type = meta.operation_type

            if op_type in _SINGLE_SIG_TYPES:
                log.info(
                    "msv.orchestrator.single_sig_route",
                    bank_id=inp.bank_id,
                    operation_type=op_type,
                )
                return await self._single_sig.validate(inp, meta)

            if op_type not in _MULTI_SIG_TYPES:
                log.warning(
                    "msv.orchestrator.unknown_operation_type",
                    bank_id=inp.bank_id,
                    operation_type=op_type,
                )
                return MSVOutput(
                    outcome=MSVOutcome.AMBER,
                    confidence=0.0,
                    reason_code="UNKNOWN_OPERATION_TYPE",
                    reason_message=f"Operation type '{op_type}' is not recognised.",
                    matched_signatories=[],
                    detected_sig_count=0,
                    mandate_rule_type=meta.mandate.rule_type.value,
                )

            # --- Multi-sig pipeline ---
            return await self._run_msv_pipeline(inp, meta, span)

    async def _run_msv_pipeline(
        self,
        inp: MSVInput,
        meta: AccountMandateMeta,
        span,
    ) -> MSVOutput:
        mandate_rule_type = meta.mandate.rule_type.value

        # Step 1: Load enrolled signatories from registry
        enrolled = meta.signatories
        if not enrolled:
            # Try registry fallback
            account_hash = await self._registry._hash_account(inp.account_number, inp.bank_id)
            enrolled = await self._registry.load_all_signatories(inp.bank_id, account_hash)

        if not enrolled:
            log.warning(
                "msv.orchestrator.no_signatories_enrolled",
                bank_id=inp.bank_id,
                instrument_id=inp.instrument_id,
            )
            return MSVOutput(
                outcome=MSVOutcome.AMBER,
                confidence=0.0,
                reason_code="NO_SIGNATORIES_ENROLLED",
                reason_message="No enrolled signatories found — routing to human review.",
                matched_signatories=[],
                detected_sig_count=0,
                mandate_rule_type=mandate_rule_type,
            )

        # Step 2: Detect signature regions on cheque image
        try:
            detected_crops: list[bytes] = await self._detector.detect(
                inp.cheque_image_url, inp.bank_id
            )
        except SignatureDetectorUnavailableError as exc:
            log.warning(
                "msv.orchestrator.detector_unavailable",
                bank_id=inp.bank_id,
                instrument_id=inp.instrument_id,
                error=str(exc),
            )
            span.set_attribute("ai.degraded", True)
            return MSVOutput(
                outcome=MSVOutcome.AMBER,
                confidence=0.0,
                reason_code="DETECTOR_MODEL_UNAVAILABLE",
                reason_message="Signature detector unavailable — routing to human review.",
                matched_signatories=[],
                detected_sig_count=0,
                mandate_rule_type=mandate_rule_type,
            )

        detected_count = len(detected_crops)
        span.set_attribute("msv.detected_sig_count", detected_count)

        # Step 3: Embed each detected signature crop
        if detected_count == 0:
            detected_embeddings: list[list[float]] = []
        else:
            detected_embeddings = []
            try:
                for crop_bytes in detected_crops:
                    embedding = await self._model.embed(crop_bytes, inp.bank_id)
                    detected_embeddings.append(embedding)
                    # crop_bytes goes out of scope — never stored
            except EmbeddingModelUnavailableError as exc:
                log.warning(
                    "msv.orchestrator.embedding_model_unavailable",
                    bank_id=inp.bank_id,
                    instrument_id=inp.instrument_id,
                    error=str(exc),
                )
                span.set_attribute("ai.degraded", True)
                return MSVOutput(
                    outcome=MSVOutcome.AMBER,
                    confidence=0.0,
                    reason_code="EMBEDDING_MODEL_UNAVAILABLE",
                    reason_message="Embedding model unavailable — routing to human review.",
                    matched_signatories=[],
                    detected_sig_count=detected_count,
                    mandate_rule_type=mandate_rule_type,
                )

        # Step 4: Greedy assignment — detected embeddings × enrolled signatory embeddings
        matched = assign_signatures(detected_embeddings, enrolled)
        span.set_attribute("msv.matched_count", len(matched))

        # Step 5: BRE evaluation
        outcome, reason_code, reason_message = self._bre.evaluate(
            mandate=meta.mandate,
            matched=matched,
            detected_count=detected_count,
            expected_signatories=enrolled,
        )

        # Confidence = mean of best_scores across matched signatories (or 0.0 if none)
        confidence = (
            sum(m.best_score for m in matched) / len(matched)
            if matched
            else 0.0
        )
        confidence = round(min(confidence, 1.0), 4)

        span.set_attribute("msv.outcome", outcome.value)
        span.set_attribute("msv.confidence", confidence)

        log.info(
            "msv.orchestrator.decision",
            bank_id=inp.bank_id,
            instrument_id=inp.instrument_id,
            outcome=outcome.value,
            confidence=confidence,
            reason_code=reason_code,
            detected_count=detected_count,
            matched_count=len(matched),
        )

        return MSVOutput(
            outcome=outcome,
            confidence=confidence,
            reason_code=reason_code,
            reason_message=reason_message,
            matched_signatories=matched,
            detected_sig_count=detected_count,
            mandate_rule_type=mandate_rule_type,
        )
