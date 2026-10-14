"""Conformance of ASTRA's return reason codes with the clearing-house annexure.

Master data: docs/npci/return_reason_codes.json (Annexure D to the Uniform Regulations and Rules for
Bankers' Clearing Houses, via a bank's published policy; a secondary source - re-verify against the
current NPCI/RBI annexure before certification).
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
MASTER = json.loads((ROOT / "docs/npci/return_reason_codes.json").read_text(encoding="utf-8"))["codes"]


def _emitted_codes() -> set[str]:
    """Every literal return_reason_code the code base can emit."""
    found = set()
    for rel in ("modules/cts/workflows/activities/decision.py", "modules/cts/workflows/activities/ngch_filer.py",
                "modules/cts/workflows/activities/pps.py", "modules/cts/workflows/activities/stop_payment.py",
                "modules/cts/workflows/cheque_workflow.py"):
        p = ROOT / rel
        if p.exists():
            found |= set(re.findall(r"return_reason_code\s*=\s*[\"'](\d\d)[\"']", p.read_text(encoding="utf-8")))
    return found


def test_master_is_complete_enough_to_trust():
    assert len(MASTER) >= 60
    for c in ("01", "12", "20", "30", "31", "32", "34", "36", "39", "41", "52", "85", "86", "88"):
        assert c in MASTER, c


def test_every_code_astra_emits_is_in_the_master():
    emitted = _emitted_codes()
    assert emitted, "no emitted codes found - the scan is broken"
    assert emitted <= set(MASTER), sorted(emitted - set(MASTER))


def test_every_code_in_models_exists_in_the_master():
    from modules.cts.compliance import models as m
    for name in ("NON_CUSTOMER_FAULT_CODES", "RE_PRESENTATION_CODES"):
        assert getattr(m, name) <= set(MASTER), (name, sorted(getattr(m, name) - set(MASTER)))


# Codes ASTRA treats as "customer not at fault" although Annexure II does not list them. The code comments
# call this "by convention: collecting bank should have rejected at intake" and older tests cite four banks'
# customer-compensation policies for it. OPEN POLICY QUESTION for a compliance officer: under Annexure II alone
# the depositor is at fault for 30/31/32/55 and return charges would apply. The deviation is pinned here so
# it can only change deliberately.
DOCUMENTED_DEVIATION_FROM_ANNEXURE_II = {"30", "31", "32", "55"}


def test_customer_not_at_fault_set_is_annexure_ii_plus_the_documented_deviation_only():
    from modules.cts.compliance.models import NON_CUSTOMER_FAULT_CODES
    annexure_ii = {c for c, v in MASTER.items() if v["customer_not_at_fault_annexure_ii"]}
    assert annexure_ii <= set(NON_CUSTOMER_FAULT_CODES), sorted(annexure_ii - set(NON_CUSTOMER_FAULT_CODES))
    assert set(NON_CUSTOMER_FAULT_CODES) - annexure_ii == DOCUMENTED_DEVIATION_FROM_ANNEXURE_II


def test_descriptions_of_the_codes_decision_relies_on_say_what_we_think_they_say():
    expect = {"30": "post dated", "31": "stale", "32": "undated", "34": "amount in words and figures",
              "36": "not drawn on us", "39": "image not clear", "41": "listed twice", "85": "alterations",
              "86": "forged"}
    for code, phrase in expect.items():
        assert phrase in MASTER[code]["description"].lower(), (code, MASTER[code]["description"])


def test_master_is_verified_against_the_primary_specification():
    data = json.loads((ROOT / "docs/npci/return_reason_codes.json").read_text(encoding="utf-8"))
    assert "Continuous Clearing, Rev 3.0" in data["_source"]
    not_in_chi = [c for c, v in data["codes"].items() if not v["in_chi_spec"]]
    assert not_in_chi == ["92"], not_in_chi            # only 'Bank excluded' is absent from the current spec
    assert "99" in data["codes"] and "00" in data["codes"]


def test_every_member_of_the_compliance_enum_is_a_code_in_the_current_specification():
    from modules.cts.compliance.models import ReturnReasonCode
    for member in ReturnReasonCode:
        code = member.value
        # 92 'Bank excluded' is in the 2018 Chennai guideline but not in CHI spec Rev 3.0 (handled at the clearing house):
        # tolerated as a documented legacy member, never to be sent.
        assert code in MASTER and (MASTER[code]["in_chi_spec"] or code == "92"), (member.name, code)
    assert "99" not in {m.value for m in ReturnReasonCode}        # deemed accepted is the clearing house's, never sent
