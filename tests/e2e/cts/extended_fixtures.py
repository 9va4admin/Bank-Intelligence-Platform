"""
Extended CTS E2E Fixtures — 80 additional synthetic cheques
============================================================
Crosses the 10 core inward scenario types with all 8 non-English languages
(8 × 10 = 80 fixtures).  IDs: EX-IN-001 … EX-IN-080.

Each fixture uses the SAME mock infrastructure and SAME expected outcome as
the matching trigger in cheque_fixtures.py — proving the pipeline is
language-agnostic (payee names, script encoding, Unicode don't affect routing).

Signature count by amount:
  < ₹20 L   →  1 signature
  ≥ ₹20 L   →  2 signatures (joint / high-value)
  MSV trigger →  3 required (3rd box unsigned = MSV fraud scenario)
"""
from __future__ import annotations

import time
from tests.e2e.cts.cheque_fixtures import (
    ChequeFixture,
    DEFAULT_CTS_CONFIG,
    TODAY,
)

# ─────────────────────────────────────────────────────────────────────────────
# Language data table
# ─────────────────────────────────────────────────────────────────────────────
# (language_label, bank_id, bank_ifsc, payee_STP, payee_FRAUD, payee_STOP)

_LANG: list[tuple] = [
    # label          bank_id                 ifsc          payee_stp                 payee_fraud           payee_stop
    ("Hindi",        "punjab-national-bank", "PUNB0123456","रामकृष्ण शर्मा",         "विजय गुप्ता",        "मोहन लाल"),
    ("Marathi",      "bank-of-maharashtra",  "MAHB0001122","सुनील देशपांडे",         "प्रकाश जोशी",        "राजेश पाटील"),
    ("Tamil",        "indian-bank",          "IDIB000T001","முத்துக்குமார் ஐயர்",    "சுப்ரமணியன்",       "கார்த்திக் ராஜ்"),
    ("Telugu",       "andhra-bank",          "ANDB0001234","వెంకట రమణ రెడ్డి",      "సురేష్ కుమార్",     "రాజేశ్వర రావు"),
    ("Kannada",      "canara-bank",          "CNRB0001234","ರಾಘವೇಂದ್ರ ಶರ್ಮ",       "ಪ್ರಕಾಶ್ ಹೆಗ್ಡೆ",   "ಮಂಜುನಾಥ ನಾಯಕ"),
    ("Gujarati",     "bank-of-baroda",       "BARB0001234","ભરત ભાઈ પટેલ",          "અમૃત દેસાઈ",        "ભૂપેન્દ્ર શાહ"),
    ("Bengali",      "uco-bank",             "UCBA0001234","সুব্রত চক্রবর্তী",      "অমিত বসু",           "রাহুল দাস"),
    ("Malayalam",    "south-indian-bank",    "SIBL0000123","ജോർജ് തോമസ് കുര്യൻ",  "ശ്രീകുമാർ നായർ",   "അഭിലാഷ് മേനോൻ"),
]

# ─────────────────────────────────────────────────────────────────────────────
# Scenario templates — (trigger, expected_outcome, amount, polarity, scenario_desc, date)
# ─────────────────────────────────────────────────────────────────────────────

