"""
Tests for modules/msv/mandates/models.py — mandate data models.

Covers: model construction, frozen enforcement, enum values,
field defaults, and validation constraints.
"""
import pytest
from pydantic import ValidationError

from modules.msv.mandates.models import (
    AccountMandateMeta,
    MSVInput,
    MSVOutcome,
    MSVOutput,
    MandateRule,
    MandateRuleType,
    MatchedSignatory,
    SignatoryRecord,
)


class TestMandateRuleType:
    def test_all_variants_present(self):
        assert MandateRuleType.ALL_OF == "ALL_OF"
        assert MandateRuleType.ANY_N_OF == "ANY_N_OF"
        assert MandateRuleType.MANDATORY_PLUS_QUORUM == "MANDATORY_PLUS_QUORUM"
        assert MandateRuleType.THRESHOLD_SPLIT == "THRESHOLD_SPLIT"
        assert MandateRuleType.ROLE_BASED == "ROLE_BASED"

    def test_enum_is_string(self):
        assert isinstance(MandateRuleType.ALL_OF, str)


class TestMSVOutcome:
    def test_all_variants_present(self):
        assert MSVOutcome.GREEN == "GREEN"
        assert MSVOutcome.AMBER == "AMBER"
        assert MSVOutcome.RED == "RED"

    def test_outcome_is_string(self):
        assert isinstance(MSVOutcome.GREEN, str)


class TestSignatoryRecord:
    def test_basic_construction(self):
        rec = SignatoryRecord(
            signatory_id="sig-001",
            role="CFO",
            name_masked="P***",
            specimen_count=3,
            embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
        )
        assert rec.signatory_id == "sig-001"
        assert rec.role == "CFO"
        assert rec.name_masked == "P***"
        assert rec.specimen_count == 3
        assert len(rec.embeddings) == 2

    def test_frozen_model(self):
        rec = SignatoryRecord(
            signatory_id="sig-001",
            role="CFO",
            name_masked="P***",
            specimen_count=3,
            embeddings=[],
        )
        with pytest.raises(Exception):
            rec.role = "DIRECTOR"

    def test_empty_embeddings_allowed(self):
        rec = SignatoryRecord(
            signatory_id="sig-001",
            role="CFO",
            name_masked="P***",
            specimen_count=0,
            embeddings=[],
        )
        assert rec.embeddings == []

    def test_512_dim_embeddings(self):
        embedding = [0.0] * 512
        rec = SignatoryRecord(
            signatory_id="sig-001",
            role="CFO",
            name_masked="P***",
            specimen_count=1,
            embeddings=[embedding],
        )
        assert len(rec.embeddings[0]) == 512


class TestMandateRule:
    def test_all_of_default_construction(self):
        rule = MandateRule(rule_type=MandateRuleType.ALL_OF)
        assert rule.rule_type == MandateRuleType.ALL_OF
        assert rule.mandatory_ids == []
        assert rule.required_count == 1
        assert rule.required_roles == []
        assert rule.min_score == 0.80

    def test_any_n_of_with_count(self):
        rule = MandateRule(
            rule_type=MandateRuleType.ANY_N_OF,
            required_count=2,
        )
        assert rule.required_count == 2

    def test_mandatory_plus_quorum(self):
        rule = MandateRule(
            rule_type=MandateRuleType.MANDATORY_PLUS_QUORUM,
            mandatory_ids=["sig-md"],
            required_count=1,
        )
        assert "sig-md" in rule.mandatory_ids
        assert rule.required_count == 1

    def test_frozen_model(self):
        rule = MandateRule(rule_type=MandateRuleType.ALL_OF)
        with pytest.raises(Exception):
            rule.required_count = 5

    def test_custom_min_score(self):
        rule = MandateRule(rule_type=MandateRuleType.ALL_OF, min_score=0.92)
        assert rule.min_score == 0.92

    def test_role_based_with_roles(self):
        rule = MandateRule(
            rule_type=MandateRuleType.ROLE_BASED,
            required_roles=["CFO", "DIRECTOR"],
            required_count=2,
        )
        assert "CFO" in rule.required_roles
        assert "DIRECTOR" in rule.required_roles


