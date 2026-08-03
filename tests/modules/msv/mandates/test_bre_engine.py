"""
Tests for modules/msv/mandates/bre_engine.py — Business Rules Engine.

Covers:
  - ALL_OF: all must match above threshold
  - ANY_N_OF: at least N must match
  - MANDATORY_PLUS_QUORUM: specific mandatory sigs + quorum of others
  - THRESHOLD_SPLIT: different thresholds per role
  - ROLE_BASED: match by role count, not identity
  - Pre-check: detected_count < required → RED INSUFFICIENT_SIGNATURES_DETECTED
  - Score boundary tests
"""
import pytest

from modules.msv.mandates.bre_engine import BREEngine
from modules.msv.mandates.models import (
    MandateRule,
    MandateRuleType,
    MatchedSignatory,
    MSVOutcome,
    SignatoryRecord,
)


def _make_signatory(sig_id: str, role: str = "CFO", specimen_count: int = 3) -> SignatoryRecord:
    return SignatoryRecord(
        signatory_id=sig_id,
        role=role,
        name_masked="P***",
        specimen_count=specimen_count,
        embeddings=[[0.1] * 512] * specimen_count,
    )


def _make_matched(sig_id: str, score: float, role: str = "CFO", specimen_idx: int = 0) -> MatchedSignatory:
    return MatchedSignatory(
        signatory_id=sig_id,
        role=role,
        name_masked="P***",
        best_score=score,
        specimen_idx=specimen_idx,
    )