_SCENARIOS: list[tuple] = [
    # trigger              expected_outcome   amount          polarity   desc                                         date
    ("CLEAN_ALL_PASS",     "STP_CONFIRM",     95_000.0,   "POSITIVE","All checks pass — clean STP confirm",          TODAY),
    ("STOP_PAYMENT_STP",   "STP_RETURN",      75_000.0,   "NEGATIVE","Stop-payment order in force",                  TODAY),
    ("OCR_LOW_CONF",       "HUMAN_REVIEW",    42_000.0,   "NEGATIVE","OCR confidence below threshold",               TODAY),
    ("ALTERATION",         "HUMAN_REVIEW",   110_000.0,   "NEGATIVE","Visible alteration detected",                  TODAY),
    ("FRAUD_HIGH",         "HUMAN_REVIEW",    88_000.0,   "NEGATIVE","Fraud score above threshold → human review",   TODAY),
    ("ACCOUNT_FROZEN",     "STP_RETURN",      55_000.0,   "NEGATIVE","Account frozen — hard STP return",             TODAY),
    ("CBS_INSUFFICIENT",   "STP_RETURN",     220_000.0,   "NEGATIVE","CBS balance insufficient — hard STP return",   TODAY),
    ("SIG_MISMATCH",       "HUMAN_REVIEW",    60_000.0,   "NEGATIVE","Signature match score below threshold",        TODAY),
    ("HIGH_VALUE_CLEAN",      "STP_CONFIRM",  2_500_000.0, "POSITIVE","High-value (≥20L) clean — 2 sigs required",   TODAY),
    ("WORDS_DIGITS_MISMATCH","HUMAN_REVIEW",    85_000.0, "NEGATIVE","Digit box tampered — words≠digits mismatch",  TODAY),
]

_ACCT_POOL = [
    "3000201010884", "9110100490015", "6200012345678", "1234567890123",
    "5000111222333", "7890001234567", "2200987654321", "4400123456789",
]
_MICR_POOL = [
    "500025033290062", "500211012426160", "600012003300456", "110003456789012",
    "400088900123456", "560044001230099", "700031122334455", "800099887766554",
]


def _fresh_iet_deadline() -> float:
    return time.time() + 3 * 3600


def _make(seq: int, lang_idx: int, scen_idx: int) -> ChequeFixture:
    lang_lbl, bank_id, ifsc, py_stp, py_fraud, py_stop = _LANG[lang_idx]
    trigger, exp_out, amount, polarity, desc, chq_date = _SCENARIOS[scen_idx]

    # Pick payee based on trigger
    if trigger in ("FRAUD_HIGH", "STOP_PAYMENT_STP", "SIG_MISMATCH"):
        payee = py_stop
    elif trigger in ("CLEAN_ALL_PASS", "HIGH_VALUE_CLEAN"):
        payee = py_stp
    else:
        payee = py_fraud

    fid  = f"EX-IN-{seq:03d}"
    iid  = f"CTS-{fid}-{int(time.time()) % 100_000:05d}"
    acct = _ACCT_POOL[seq % len(_ACCT_POOL)]
    micr = _MICR_POOL[seq % len(_MICR_POOL)]
    chq_no = f"EX{seq:05d}"

    if amount < 100_000:
        amt_range = "₹[<1L]"
    elif amount < 500_000:
        amt_range = "₹[1L-5L]"
    elif amount < 1_000_000:
        amt_range = "₹[5L-10L]"
    elif amount < 10_000_000:
        amt_range = "₹[10L-1Cr]"
    else:
        amt_range = "₹[>1Cr]"

    return ChequeFixture(
        fixture_id=fid,
        pipeline="INWARD",
        language=lang_lbl,
        polarity=polarity,
        scenario=desc,
        trigger=trigger,
        expected_outcome=exp_out,
        instrument_id=iid,
        bank_id=bank_id,
        amount=amount,
        amount_range=amt_range,
        payee_name=payee,
        account_number=acct,
        cheque_number=chq_no,
        micr_line=micr,
        cheque_date=chq_date,
        bank_ifsc=ifsc,
        cts_config=dict(DEFAULT_CTS_CONFIG),
    )


# Build 80 fixtures: 8 languages × 10 scenarios
EXTENDED_FIXTURES: list[ChequeFixture] = [
    _make(lang_idx * 10 + scen_idx + 1, lang_idx, scen_idx)
    for lang_idx in range(8)
    for scen_idx in range(10)
]

EXTENDED_COUNT = len(EXTENDED_FIXTURES)

assert EXTENDED_COUNT == 80, f"Expected 80 extended fixtures, got {EXTENDED_COUNT}"
