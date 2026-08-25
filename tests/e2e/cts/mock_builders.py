"""
CTS E2E Mock Builders
======================
Constructs mock result objects for both pipelines.

MOCKED (synthetic values, no real infra):
  • vLLM inference — Qwen2-VL, GOT-OCR2.0, Llama 3.3 70B
  • NGCH push (file_to_ngch activity)

REAL CODE PATHS (tested):
  • Workflow orchestration logic (run_with_mocks)
  • STP-mode routing (FULL_STP / SELECTIVE / SUPERVISED / FULL_MANUAL)
  • CBS result routing (RETURN / CBS_UNAVAILABLE / OK)
  • Account status routing (FROZEN / CLOSED / DORMANT → HUMAN_REVIEW)
  • Stop payment routing (STP_RETURN / HUMAN_REVIEW / OK)
  • CTS-2010 compliance gate
  • IFSC registry gate
  • Cheque series gate
  • Fraud score routing via synthesise_decision mock
  • IET watchdog spawn callback
  • SMB side-effect routing (ledger + notify)
  • Date validation (stale / post-dated / undated) — runs inline in workflow
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def _ns(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# OUTWARD mock builder
# ─────────────────────────────────────────────────────────────────────────────

def build_outward_mocks(fixture) -> dict:                        # noqa: ANN001
    """
    Return mock_results dict for OutwardScanWorkflow.run_with_mocks().

    The 'micr' key drives date validation (inline in workflow — not mocked).
    All other keys wire the specific failure path for each scenario.
    """
    t = fixture.trigger
    today = fixture.cheque_date   # already set per fixture (TODAY / FUTURE / STALE)

    # ── Baseline: passing values for every key ────────────────────────────────
    micr = _ns(
        micr_line=fixture.micr_line,
        date=today,
        amount_str=str(fixture.amount),
        payee_name=fixture.payee_name,
        cheque_number=fixture.cheque_number,
    )
    compliance = _ns(is_compliant=True, violations=[])
    cross_check = _ns(outcome="PROCEED", mismatch_fields=[])
    payee = _ns(outcome="PROCEED", name_match_score=0.95, account_status="ACTIVE")
    alteration = _ns(alteration_detected=False, degraded=False, altered_fields=[])
    uv = _ns(uv_security_passed=True, degraded=False, uv_risk_score=0.05)
    vision_llm = _ns(has_mismatch=False, mismatch_fields=[])
    audit = _ns(written=True)

    # ── Scenario overrides ────────────────────────────────────────────────────

    if t == "POST_DATED":
        # Date is already FUTURE in fixture.cheque_date → workflow exits at date check
        pass

    elif t == "STALE_DATE":
        # Date is already STALE in fixture.cheque_date → workflow exits at date check
        pass

    elif t == "CTS2010_FAIL":
        compliance = _ns(
            is_compliant=False,
            violations=["DPI_BELOW_MINIMUM:front=150,required=200"],
        )

    elif t == "NGCH_MISMATCH":
        cross_check = _ns(
            outcome="HUMAN_REVIEW",
            mismatch_fields=["drawee_ifsc"],
        )

    elif t == "PAYEE_NOT_FOUND":
        payee = _ns(outcome="ACCOUNT_NOT_FOUND", name_match_score=0.0, account_status="UNKNOWN")

    elif t == "PAYEE_NAME_MISMATCH":
        payee = _ns(outcome="NAME_MISMATCH", name_match_score=0.41, account_status="ACTIVE")

    elif t == "VISION_MISMATCH":
        vision_llm = _ns(
            has_mismatch=True,
            mismatch_fields=["amount_in_words", "amount_in_figures"],
        )

    elif t == "UV_FAIL":
        uv = _ns(uv_security_passed=False, degraded=False, uv_risk_score=0.91)

    elif t == "ALTERATION_DETECTED":
        alteration = _ns(
            alteration_detected=True,
            degraded=False,
            altered_fields=["amount_figures"],
        )

    elif t in ("ALL_PASS", "ALL_PASS_XCHECK", "ALL_PASS_SMB"):
        # Extra: wire cross_check as passing for ALL_PASS_XCHECK
        if t == "ALL_PASS_XCHECK":
            cross_check = _ns(outcome="PROCEED", mismatch_fields=[])

    return {
        "micr": micr,
        "compliance": compliance,
        "cross_check": cross_check,
        "payee": payee,
        "alteration": alteration,
        "uv": uv,
        "vision_llm": vision_llm,
        "audit": audit,
    }


# ─────────────────────────────────────────────────────────────────────────────
# INWARD mock builder
# ─────────────────────────────────────────────────────────────────────────────

_SHAP_CLEAN = {
    "amount": -0.12,
    "account_age_days": -0.08,
    "payee_match_score": -0.15,
    "fraud_velocity": -0.04,
    "sig_match_score": -0.18,
}

_SHAP_FRAUD = {
    "amount": 0.31,
    "account_age_days": 0.18,
    "payee_match_score": 0.22,
    "fraud_velocity": 0.09,
    "sig_match_score": -0.05,
}


def build_inward_mocks(fixture) -> dict:                         # noqa: ANN001
    """
    Return mock_results dict for ChequeProcessingWorkflow.run_with_mocks().

    vLLM calls (OCR output, alteration, security features, vision) are synthetic.
    All workflow routing logic is exercised for real.
    NGCH filing is bypassed (no 'file_to_ngch' key needed — watchdog signal not sent in mocks).
    """
    t = fixture.trigger

    # ── Baseline: all checks pass ─────────────────────────────────────────────
    ocr = _ns(outcome="PROCEED", extracted_date=fixture.cheque_date,
              amount_str=str(fixture.amount), payee_name=fixture.payee_name,
              cheque_number=fixture.cheque_number, low_confidence_reason=None)

    alteration = _ns(alteration_detected=False, tamper_risk_score=0.03)

    security_features = _ns(
        outcome="PROCEED",
        missing_features=[],
        void_pantograph_detected=True,
        micro_lettering_detected=True,
        rupee_symbol_detected=True,
    )

    compliance = _ns(is_compliant=True, violations=[])

    stop_payment = _ns(outcome="OK", stop_reason=None)

    ifsc = _ns(outcome="PROCEED", reason=None)

    pps = _ns(
        pps_found=True,
        account_hash="sha256:aabbccdd",
        pps_entries=3,
        cheque_series_start="100000",
    )

    sig_count = 1

    signature = _ns(
        match_score=0.93,
        matched=True,
        signatory_id="SIG-001",
        comparison_method="siamese_v2",
    )

    fraud = _ns(
        fraud_score=0.11,
        shap_values=_SHAP_CLEAN,
        model_version="xgboost-v3.2",
        feature_vector={},
    )

    cheque_series = _ns(outcome="OK", reason=None, return_reason_code=None)

    cbs = _ns(outcome="OK", available_balance=fixture.amount * 2.5,
              account_balance_range="above_amount")

    account_status = _ns(outcome="OK", account_status="ACTIVE")

    decision = _ns(
        decision="STP_CONFIRM",
        rationale="all_checks_passed",
        shap_values=_SHAP_CLEAN,
        stp_confidence=0.97,
    )

    audit = _ns(written=True, immudb_tx_id="TX-MOCK-001")

    # ── Scenario overrides ────────────────────────────────────────────────────

    if t == "OCR_LOW_CONF":
        ocr = _ns(
            outcome="HUMAN_REVIEW",
            low_confidence_reason="indic_script_extraction_failed",
            extracted_date=None,
            amount_str=None,
            payee_name=None,
            cheque_number=None,
        )

    elif t == "ALTERATION":
        alteration = _ns(
            alteration_detected=True,
            tamper_risk_score=0.92,
            altered_fields=["amount_figures"],
        )

    elif t == "SECURITY_FEAT_FAIL":
        security_features = _ns(
            outcome="HUMAN_REVIEW",
            missing_features=["VOID_PANTOGRAPH"],
            void_pantograph_detected=False,
            micro_lettering_detected=True,
            rupee_symbol_detected=True,
        )

    elif t == "CTS2010_FAIL":
        compliance = _ns(
            is_compliant=False,
            violations=["DPI_BELOW_MINIMUM:front=150,required=200"],
        )

    elif t == "STOP_PAYMENT_STP":
        stop_payment = _ns(
            outcome="STP_RETURN",
            stop_reason="STOP_PAYMENT_CONFIRMED_CBS",
        )

    elif t == "STOP_PAYMENT_BLOOM":
        stop_payment = _ns(
            outcome="HUMAN_REVIEW",
            stop_reason="BLOOM_HIT_CBS_UNCONFIRMED",
        )

    elif t == "IFSC_INVALID":
        ifsc = _ns(
            outcome="HUMAN_REVIEW",
            reason="IFSC_NOT_IN_REGISTRY",
        )

    elif t == "NO_SIGNATURE":
        # Cheque has no signature at all — sig_count=0 triggers STP_RETURN
        sig_count = 0
        decision = _ns(
            decision="STP_RETURN",
            rationale="no_signature_on_cheque",
            shap_values={},
            stp_confidence=0.0,
        )

    elif t == "SIG_MISMATCH":
        signature = _ns(
            match_score=0.41,
            matched=False,
            signatory_id="SIG-001",
            comparison_method="siamese_v2",
        )
        decision = _ns(
            decision="HUMAN_REVIEW",
            rationale="signature_mismatch_score_0.41_below_threshold_0.85",
            shap_values={"sig_match_score": 0.55},
            stp_confidence=0.0,
        )

    elif t == "FRAUD_HIGH":
        fraud = _ns(
            fraud_score=0.85,
            shap_values=_SHAP_FRAUD,
            model_version="xgboost-v3.2",
            feature_vector={},
        )
        decision = _ns(
            decision="HUMAN_REVIEW",
            rationale="fraud_score_0.85_above_threshold_0.72",
            shap_values=_SHAP_FRAUD,
            stp_confidence=0.0,
        )

    elif t == "CHEQUE_SERIES_STP":
        cheque_series = _ns(
            outcome="STP_RETURN",
            reason="cheque_leaf_not_issued_to_account",
            return_reason_code="RRC-21",
        )

    elif t == "CBS_INSUFFICIENT":
        cbs = _ns(
            outcome="RETURN",
            available_balance=fixture.amount * 0.3,
            account_balance_range="below_amount",
        )

    elif t == "CBS_UNAVAILABLE":
        cbs = _ns(outcome="CBS_UNAVAILABLE", available_balance=None, account_balance_range=None)

    elif t == "WORDS_DIGITS_MISMATCH":
        # Fraudster altered the digit box; handwritten words still show original amount.
        # Vision LLM detects the discrepancy → HUMAN_REVIEW.
        _tampered = float(str(int(fixture.amount))[0] + str(int(fixture.amount)))
        alteration = _ns(
            alteration_detected=True,
            tamper_risk_score=0.88,
            altered_fields=["amount_figures"],
            amount_figures=_tampered,
            amount_words_value=fixture.amount,
            amount_mismatch=True,
        )

    elif t == "ACCOUNT_FROZEN":
        account_status = _ns(outcome="RETURN", account_status="FROZEN")

    elif t == "ACCOUNT_DORMANT":
        account_status = _ns(outcome="HUMAN_REVIEW", account_status="DORMANT")

    elif t == "STP_FULL_MANUAL":
        # All checks pass; decision=STP_CONFIRM; but cts_config.stp_mode=FULL_MANUAL
        # → workflow routes to HUMAN_REVIEW with stp_eligible=True
        pass  # baseline decision=STP_CONFIRM already set; cts_config carries FULL_MANUAL

    elif t == "MULTI_SIG_MSV_RED":
        sig_count = 2
        # msv result: mandate not met (only 1 of 2 required signatories verified)
        msv = _ns(outcome="RED", reason="MANDATE_NOT_MET:required=2,verified=1",
                  mandate_id="MSV-CORP-001")
        return {
            "ocr": ocr,
            "alteration": alteration,
            "security_features": security_features,
            "compliance": compliance,
            "stop_payment": stop_payment,
            "ifsc": ifsc,
            "pps": pps,
            "sig_count": sig_count,
            "msv": msv,
            "signature": signature,
            "fraud": fraud,
            "cheque_series": cheque_series,
            "cbs": cbs,
            "account_status": account_status,
            "decision": decision,
            "audit": audit,
            "amount_range": fixture.amount_range,
            "session_date": "20260824",
            "clearing_session": "MORNING",
        }

    elif t in ("ALL_PASS", "ALL_PASS_SMB"):
        pass  # baseline already correct

    # SMB extras (needed for ALL_PASS_SMB to wire the ledger update)
    result: dict = {
        "ocr": ocr,
        "alteration": alteration,
        "security_features": security_features,
        "compliance": compliance,
        "stop_payment": stop_payment,
        "ifsc": ifsc,
        "pps": pps,
        "sig_count": sig_count,
        "signature": signature,
        "fraud": fraud,
        "cheque_series": cheque_series,
        "cbs": cbs,
        "account_status": account_status,
        "decision": decision,
        "audit": audit,
        "amount_range": fixture.amount_range,
        "session_date": "20260824",
        "clearing_session": "MORNING",
    }

    if fixture.smb_id:
        result["sub_member_id"] = fixture.smb_id

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Step-trace builders  (for register_instrument 'steps' argument)
# ─────────────────────────────────────────────────────────────────────────────

_OUTWARD_STEP_NAMES = [
    ("ocr_extract",      "OCR / MICR Extraction"),
    ("date_validate",    "Date Validation"),
    ("post_dated_hold",  "Post-Dated Hold Spawn"),
    ("payee_validate",   "Payee Account Validation"),
    ("ngch_cross_check", "NGCH Metadata Cross-Check"),
    ("cts2010",          "CTS-2010 Compliance"),
    ("alteration",       "Alteration Detection (Gray)"),
    ("uv_security",      "UV Security Check"),
    ("vision_crosscheck","Vision LLM Cross-Check"),
    ("mismatch_spawn",   "MismatchResolution Spawn"),
    ("audit_write",      "Audit Write (Immudb)"),
    ("branch_monitor",   "Branch Monitor Event"),
]

_INWARD_STEP_NAMES = [
    ("iet_watchdog",      "IET Watchdog"),
    ("ocr_extract",       "OCR Extraction"),
    ("alteration_detect", "Alteration Detection"),
    ("security_features", "Security Features"),
    ("cts2010",           "CTS-2010 Compliance (received)"),
    ("stop_payment",      "Stop Payment Check"),
    ("ifsc_validate",     "IFSC Registry Validation"),
    ("pps_lookup",        "PPS Vault Lookup"),
    ("sig_detect",        "Signature Detection"),
    ("sig_verify",        "Signature Verification"),
    ("fraud_score",       "Fraud Scoring (XGBoost)"),
    ("cheque_series",     "Cheque Series Validation"),
    ("cbs_balance",       "CBS Balance Check"),
    ("account_status",    "Account Status Check"),
    ("synthesise_decision","Decision Synthesis (OPA)"),
    ("stp_mode_routing",  "STP Mode Routing"),
    ("persist_decision",  "Persist Agent Decision"),
    ("ngch_file",         "NGCH Filing"),
    ("audit_write",       "Audit Write (Immudb)"),
    ("feedback_emit",     "OCR Feedback Emit"),
]

# Map: trigger → (step_id where exit occurs, outcome label for that step)
_OUTWARD_EXIT: dict[str, tuple[str, str]] = {
    "ALL_PASS":          ("audit_write", "WRITTEN"),
    "ALL_PASS_XCHECK":   ("audit_write", "WRITTEN"),
    "ALL_PASS_SMB":      ("audit_write", "WRITTEN"),
    "POST_DATED":        ("date_validate", "POST_DATED_HELD"),
    "STALE_DATE":        ("date_validate", "STALE_REJECTED"),
    "CTS2010_FAIL":      ("cts2010", "NON_COMPLIANT"),
    "NGCH_MISMATCH":     ("ngch_cross_check", "MISMATCH"),
    "PAYEE_NOT_FOUND":   ("payee_validate", "NOT_FOUND"),
    "PAYEE_NAME_MISMATCH":("payee_validate", "NAME_MISMATCH"),
    "VISION_MISMATCH":   ("vision_crosscheck", "AMOUNT_MISMATCH"),
    "UV_FAIL":           ("uv_security", "FAILED"),
    "ALTERATION_DETECTED":("alteration", "TAMPERED"),
}

_INWARD_EXIT: dict[str, tuple[str, str]] = {
    "ALL_PASS":          ("feedback_emit", "EMITTED"),
    "ALL_PASS_SMB":      ("feedback_emit", "EMITTED"),
    "OCR_LOW_CONF":      ("ocr_extract", "LOW_CONFIDENCE"),
    "ALTERATION":        ("alteration_detect", "TAMPERED"),
    "SECURITY_FEAT_FAIL":("security_features", "MISSING"),
    "CTS2010_FAIL":      ("cts2010", "NON_COMPLIANT"),
    "STOP_PAYMENT_STP":  ("stop_payment", "STP_RETURN"),
    "STOP_PAYMENT_BLOOM":("stop_payment", "BLOOM_HIT"),
    "IFSC_INVALID":      ("ifsc_validate", "NOT_IN_REGISTRY"),
    "NO_SIGNATURE":      ("detect_signatures",   "ABSENT"),
    "SIG_MISMATCH":      ("synthesise_decision", "HR_SIG_MISMATCH"),
    "FRAUD_HIGH":        ("synthesise_decision", "HR_FRAUD_HIGH"),
    "CHEQUE_SERIES_STP": ("cheque_series", "INVALID"),
    "CBS_INSUFFICIENT":  ("cbs_balance", "INSUFFICIENT"),
    "CBS_UNAVAILABLE":        ("cbs_balance",       "UNAVAILABLE"),
    "WORDS_DIGITS_MISMATCH":  ("alteration_detect", "WORDS_DIGITS_MISMATCH"),
    "ACCOUNT_FROZEN":    ("account_status", "FROZEN"),
    "ACCOUNT_DORMANT":   ("account_status", "DORMANT"),
    "STP_FULL_MANUAL":   ("stp_mode_routing", "FULL_MANUAL→HR"),
    "MULTI_SIG_MSV_RED": ("sig_verify", "MSV_RED"),
}


def build_outward_step_trace(fixture) -> list[dict]:                 # noqa: ANN001
    exit_step, exit_outcome = _OUTWARD_EXIT.get(fixture.trigger, ("audit_write", "WRITTEN"))
    steps: list[dict] = []
    reached_exit = False
    for step_id, name in _OUTWARD_STEP_NAMES:
        # Skip conditional steps that don't apply
        if step_id == "post_dated_hold" and fixture.trigger != "POST_DATED":
            continue
        if step_id == "payee_validate" and not fixture.payee_account_number:
            continue
        if step_id == "ngch_cross_check" and not getattr(fixture, "registered_drawee_ifsc", None):
            continue
        if step_id == "alteration" and not fixture.has_gray_image:
            continue
        if step_id == "uv_security" and not fixture.has_uv_image:
            continue
        if step_id == "mismatch_spawn" and fixture.expected_outcome != "MISMATCH_HELD":
            continue

        if step_id == exit_step:
            steps.append({"name": name, "outcome": exit_outcome})
            reached_exit = True
            break
        steps.append({"name": name, "outcome": "PASS"})

    if not reached_exit:
        # Safety: mark audit as written
        steps.append({"name": "Audit Write (Immudb)", "outcome": "WRITTEN"})
    return steps


def build_inward_step_trace(fixture, result) -> list[dict]:          # noqa: ANN001
    exit_step, exit_outcome = _INWARD_EXIT.get(fixture.trigger, ("synthesise_decision", "DECIDED"))
    steps: list[dict] = []

    # IET watchdog ALWAYS runs first
    steps.append({"name": "IET Watchdog", "outcome": "SPAWNED"})

    reached_exit = False
    for step_id, name in _INWARD_STEP_NAMES[1:]:   # skip iet_watchdog (already added)
        # Skip conditional steps
        if step_id == "ifsc_validate" and not fixture.ngch_ifsc:
            if fixture.trigger != "IFSC_INVALID":
                continue
        if step_id == "sig_verify" and fixture.trigger == "MULTI_SIG_MSV_RED":
            # Rename to MSV for multi-sig path
            steps.append({"name": "MSV Validation", "outcome": exit_outcome})
            reached_exit = True
            break
        if step_id == "ngch_file":
            if result.decision != "STP_CONFIRM":
                continue   # NGCH filing only on STP_CONFIRM (mocked out anyway)
        if step_id == "feedback_emit":
            # Always fires (fire-and-forget child)
            steps.append({"name": name, "outcome": "EMITTED"})
            reached_exit = True
            break

        if step_id == exit_step:
            # Annotate with extra data for interesting steps
            extra: dict = {}
            if step_id == "fraud_score":
                extra["score"] = 0.85 if fixture.trigger == "FRAUD_HIGH" else 0.11
                extra["shap"] = _SHAP_FRAUD if fixture.trigger == "FRAUD_HIGH" else _SHAP_CLEAN
            if step_id == "sig_verify":
                extra["score"] = 0.41 if fixture.trigger == "SIG_MISMATCH" else 0.93
            steps.append({"name": name, "outcome": exit_outcome, **extra})
            reached_exit = True
            break

        # Normal pass
        extra = {}
        if step_id == "fraud_score":
            extra["score"] = 0.11
            extra["shap"] = _SHAP_CLEAN
        if step_id == "sig_verify":
            extra["score"] = 0.93
        steps.append({"name": name, "outcome": "PASS", **extra})

    if not reached_exit:
        steps.append({"name": "Audit Write (Immudb)", "outcome": "WRITTEN"})

    return steps
