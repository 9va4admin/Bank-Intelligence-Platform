"""
Real Cheque Smoke Test Fixtures — 112 fixtures backed by demo/112/ scans
=========================================================================
Each fixture maps one real cheque image (from demo/112/) to a pipeline
smoke-test scenario.  The real cheque IMAGE is shown in the digest; the
mock data is synthetic and deterministic (we can't OCR the real cheques
inside the test runner).

Scenario assignment: round-robin across 8 "real-world" inward scenario types
so the corpus covers different pipeline paths while every group of 8 cheques
cycles through the full scenario set.

All 112 fixtures use bank_id="syndicate-bank" or "axis-bank" depending on
their position in the sorted file list — matching the two real banks we observed
in the demo images.

Images located at: demo/112/*.jpeg and demo/112/*.tiff  (116 total; we use 112)
"""
from __future__ import annotations

import time
from dataclasses import field
from pathlib import Path
from typing import Optional

from tests.e2e.cts.cheque_fixtures import ChequeFixture, DEFAULT_CTS_CONFIG, TODAY

_DEMO_DIR = Path(__file__).parents[3] / "demo" / "112"

_REAL_CHEQUE_FILES: list[Path] = sorted(
    p for p in _DEMO_DIR.iterdir()
    if p.suffix.lower() in (".jpeg", ".jpg", ".tiff", ".tif")
)[:112]   # use exactly 112

# 8 scenario types that cycle across the 112 real cheques
# Trigger names match mock_builders.py; expected outcomes match ChequeProcessingWorkflow routing.
_RC_SCENARIOS = [
    ("CLEAN_ALL_PASS",    "STP_CONFIRM",  "POSITIVE", "Clean pass — all checks OK",                  95_000.0),
    ("CLEAN_ALL_PASS",    "STP_CONFIRM",  "POSITIVE", "High-value clean — 2 sigs required",       2_200_000.0),
    ("SIG_MISMATCH",      "HUMAN_REVIEW", "NEGATIVE", "Signature mismatch → human review",           78_000.0),
    ("FRAUD_HIGH",        "HUMAN_REVIEW", "NEGATIVE", "High fraud score → human review",             65_000.0),
    ("STOP_PAYMENT_STP",  "STP_RETURN",   "NEGATIVE", "Stop-payment in force → hard STP return",     42_000.0),
    ("OCR_LOW_CONF",      "HUMAN_REVIEW", "NEGATIVE", "OCR confidence low → human review",           55_000.0),
    ("ACCOUNT_FROZEN",    "STP_RETURN",   "NEGATIVE", "Account frozen — hard STP return",           110_000.0),
    ("CBS_INSUFFICIENT",  "STP_RETURN",   "NEGATIVE", "CBS balance insufficient — hard STP return", 320_000.0),
]

# Per-image overrides: {sorted_file_index: (trigger, expected_outcome, polarity, desc, amount)}
# Used when the actual cheque scan shows a specific condition that must match the fixture.
_RC_OVERRIDES: dict[int, tuple] = {
    3: ("NO_SIGNATURE", "STP_RETURN", "NEGATIVE",
        "NKGSB Bank — unsigned cheque → hard STP_RETURN", 5_000.0),
}

_BANKS = ["syndicate-bank", "axis-bank"]
_IFSCS = ["SYNB0003011",    "UTIB0000426"]

_MICR_POOL = [
    "500025033290062", "500211012426160", "600012003300456", "110003456789012",
    "400088900123456", "560044001230099", "700031122334455", "800099887766554",
    "300055411223344", "200011223344556", "900033445566778", "100022334455667",
]

_PAYEES = [
    "Pradeep Kumar", "Dinesh Kumar Vemula", "Rajarshi Pal", "Sunita Devi",
    "Prakash Joshi", "Rekha Sharma", "Suresh Patel", "Anita Singh",
    "Mohan Lal Gupta", "Vijay Kumar", "Kavita Mehta", "Arjun Reddy",
]


def _amt_range(amount: float) -> str:
    if amount < 100_000:    return "₹[<1L]"
    if amount < 500_000:    return "₹[1L-5L]"
    if amount < 1_000_000:  return "₹[5L-10L]"
    if amount < 10_000_000: return "₹[10L-1Cr]"
    return "₹[>1Cr]"


def _make_rc(idx: int, fpath: Path) -> ChequeFixture:
    if idx in _RC_OVERRIDES:
        trigger, exp_out, polarity, desc, amount = _RC_OVERRIDES[idx]
    else:
        trigger, exp_out, polarity, desc, amount = _RC_SCENARIOS[idx % len(_RC_SCENARIOS)]
    bank_idx = idx % 2
    bank_id  = _BANKS[bank_idx]
    bank_ifsc = _IFSCS[bank_idx]
    cheque_no = fpath.stem.replace("Cheque ", "CHQ").replace(" ", "")
    micr = _MICR_POOL[idx % len(_MICR_POOL)]
    payee = _PAYEES[idx % len(_PAYEES)]
    acct = f"300020{idx:07d}"

    return ChequeFixture(
        fixture_id=f"RC-{idx + 1:03d}",
        pipeline="INWARD",
        language="English",
        polarity=polarity,
        scenario=desc,
        trigger=trigger,
        expected_outcome=exp_out,
        instrument_id=f"CTS-RC-{idx + 1:03d}-{int(time.time()) % 100_000:05d}",
        bank_id=bank_id,
        amount=amount,
        amount_range=_amt_range(amount),
        payee_name=payee,
        account_number=acct,
        cheque_number=cheque_no,
        micr_line=micr,
        cheque_date=TODAY,
        bank_ifsc=bank_ifsc,
        cts_config=dict(DEFAULT_CTS_CONFIG),
    )


REAL_CHEQUE_FIXTURES: list[ChequeFixture] = [
    _make_rc(i, fp) for i, fp in enumerate(_REAL_CHEQUE_FILES)
]

REAL_CHEQUE_COUNT = len(REAL_CHEQUE_FIXTURES)
REAL_CHEQUE_IMAGE_PATHS: list[Path] = list(_REAL_CHEQUE_FILES)