class TestAccountMandateMeta:
    def _make(self):
        return AccountMandateMeta(
            account_hash="abc123" * 10,
            bank_id="kotak-mah",
            operation_type="J",
            mandate=MandateRule(rule_type=MandateRuleType.ALL_OF),
            signatories=[
                SignatoryRecord(
                    signatory_id="sig-001",
                    role="CFO",
                    name_masked="P***",
                    specimen_count=3,
                    embeddings=[[0.1] * 512],
                )
            ],
        )

    def test_basic_construction(self):
        meta = self._make()
        assert meta.bank_id == "kotak-mah"
        assert meta.operation_type == "J"
        assert len(meta.signatories) == 1

    def test_frozen_model(self):
        meta = self._make()
        with pytest.raises(Exception):
            meta.bank_id = "other-bank"

    def test_empty_signatories(self):
        meta = AccountMandateMeta(
            account_hash="abc123",
            bank_id="kotak-mah",
            operation_type="J",
            mandate=MandateRule(rule_type=MandateRuleType.ALL_OF),
            signatories=[],
        )
        assert meta.signatories == []


class TestMSVInput:
    def test_basic_construction(self):
        inp = MSVInput(
            instrument_id="CHQ-001",
            bank_id="kotak-mah",
            account_number="1234567890",
            cheque_image_url="minio://bucket/img.jpg",
        )
        assert inp.instrument_id == "CHQ-001"
        assert inp.bank_id == "kotak-mah"
        assert inp.account_number == "1234567890"
        assert inp.cheque_image_url == "minio://bucket/img.jpg"

    def test_frozen_model(self):
        inp = MSVInput(
            instrument_id="CHQ-001",
            bank_id="kotak-mah",
            account_number="1234567890",
            cheque_image_url="minio://bucket/img.jpg",
        )
        with pytest.raises(Exception):
            inp.bank_id = "other"


class TestMatchedSignatory:
    def test_basic_construction(self):
        m = MatchedSignatory(
            signatory_id="sig-001",
            role="CFO",
            name_masked="P***",
            best_score=0.95,
            specimen_idx=1,
        )
        assert m.signatory_id == "sig-001"
        assert m.best_score == 0.95
        assert m.specimen_idx == 1

    def test_frozen_model(self):
        m = MatchedSignatory(
            signatory_id="sig-001",
            role="CFO",
            name_masked="P***",
            best_score=0.95,
            specimen_idx=0,
        )
        with pytest.raises(Exception):
            m.best_score = 0.5


class TestMSVOutput:
    def test_basic_construction(self):
        out = MSVOutput(
            outcome=MSVOutcome.GREEN,
            confidence=0.95,
            reason_code="ALL_MATCHED",
            reason_message="All signatories matched.",
            matched_signatories=[],
            detected_sig_count=2,
            mandate_rule_type="ALL_OF",
        )
        assert out.outcome == MSVOutcome.GREEN
        assert out.confidence == 0.95
        assert out.detected_sig_count == 2

    def test_frozen_model(self):
        out = MSVOutput(
            outcome=MSVOutcome.RED,
            confidence=0.10,
            reason_code="MISSING_SIGNATORY",
            reason_message="Required signatory absent.",
            matched_signatories=[],
            detected_sig_count=1,
            mandate_rule_type="ALL_OF",
        )
        with pytest.raises(Exception):
            out.outcome = MSVOutcome.GREEN

    def test_amber_outcome_accepted(self):
        out = MSVOutput(
            outcome=MSVOutcome.AMBER,
            confidence=0.82,
            reason_code="LOW_CONFIDENCE",
            reason_message="Match score below high-confidence threshold.",
            matched_signatories=[
                MatchedSignatory(
                    signatory_id="sig-001",
                    role="CFO",
                    name_masked="P***",
                    best_score=0.84,
                    specimen_idx=0,
                )
            ],
            detected_sig_count=1,
            mandate_rule_type="ALL_OF",
        )
        assert out.outcome == MSVOutcome.AMBER
        assert len(out.matched_signatories) == 1
