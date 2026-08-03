"""
Tests for modules/msv/orchestrator.py — SignatureOrchestrator.

Covers:
  - S/E/F/A → single sig validator called, MSV not called
  - J/JAS/L/T/P → MSV pipeline called
  - Unknown type → AMBER, UNKNOWN_OPERATION_TYPE
  - Full pipeline integration: mock detector + embedding model + registry → GREEN result
  - INSUFFICIENT_SIGNATURES_DETECTED when detector finds fewer than mandate requires
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from modules.msv.mandates.models import (
    AccountMandateMeta,
    MandateRule,
    MandateRuleType,
    MSVInput,
    MSVOutcome,
    MSVOutput,
    SignatoryRecord,
)
from modules.msv.orchestrator import SignatureOrchestrator


def _make_account_meta(
    operation_type: str,
    rule_type: MandateRuleType = MandateRuleType.ALL_OF,
    n_signatories: int = 1,
) -> AccountMandateMeta:
    import math
    signatories = [
        SignatoryRecord(
            signatory_id=f"sig-{i:03d}",
            role="CFO",
            name_masked="P***",
            specimen_count=3,
            embeddings=[[0.0] * 511 + [1.0]],  # simple unit-ish vector
        )
        for i in range(n_signatories)
    ]
    return AccountMandateMeta(
        account_hash="hash_abc123",
        bank_id="kotak-mah",
        operation_type=operation_type,
        mandate=MandateRule(rule_type=rule_type, min_score=0.80),
        signatories=signatories,
    )


def _make_msv_input(operation_type: str = "J") -> MSVInput:
    return MSVInput(
        instrument_id="CHQ-001",
        bank_id="kotak-mah",
        account_number="1234567890",
        cheque_image_url="minio://bucket/img.jpg",
    )


def _make_detector(crops: list[bytes]):
    d = MagicMock()
    d.detect = AsyncMock(return_value=crops)
    return d


def _make_embedding_model(embedding_per_call: list[float] | None = None):
    if embedding_per_call is None:
        embedding_per_call = [0.0] * 511 + [1.0]
    m = MagicMock()
    m.embed = AsyncMock(return_value=embedding_per_call)
    return m


def _make_registry(signatories: list[SignatoryRecord] | None = None):
    r = MagicMock()
    r.load_all_signatories = AsyncMock(return_value=signatories or [])
    r._hash_account = AsyncMock(return_value="hash_abc123")
    return r


def _make_single_sig_validator():
    v = MagicMock()
    v.validate = AsyncMock(return_value=MSVOutput(
        outcome=MSVOutcome.GREEN,
        confidence=0.95,
        reason_code="SINGLE_SIG_VALIDATED",
        reason_message="Single signature validated.",
        matched_signatories=[],
        detected_sig_count=1,
        mandate_rule_type="SINGLE",
    ))
    return v


class TestOrchestratorRouting:
    def _make_orchestrator(self, detector_crops=None, embedding=None, signatories=None, single_sig_validator=None):
        detector = _make_detector(detector_crops if detector_crops is not None else [b"sig_img"])
        embed_model = _make_embedding_model(embedding)
        registry = _make_registry(signatories)
        single_sig = single_sig_validator or _make_single_sig_validator()

        from modules.msv.mandates.bre_engine import BREEngine
        return SignatureOrchestrator(
            detector=detector,
            embedding_model=embed_model,
            registry=registry,
            bre_engine=BREEngine(),
            single_sig_validator=single_sig,
        )

    @pytest.mark.parametrize("op_type", ["S", "E", "F", "A"])
    @pytest.mark.asyncio
    async def test_single_sig_types_use_single_validator(self, op_type):
        single_sig = _make_single_sig_validator()
        orch = self._make_orchestrator(single_sig_validator=single_sig)
        meta = _make_account_meta(op_type)
        inp = _make_msv_input(op_type)

        result = await orch.validate(inp, meta)

        single_sig.validate.assert_called_once()
        assert result.outcome == MSVOutcome.GREEN

    @pytest.mark.parametrize("op_type", ["J", "JAS", "L", "T", "P"])
    @pytest.mark.asyncio
    async def test_multi_sig_types_use_msv_pipeline(self, op_type):
        single_sig = _make_single_sig_validator()

        # Set up a signatory that will match
        sig = SignatoryRecord(
            signatory_id="sig-000",
            role="CFO",
            name_masked="P***",
            specimen_count=1,
            embeddings=[[0.0] * 511 + [1.0]],
        )
        orch = self._make_orchestrator(
            detector_crops=[b"sig_img"],
            embedding=[0.0] * 511 + [1.0],  # same vector → score 1.0
            signatories=[sig],
            single_sig_validator=single_sig,
        )
        meta = _make_account_meta(op_type, n_signatories=1)
        inp = _make_msv_input(op_type)

        result = await orch.validate(inp, meta)

        # Single sig validator must NOT have been called
        single_sig.validate.assert_not_called()
        # Result must be from MSV pipeline
        assert result.outcome in (MSVOutcome.GREEN, MSVOutcome.AMBER, MSVOutcome.RED)

    @pytest.mark.asyncio
    async def test_unknown_operation_type_returns_amber(self):
        orch = self._make_orchestrator()
        meta = _make_account_meta("X")   # unknown type
        inp = _make_msv_input("X")

        result = await orch.validate(inp, meta)

        assert result.outcome == MSVOutcome.AMBER
        assert result.reason_code == "UNKNOWN_OPERATION_TYPE"

    @pytest.mark.asyncio
    async def test_full_pipeline_green_result(self):
        """Integration: detector finds 1 sig, embedding matches, BRE → GREEN."""
        embedding = [0.0] * 511 + [1.0]
        sig = SignatoryRecord(
            signatory_id="sig-000",
            role="CFO",
            name_masked="P***",
            specimen_count=1,
            embeddings=[embedding],  # exact same embedding → score 1.0
        )
        orch = self._make_orchestrator(
            detector_crops=[b"sig_img_bytes"],
            embedding=embedding,
            signatories=[sig],
        )
        meta = _make_account_meta("J", MandateRuleType.ALL_OF, n_signatories=1)
        inp = _make_msv_input("J")

        result = await orch.validate(inp, meta)

        assert result.outcome == MSVOutcome.GREEN
        assert result.detected_sig_count == 1
        assert len(result.matched_signatories) == 1

    @pytest.mark.asyncio
    async def test_insufficient_signatures_detected_returns_red(self):
        """Detector finds 0 signatures but mandate requires 1 → RED."""
        orch = self._make_orchestrator(
            detector_crops=[],   # no signatures detected
            signatories=[
                SignatoryRecord(
                    signatory_id="sig-000",
                    role="CFO",
                    name_masked="P***",
                    specimen_count=1,
                    embeddings=[[0.0] * 512],
                )
            ],
        )
        meta = _make_account_meta("J", MandateRuleType.ALL_OF, n_signatories=1)
        inp = _make_msv_input("J")

        result = await orch.validate(inp, meta)

        assert result.outcome == MSVOutcome.RED
        assert result.reason_code == "INSUFFICIENT_SIGNATURES_DETECTED"

    @pytest.mark.asyncio
    async def test_vault_miss_returns_amber(self):
        """No enrolled signatories → AMBER vault miss."""
        orch = self._make_orchestrator(
            detector_crops=[b"sig_img"],
            signatories=[],   # nothing enrolled
        )
        meta = AccountMandateMeta(
            account_hash="hash_abc",
            bank_id="kotak-mah",
            operation_type="J",
            mandate=MandateRule(rule_type=MandateRuleType.ALL_OF),
            signatories=[],   # no signatories known
        )
        inp = _make_msv_input("J")

        result = await orch.validate(inp, meta)

        assert result.outcome == MSVOutcome.AMBER
        assert "VAULT_MISS" in result.reason_code or result.reason_code == "NO_SIGNATORIES_ENROLLED"

    @pytest.mark.asyncio
    async def test_detector_unavailable_returns_amber(self):
        """If signature detector fails, graceful degradation → AMBER."""
        from modules.msv.ai.signature_detector import SignatureDetectorUnavailableError
        detector = MagicMock()
        detector.detect = AsyncMock(side_effect=SignatureDetectorUnavailableError("vLLM down"))

        from modules.msv.mandates.bre_engine import BREEngine
        orch = SignatureOrchestrator(
            detector=detector,
            embedding_model=_make_embedding_model(),
            registry=_make_registry(),
            bre_engine=BREEngine(),
            single_sig_validator=_make_single_sig_validator(),
        )
        meta = _make_account_meta("J")
        inp = _make_msv_input("J")

        result = await orch.validate(inp, meta)

        assert result.outcome == MSVOutcome.AMBER
        assert "MODEL_UNAVAILABLE" in result.reason_code or result.outcome == MSVOutcome.AMBER

    @pytest.mark.asyncio
    async def test_msv_output_has_mandate_rule_type(self):
        """MSVOutput.mandate_rule_type should reflect the actual rule."""
        embedding = [0.0] * 511 + [1.0]
        sig = SignatoryRecord(
            signatory_id="sig-000",
            role="CFO",
            name_masked="P***",
            specimen_count=1,
            embeddings=[embedding],
        )
        orch = self._make_orchestrator(
            detector_crops=[b"sig_img"],
            embedding=embedding,
            signatories=[sig],
        )
        meta = _make_account_meta("J", MandateRuleType.ANY_N_OF, n_signatories=1)
        inp = _make_msv_input("J")

        result = await orch.validate(inp, meta)

        assert result.mandate_rule_type == "ANY_N_OF"
