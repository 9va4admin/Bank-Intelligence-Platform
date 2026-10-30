"""
BRE (Business Rules Engine) for Multi-Signature Validation.

Evaluates the mandate rule against a list of matched signatories and returns
an (outcome, reason_code, reason_message) tuple.

Score interpretation (applies consistently across all rule types):
  All required signatories matched with score >= HIGH_CONFIDENCE_THRESHOLD (0.90) → GREEN
  All required matched, but any score in [mandate.min_score, 0.90) → AMBER
  Any required signatory missing OR any score below mandate.min_score → RED

Pre-check (applied before any rule-type evaluation):
  detected_count < minimum_required_by_mandate → RED, INSUFFICIENT_SIGNATURES_DETECTED

All threshold constants here are BRE-internal logic constants, NOT bank-configurable.
The per-signatory min_score comes from MandateRule.min_score (CBS-derived, per-account).
"""
import structlog

from modules.msv.mandates.models import (
    MandateRule,
    MandateRuleType,
    MatchedSignatory,
    MSVOutcome,
    SignatoryRecord,
)
from shared.messages import get_message

log = structlog.get_logger()

# Score above this → GREEN; [min_score, this) → AMBER; below min_score → RED
_HIGH_CONFIDENCE_THRESHOLD = 0.90


def _parse_threshold_split(required_roles: list[str]) -> dict[str, float]:
    """Parse 'ROLE:0.90' entries in required_roles into {role: threshold} dict."""
    result: dict[str, float] = {}
    for entry in required_roles:
        if ":" in entry:
            role, threshold_str = entry.split(":", 1)
            try:
                result[role.strip()] = float(threshold_str.strip())
            except ValueError:
                pass
    return result


def _min_required_count(mandate: MandateRule, expected_signatories: list[SignatoryRecord]) -> int:
    """Return the minimum number of detected signatures needed to proceed."""
    if mandate.rule_type == MandateRuleType.ALL_OF:
        return len(expected_signatories)
    if mandate.rule_type == MandateRuleType.ANY_N_OF:
        return mandate.required_count
    if mandate.rule_type == MandateRuleType.MANDATORY_PLUS_QUORUM:
        return len(mandate.mandatory_ids) + mandate.required_count
    if mandate.rule_type == MandateRuleType.THRESHOLD_SPLIT:
        return len(expected_signatories)
    if mandate.rule_type == MandateRuleType.ROLE_BASED:
        return mandate.required_count
    return 1


def _determine_outcome_from_scores(
    matched_above_threshold: list[MatchedSignatory],
    mandate: MandateRule,
) -> MSVOutcome:
    """
    Given that all structural requirements are met (right signatories, right count),
    determine GREEN vs AMBER based on score levels.
    """
    if all(m.best_score >= _HIGH_CONFIDENCE_THRESHOLD for m in matched_above_threshold):
        return MSVOutcome.GREEN
    return MSVOutcome.AMBER


def _compute_confidence(matched: list[MatchedSignatory]) -> float:
    """Overall confidence = mean best_score across all matched signatories."""
    if not matched:
        return 0.0
    return sum(m.best_score for m in matched) / len(matched)