class TestBREEngineAllOf:
    def setup_method(self):
        self.engine = BREEngine()
        self.mandate = MandateRule(rule_type=MandateRuleType.ALL_OF, min_score=0.80)
        self.signatories = [
            _make_signatory("sig-001"),
            _make_signatory("sig-002"),
        ]

    def test_all_matched_high_confidence_green(self):
        matched = [
            _make_matched("sig-001", 0.95),
            _make_matched("sig-002", 0.92),
        ]
        outcome, code, msg = self.engine.evaluate(self.mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.GREEN
        assert code == "ALL_MATCHED"

    def test_one_missing_red(self):
        matched = [_make_matched("sig-001", 0.95)]
        outcome, code, msg = self.engine.evaluate(self.mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.RED
        assert code == "MISSING_SIGNATORY"

    def test_all_missing_red(self):
        matched = []
        outcome, code, msg = self.engine.evaluate(self.mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.RED
        assert code == "MISSING_SIGNATORY"

    def test_score_below_min_red(self):
        matched = [
            _make_matched("sig-001", 0.79),   # below 0.80 min_score
            _make_matched("sig-002", 0.95),
        ]
        outcome, code, msg = self.engine.evaluate(self.mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.RED
        assert code == "SCORE_BELOW_THRESHOLD"

    def test_score_at_min_but_below_high_confidence_amber(self):
        # At min_score (0.80) but below high-confidence threshold (0.90) → AMBER
        matched = [
            _make_matched("sig-001", 0.85),   # >= 0.80 but < 0.90
            _make_matched("sig-002", 0.85),
        ]
        outcome, code, msg = self.engine.evaluate(self.mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.AMBER
        assert code == "LOW_CONFIDENCE_MATCH"

    def test_exactly_at_min_score_amber(self):
        # Exactly 0.80 — at threshold, amber (not red, not green)
        matched = [
            _make_matched("sig-001", 0.80),
            _make_matched("sig-002", 0.95),
        ]
        outcome, code, msg = self.engine.evaluate(self.mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.AMBER

    def test_exactly_at_high_confidence_green(self):
        # Exactly 0.90 — at high-confidence boundary → GREEN
        matched = [
            _make_matched("sig-001", 0.90),
            _make_matched("sig-002", 0.92),
        ]
        outcome, code, msg = self.engine.evaluate(self.mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.GREEN

    def test_just_below_high_confidence_amber(self):
        # 0.8999... — just under the GREEN threshold → AMBER
        matched = [
            _make_matched("sig-001", 0.8999),
            _make_matched("sig-002", 0.91),
        ]
        outcome, code, msg = self.engine.evaluate(self.mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.AMBER

    def test_just_below_min_score_red(self):
        # 0.7999 — just under the min threshold → RED
        matched = [
            _make_matched("sig-001", 0.7999),
            _make_matched("sig-002", 0.95),
        ]
        outcome, code, msg = self.engine.evaluate(self.mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.RED

    def test_reason_message_not_empty(self):
        matched = [_make_matched("sig-001", 0.95), _make_matched("sig-002", 0.92)]
        _, _, msg = self.engine.evaluate(self.mandate, matched, 2, self.signatories)
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_single_signatory_all_of(self):
        mandate = MandateRule(rule_type=MandateRuleType.ALL_OF, min_score=0.80)
        sig = [_make_signatory("sig-001")]
        matched = [_make_matched("sig-001", 0.93)]
        outcome, code, _ = self.engine.evaluate(mandate, matched, 1, sig)
        assert outcome == MSVOutcome.GREEN


class TestBREEngineAnyNOf:
    def setup_method(self):
        self.engine = BREEngine()
        self.signatories = [
            _make_signatory("sig-001"),
            _make_signatory("sig-002"),
            _make_signatory("sig-003"),
        ]

    def test_exactly_n_matched_green(self):
        mandate = MandateRule(rule_type=MandateRuleType.ANY_N_OF, required_count=2, min_score=0.80)
        matched = [
            _make_matched("sig-001", 0.92),
            _make_matched("sig-002", 0.91),
        ]
        outcome, code, _ = self.engine.evaluate(mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.GREEN

    def test_more_than_n_matched_green(self):
        mandate = MandateRule(rule_type=MandateRuleType.ANY_N_OF, required_count=2, min_score=0.80)
        matched = [
            _make_matched("sig-001", 0.92),
            _make_matched("sig-002", 0.91),
            _make_matched("sig-003", 0.90),
        ]
        outcome, code, _ = self.engine.evaluate(mandate, matched, 3, self.signatories)
        assert outcome == MSVOutcome.GREEN

    def test_fewer_than_n_matched_red(self):
        mandate = MandateRule(rule_type=MandateRuleType.ANY_N_OF, required_count=2, min_score=0.80)
        matched = [_make_matched("sig-001", 0.95)]
        outcome, code, _ = self.engine.evaluate(mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.RED
        assert code == "INSUFFICIENT_MATCHES"

    def test_none_matched_red(self):
        mandate = MandateRule(rule_type=MandateRuleType.ANY_N_OF, required_count=1, min_score=0.80)
        matched = []
        outcome, code, _ = self.engine.evaluate(mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.RED

    def test_n_matched_but_low_score_amber(self):
        mandate = MandateRule(rule_type=MandateRuleType.ANY_N_OF, required_count=2, min_score=0.80)
        matched = [
            _make_matched("sig-001", 0.85),  # above min but below high-confidence
            _make_matched("sig-002", 0.86),
        ]
        outcome, code, _ = self.engine.evaluate(mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.AMBER

    def test_n_of_1_one_match_green(self):
        mandate = MandateRule(rule_type=MandateRuleType.ANY_N_OF, required_count=1, min_score=0.80)
        matched = [_make_matched("sig-001", 0.93)]
        outcome, _, _ = self.engine.evaluate(mandate, matched, 1, self.signatories)
        assert outcome == MSVOutcome.GREEN

    def test_only_low_score_matches_red(self):
        """Matches below min_score don't count towards the N."""
        mandate = MandateRule(rule_type=MandateRuleType.ANY_N_OF, required_count=2, min_score=0.80)
        matched = [
            _make_matched("sig-001", 0.75),  # below min
            _make_matched("sig-002", 0.79),  # below min
            _make_matched("sig-003", 0.93),  # above min
        ]
        outcome, code, _ = self.engine.evaluate(mandate, matched, 3, self.signatories)
        # Only 1 above threshold → fewer than required_count=2 → RED
        assert outcome == MSVOutcome.RED


class TestBREEngineMandatoryPlusQuorum:
    def setup_method(self):
        self.engine = BREEngine()
        self.signatories = [
            _make_signatory("sig-md", "MD"),
            _make_signatory("sig-001", "DIRECTOR"),
            _make_signatory("sig-002", "DIRECTOR"),
        ]

    def _mandate(self, required_count: int = 1, min_score: float = 0.80):
        return MandateRule(
            rule_type=MandateRuleType.MANDATORY_PLUS_QUORUM,
            mandatory_ids=["sig-md"],
            required_count=required_count,
            min_score=min_score,
        )

    def test_mandatory_and_quorum_met_green(self):
        matched = [
            _make_matched("sig-md", 0.93, "MD"),
            _make_matched("sig-001", 0.91, "DIRECTOR"),
        ]
        outcome, code, _ = self.engine.evaluate(self._mandate(1), matched, 2, self.signatories)
        assert outcome == MSVOutcome.GREEN

    def test_mandatory_missing_red_even_if_quorum_met(self):
        matched = [
            _make_matched("sig-001", 0.92, "DIRECTOR"),
            _make_matched("sig-002", 0.90, "DIRECTOR"),
        ]
        outcome, code, _ = self.engine.evaluate(self._mandate(1), matched, 2, self.signatories)
        assert outcome == MSVOutcome.RED
        assert code == "MANDATORY_SIGNATORY_MISSING"

    def test_mandatory_present_but_quorum_not_met_red(self):
        matched = [_make_matched("sig-md", 0.93, "MD")]
        outcome, code, _ = self.engine.evaluate(self._mandate(1), matched, 2, self.signatories)
        assert outcome == MSVOutcome.RED
        assert code == "QUORUM_NOT_MET"

    def test_quorum_of_2_both_met_green(self):
        matched = [
            _make_matched("sig-md", 0.93, "MD"),
            _make_matched("sig-001", 0.91, "DIRECTOR"),
            _make_matched("sig-002", 0.90, "DIRECTOR"),
        ]
        outcome, code, _ = self.engine.evaluate(self._mandate(2), matched, 3, self.signatories)
        assert outcome == MSVOutcome.GREEN

    def test_mandatory_low_score_amber(self):
        matched = [
            _make_matched("sig-md", 0.83, "MD"),     # above min, below 0.90
            _make_matched("sig-001", 0.95, "DIRECTOR"),
        ]
        outcome, code, _ = self.engine.evaluate(self._mandate(1), matched, 2, self.signatories)
        assert outcome == MSVOutcome.AMBER

    def test_mandatory_below_min_red(self):
        matched = [
            _make_matched("sig-md", 0.75, "MD"),     # below min_score
            _make_matched("sig-001", 0.95, "DIRECTOR"),
        ]
        outcome, code, _ = self.engine.evaluate(self._mandate(1), matched, 2, self.signatories)
        assert outcome == MSVOutcome.RED
        assert code == "SCORE_BELOW_THRESHOLD"


class TestBREEngineThresholdSplit:
    """THRESHOLD_SPLIT: different thresholds per role stored in required_roles as 'ROLE:score' items."""

    def setup_method(self):
        self.engine = BREEngine()
        self.signatories = [
            _make_signatory("sig-cfo", "CFO"),
            _make_signatory("sig-dir", "DIRECTOR"),
        ]

    def test_all_roles_meet_their_threshold_green(self):
        mandate = MandateRule(
            rule_type=MandateRuleType.THRESHOLD_SPLIT,
            required_roles=["CFO:0.90", "DIRECTOR:0.82"],
            min_score=0.80,
        )
        matched = [
            _make_matched("sig-cfo", 0.93, "CFO"),
            _make_matched("sig-dir", 0.85, "DIRECTOR"),
        ]
        outcome, code, _ = self.engine.evaluate(mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.GREEN

    def test_cfo_below_its_threshold_red(self):
        mandate = MandateRule(
            rule_type=MandateRuleType.THRESHOLD_SPLIT,
            required_roles=["CFO:0.90", "DIRECTOR:0.82"],
            min_score=0.80,
        )
        matched = [
            _make_matched("sig-cfo", 0.88, "CFO"),   # below CFO threshold of 0.90
            _make_matched("sig-dir", 0.85, "DIRECTOR"),
        ]
        outcome, code, _ = self.engine.evaluate(mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.RED
        assert code == "SCORE_BELOW_THRESHOLD"

    def test_director_missing_red(self):
        mandate = MandateRule(
            rule_type=MandateRuleType.THRESHOLD_SPLIT,
            required_roles=["CFO:0.90", "DIRECTOR:0.82"],
            min_score=0.80,
        )
        matched = [_make_matched("sig-cfo", 0.95, "CFO")]
        outcome, code, _ = self.engine.evaluate(mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.RED
        assert code == "MISSING_SIGNATORY"


class TestBREEngineRoleBased:
    """ROLE_BASED: match by role count, not specific identity."""

    def setup_method(self):
        self.engine = BREEngine()
        self.signatories = [
            _make_signatory("sig-001", "TRUSTEE"),
            _make_signatory("sig-002", "TRUSTEE"),
            _make_signatory("sig-003", "TRUSTEE"),
        ]

    def test_enough_role_matches_green(self):
        mandate = MandateRule(
            rule_type=MandateRuleType.ROLE_BASED,
            required_roles=["TRUSTEE"],
            required_count=2,
            min_score=0.80,
        )
        matched = [
            _make_matched("sig-001", 0.93, "TRUSTEE"),
            _make_matched("sig-002", 0.91, "TRUSTEE"),
        ]
        outcome, code, _ = self.engine.evaluate(mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.GREEN

    def test_insufficient_role_matches_red(self):
        mandate = MandateRule(
            rule_type=MandateRuleType.ROLE_BASED,
            required_roles=["TRUSTEE"],
            required_count=2,
            min_score=0.80,
        )
        matched = [_make_matched("sig-001", 0.93, "TRUSTEE")]
        outcome, code, _ = self.engine.evaluate(mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.RED
        assert code == "INSUFFICIENT_ROLE_MATCHES"

    def test_wrong_role_does_not_count(self):
        mandate = MandateRule(
            rule_type=MandateRuleType.ROLE_BASED,
            required_roles=["TRUSTEE"],
            required_count=2,
            min_score=0.80,
        )
        matched = [
            _make_matched("sig-001", 0.93, "TRUSTEE"),
            _make_matched("sig-x", 0.91, "CFO"),       # CFO — doesn't count for TRUSTEE
        ]
        outcome, code, _ = self.engine.evaluate(mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.RED


class TestBREEnginePreCheck:
    """Pre-check: detected_count < minimum required by mandate → RED immediately."""

    def setup_method(self):
        self.engine = BREEngine()
        self.signatories = [
            _make_signatory("sig-001"),
            _make_signatory("sig-002"),
        ]

    def test_detected_zero_red(self):
        mandate = MandateRule(rule_type=MandateRuleType.ALL_OF, min_score=0.80)
        outcome, code, msg = self.engine.evaluate(mandate, [], 0, self.signatories)
        assert outcome == MSVOutcome.RED
        assert code == "INSUFFICIENT_SIGNATURES_DETECTED"

    def test_detected_fewer_than_required_all_of_red(self):
        mandate = MandateRule(rule_type=MandateRuleType.ALL_OF, min_score=0.80)
        # 2 signatories required (ALL_OF), only 1 detected
        outcome, code, msg = self.engine.evaluate(mandate, [], 1, self.signatories)
        assert outcome == MSVOutcome.RED
        assert code == "INSUFFICIENT_SIGNATURES_DETECTED"

    def test_detected_fewer_than_required_any_n_of_red(self):
        mandate = MandateRule(
            rule_type=MandateRuleType.ANY_N_OF,
            required_count=3,
            min_score=0.80,
        )
        # required_count=3, only 2 detected → RED pre-check
        outcome, code, msg = self.engine.evaluate(mandate, [], 2, self.signatories)
        assert outcome == MSVOutcome.RED
        assert code == "INSUFFICIENT_SIGNATURES_DETECTED"

    def test_detected_equals_required_no_pre_check_fail(self):
        mandate = MandateRule(rule_type=MandateRuleType.ALL_OF, min_score=0.80)
        # 2 required, 2 detected — pre-check passes (BRE continues)
        matched = [
            _make_matched("sig-001", 0.93),
            _make_matched("sig-002", 0.91),
        ]
        outcome, code, _ = self.engine.evaluate(mandate, matched, 2, self.signatories)
        assert outcome == MSVOutcome.GREEN  # not a pre-check failure

    def test_mandatory_plus_quorum_precheck_uses_1_plus_quorum(self):
        mandate = MandateRule(
            rule_type=MandateRuleType.MANDATORY_PLUS_QUORUM,
            mandatory_ids=["sig-001"],
            required_count=1,
            min_score=0.80,
        )
        signatories = [_make_signatory("sig-001"), _make_signatory("sig-002")]
        # Need 1 (mandatory) + 1 (quorum) = 2, only 1 detected → RED
        outcome, code, _ = self.engine.evaluate(mandate, [], 1, signatories)
        assert outcome == MSVOutcome.RED
        assert code == "INSUFFICIENT_SIGNATURES_DETECTED"