class BREEngine:
    """
    Stateless BRE evaluator. All inputs passed explicitly — no shared state.
    Can be safely reused across concurrent workflow activities.
    """

    def evaluate(
        self,
        mandate: MandateRule,
        matched: list[MatchedSignatory],
        detected_count: int,
        expected_signatories: list[SignatoryRecord],
    ) -> tuple[MSVOutcome, str, str]:
        """
        Returns (outcome, reason_code, reason_message).

        Pre-check: detected_count < mandate minimum → RED immediately.
        Then delegates to the specific rule evaluator.
        """
        min_required = _min_required_count(mandate, expected_signatories)
        if detected_count < min_required:
            msg = (
                f"Only {detected_count} signature(s) detected; "
                f"mandate requires {min_required}."
            )
            log.info(
                "bre.precheck_failed",
                detected=detected_count,
                required=min_required,
                rule_type=mandate.rule_type,
            )
            return MSVOutcome.RED, "INSUFFICIENT_SIGNATURES_DETECTED", msg

        if mandate.rule_type == MandateRuleType.ALL_OF:
            return self._eval_all_of(mandate, matched, expected_signatories)
        if mandate.rule_type == MandateRuleType.ANY_N_OF:
            return self._eval_any_n_of(mandate, matched)
        if mandate.rule_type == MandateRuleType.MANDATORY_PLUS_QUORUM:
            return self._eval_mandatory_plus_quorum(mandate, matched, expected_signatories)
        if mandate.rule_type == MandateRuleType.THRESHOLD_SPLIT:
            return self._eval_threshold_split(mandate, matched, expected_signatories)
        if mandate.rule_type == MandateRuleType.ROLE_BASED:
            return self._eval_role_based(mandate, matched)

        return MSVOutcome.AMBER, "UNKNOWN_RULE_TYPE", get_message("MSV_UNKNOWN_MANDATE_RULE_TYPE", rule_type=mandate.rule_type)

    # ------------------------------------------------------------------
    # Rule-specific evaluators
    # ------------------------------------------------------------------

    def _eval_all_of(
        self,
        mandate: MandateRule,
        matched: list[MatchedSignatory],
        expected: list[SignatoryRecord],
    ) -> tuple[MSVOutcome, str, str]:
        matched_ids = {m.signatory_id for m in matched}
        expected_ids = {s.signatory_id for s in expected}

        # Check all expected are present
        missing = expected_ids - matched_ids
        if missing:
            return (
                MSVOutcome.RED,
                "MISSING_SIGNATORY",
                get_message("MSV_REQUIRED_SIGNATORIES_ABSENT", sorted=sorted(missing)),
            )

        # Check scores
        matched_expected = [m for m in matched if m.signatory_id in expected_ids]
        below_min = [m for m in matched_expected if m.best_score < mandate.min_score]
        if below_min:
            return (
                MSVOutcome.RED,
                "SCORE_BELOW_THRESHOLD",
                get_message("MSV_SIGNATORY_IES_SCORED_BELOW_MINIMUM", value=[m.signatory_id for m in below_min], min_score=mandate.min_score),
            )

        outcome = _determine_outcome_from_scores(matched_expected, mandate)
        if outcome == MSVOutcome.GREEN:
            return MSVOutcome.GREEN, "ALL_MATCHED", get_message("MSV_ALL_SIGNATORIES_MATCHED_ABOVE_HIGH")
        return MSVOutcome.AMBER, "LOW_CONFIDENCE_MATCH", get_message("MSV_ALL_SIGNATORIES_PRESENT_BUT_SOME")

    def _eval_any_n_of(
        self,
        mandate: MandateRule,
        matched: list[MatchedSignatory],
    ) -> tuple[MSVOutcome, str, str]:
        # Only count matches that meet the minimum score
        qualifying = [m for m in matched if m.best_score >= mandate.min_score]
        n = mandate.required_count

        if len(qualifying) < n:
            return (
                MSVOutcome.RED,
                "INSUFFICIENT_MATCHES",
                get_message("MSV_ONLY_SIGNATORY_IES_MATCHED_ABOVE", len=len(qualifying), min_score=mandate.min_score, n=n),
            )

        # Enough qualify — determine GREEN vs AMBER from scores of the n best
        best_n = sorted(qualifying, key=lambda m: m.best_score, reverse=True)[:n]
        outcome = _determine_outcome_from_scores(best_n, mandate)
        if outcome == MSVOutcome.GREEN:
            return MSVOutcome.GREEN, "QUORUM_MET", f"{n} of {n} required signatories matched."
        return MSVOutcome.AMBER, "LOW_CONFIDENCE_MATCH", get_message("MSV_QUORUM_MET_BUT_CONFIDENCE_BELOW")

    def _eval_mandatory_plus_quorum(
        self,
        mandate: MandateRule,
        matched: list[MatchedSignatory],
        expected: list[SignatoryRecord],
    ) -> tuple[MSVOutcome, str, str]:
        matched_map = {m.signatory_id: m for m in matched}

        # 1. Check mandatory signatories are present and above min_score
        for sig_id in mandate.mandatory_ids:
            if sig_id not in matched_map:
                return (
                    MSVOutcome.RED,
                    "MANDATORY_SIGNATORY_MISSING",
                    get_message("MSV_MANDATORY_SIGNATORY_DID_NOT_SIGN", sig_id=sig_id),
                )
            m = matched_map[sig_id]
            if m.best_score < mandate.min_score:
                return (
                    MSVOutcome.RED,
                    "SCORE_BELOW_THRESHOLD",
                    f"Mandatory signatory '{sig_id}' scored {m.best_score:.3f} "
                    f"below minimum {mandate.min_score}.",
                )

        # 2. Check quorum among non-mandatory signatories
        non_mandatory_matched = [
            m for m in matched
            if m.signatory_id not in set(mandate.mandatory_ids)
            and m.best_score >= mandate.min_score
        ]
        if len(non_mandatory_matched) < mandate.required_count:
            return (
                MSVOutcome.RED,
                "QUORUM_NOT_MET",
                get_message("MSV_ONLY_OF_REQUIRED_QUORUM_SIGNATORIES", len=len(non_mandatory_matched), required_count=mandate.required_count),
            )

        # All conditions met — determine GREEN vs AMBER
        all_qualifying = [matched_map[sid] for sid in mandate.mandatory_ids] + non_mandatory_matched[:mandate.required_count]
        outcome = _determine_outcome_from_scores(all_qualifying, mandate)
        if outcome == MSVOutcome.GREEN:
            return MSVOutcome.GREEN, "ALL_MATCHED", get_message("MSV_MANDATORY_SIGNER_S_AND_QUORUM")
        return MSVOutcome.AMBER, "LOW_CONFIDENCE_MATCH", get_message("MSV_MANDATORY_SIGNER_S_AND_QUORUM_2")

    def _eval_threshold_split(
        self,
        mandate: MandateRule,
        matched: list[MatchedSignatory],
        expected: list[SignatoryRecord],
    ) -> tuple[MSVOutcome, str, str]:
        role_thresholds = _parse_threshold_split(mandate.required_roles)
        matched_by_id = {m.signatory_id: m for m in matched}
        expected_ids = {s.signatory_id for s in expected}

        missing = expected_ids - set(matched_by_id)
        if missing:
            return (
                MSVOutcome.RED,
                "MISSING_SIGNATORY",
                get_message("MSV_REQUIRED_SIGNATORIES_ABSENT", sorted=sorted(missing)),
            )

        all_qualifying: list[MatchedSignatory] = []
        for m in matched:
            if m.signatory_id not in expected_ids:
                continue
            threshold = role_thresholds.get(m.role, mandate.min_score)
            if m.best_score < threshold:
                return (
                    MSVOutcome.RED,
                    "SCORE_BELOW_THRESHOLD",
                    f"Signatory '{m.signatory_id}' (role {m.role}) scored {m.best_score:.3f} "
                    f"below role threshold {threshold}.",
                )
            all_qualifying.append(m)

        # For THRESHOLD_SPLIT, meeting the role-specific threshold IS the high-confidence
        # bar — if all qualified, outcome is GREEN (role threshold already provides the bar).
        return MSVOutcome.GREEN, "ALL_MATCHED", get_message("MSV_ALL_SIGNATORIES_MET_THEIR_ROLE")

    def _eval_role_based(
        self,
        mandate: MandateRule,
        matched: list[MatchedSignatory],
    ) -> tuple[MSVOutcome, str, str]:
        required_roles = set(
            r.split(":")[0] if ":" in r else r
            for r in mandate.required_roles
        )
        qualifying = [
            m for m in matched
            if m.role in required_roles and m.best_score >= mandate.min_score
        ]

        if len(qualifying) < mandate.required_count:
            return (
                MSVOutcome.RED,
                "INSUFFICIENT_ROLE_MATCHES",
                get_message("MSV_ONLY_SIGNATORIES_WITH_REQUIRED_ROLE", len=len(qualifying), required_roles=required_roles, required_count=mandate.required_count),
            )

        best_n = sorted(qualifying, key=lambda m: m.best_score, reverse=True)[:mandate.required_count]
        outcome = _determine_outcome_from_scores(best_n, mandate)
        if outcome == MSVOutcome.GREEN:
            return MSVOutcome.GREEN, "ROLE_QUORUM_MET", get_message("MSV_REQUIRED_ROLE_S_MATCHED_WITH", required_roles=required_roles, required_count=mandate.required_count)
        return MSVOutcome.AMBER, "LOW_CONFIDENCE_MATCH", get_message("MSV_ROLE_QUORUM_MET_BUT_CONFIDENCE")
