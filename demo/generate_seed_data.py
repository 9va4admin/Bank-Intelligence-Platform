#!/usr/bin/env python3
"""
ASTRA Demo - Seed Data Generator

Produces all demo/seed/*.json files for the 5-bank local Docker demo.
Run once before starting the Docker containers:
    python demo/generate_seed_data.py

Output files:
    demo/seed/banks.json
    demo/seed/customers.json
    demo/seed/cheques.json
    demo/seed/cbs_accounts.json
    demo/seed/signature_vault.json
    demo/seed/pps_records.json
    demo/seed/cancelled_leaves.json
    demo/seed/duplicate_registry.json
"""

import json
from pathlib import Path

OUT = Path(__file__).parent / "seed"
OUT.mkdir(exist_ok=True)


# ── Banks ─────────────────────────────────────────────────────────────────────

BANKS = [
    {
        "bank_id": "srcb",
        "name": "Saraswat Co-operative Bank Ltd.",
        "short": "Saraswat",
        "type": "SB",
        "ifsc_prefix": "SRCB",
        "micr_code": "400057001",
        "branch": "Fort Branch, Mumbai",
        "acct_prefix": "10010010",
        "color_primary": "#1a3a5c",
        "color_accent": "#c9a84c",
        "port_ui": 3001,
        "port_api": 8001,
        "docker_host": "srcb",
        "city": "Mumbai",
        "state": "Maharashtra",
        "established": 1918,
    },
    {
        "bank_id": "vvsb",
        "name": "Vasai Vikas Sahakari Bank Ltd.",
        "short": "Vasai Vikas",
        "type": "SMB",
        "ifsc_prefix": "VVSB",
        "micr_code": "401229001",
        "branch": "Vasai Main Branch",
        "acct_prefix": "20010010",
        "color_primary": "#1a5c3a",
        "color_accent": "#c9a84c",
        "port_ui": 3002,
        "port_api": 8002,
        "docker_host": "vvsb",
        "city": "Vasai",
        "state": "Maharashtra",
        "established": 1972,
    },
    {
        "bank_id": "kjsb",
        "name": "Kalyan Janata Sahakari Bank Ltd.",
        "short": "Kalyan Janata",
        "type": "SMB",
        "ifsc_prefix": "KJSB",
        "micr_code": "421301001",
        "branch": "Kalyan Main Branch",
        "acct_prefix": "30010010",
        "color_primary": "#5c1a3a",
        "color_accent": "#c9a84c",
        "port_ui": 3003,
        "port_api": 8003,
        "docker_host": "kjsb",
        "city": "Kalyan",
        "state": "Maharashtra",
        "established": 1955,
    },
    {
        "bank_id": "bcbk",
        "name": "Bharat Co-operative Bank (Mumbai) Ltd.",
        "short": "Bharat Co-op",
        "type": "SMB",
        "ifsc_prefix": "BCBK",
        "micr_code": "400058001",
        "branch": "Dadar Branch, Mumbai",
        "acct_prefix": "40010010",
        "color_primary": "#5c4a1a",
        "color_accent": "#c9a84c",
        "port_ui": 3004,
        "port_api": 8004,
        "docker_host": "bcbk",
        "city": "Mumbai",
        "state": "Maharashtra",
        "established": 1949,
    },
    {
        "bank_id": "ducb",
        "name": "Deccan Urban Co-operative Bank Ltd.",
        "short": "Deccan Urban",
        "type": "SMB",
        "ifsc_prefix": "DUCB",
        "micr_code": "411001001",
        "branch": "Pune Main Branch",
        "acct_prefix": "50010010",
        "color_primary": "#1a4a5c",
        "color_accent": "#c9a84c",
        "port_ui": 3005,
        "port_api": 8005,
        "docker_host": "ducb",
        "city": "Pune",
        "state": "Maharashtra",
        "established": 1963,
    },
]

# Drawee ring: each bank's customers deposit cheques drawn on the NEXT bank
# srcb→vvsb, vvsb→kjsb, kjsb→bcbk, bcbk→ducb, ducb→srcb
DRAWEE_RING = {
    "srcb": "vvsb",
    "vvsb": "kjsb",
    "kjsb": "bcbk",
    "bcbk": "ducb",
    "ducb": "srcb",
}

BANK_BY_ID = {b["bank_id"]: b for b in BANKS}


# ── Amount to words (Indian system) ──────────────────────────────────────────

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
         "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
         "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two_digits(n):
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")).strip()


def amount_to_words(amount: int) -> str:
    """Convert integer rupees to Indian English words."""
    if amount == 0:
        return "Zero Only"
    parts = []
    crore = amount // 10_000_000
    amount %= 10_000_000
    lakh = amount // 100_000
    amount %= 100_000
    thousand = amount // 1_000
    amount %= 1_000
    hundred = amount // 100
    remainder = amount % 100

    if crore:
        parts.append(_two_digits(crore) + " Crore")
    if lakh:
        parts.append(_two_digits(lakh) + " Lakh")
    if thousand:
        parts.append(_two_digits(thousand) + " Thousand")
    if hundred:
        parts.append(_ONES[hundred] + " Hundred")
    if remainder:
        parts.append(_two_digits(remainder))
    return " ".join(parts) + " Only"


# ── Customer definitions ──────────────────────────────────────────────────────
# (bank_id, idx, full_name, state, religion, community, acct_type, category, special)
# category codes: A=clean STP, B=amount mismatch, C=overwrite(VisionLLM),
#   D=date tamper(VisionLLM), E=cancelled(VisionLLM), G=duplicate,
#   I=sig mismatch, J=stop payment, K=insufficient, L=PPS mismatch, M=frozen

CUSTOMER_DEFS = [
    # ── SRCB (Sponsor Bank) ────────────────────────────────────────────────
    ("srcb", 1,  "Ramesh Kumar Sharma",           "Uttar Pradesh",     "Hindu",     "Brahmin",   "SAVINGS",  "A",
     {"amount": 120000}),
    ("srcb", 2,  "Priya Subramaniam",             "Tamil Nadu",        "Hindu",     "Iyer",      "CURRENT",  "A",
     {"amount": 1850000, "high_value": True}),
    ("srcb", 3,  "Mohammed Irfan Shaikh",         "Maharashtra",       "Muslim",    "Shaikh",    "SAVINGS",  "C",
     {"orig_amount": 9000,  "orig_words": "Nine Thousand Only",
      "fraud_amount": 90000, "fraud_words": "Ninety Thousand Only"}),
    ("srcb", 4,  "Anita Devi Rathore",            "Rajasthan",         "Hindu",     "Rajput",    "SAVINGS",  "D",
     {"amount": 125000,
      "orig_date": "15-01-2024", "tampered_date": "15-01-2026",
      "orig_year": "2024",  "new_year": "2026"}),
    ("srcb", 5,  "Cyrus Eruch Irani",             "Gujarat",           "Parsi",     "Irani",     "CURRENT",  "E",
     {"amount": 450000}),
    ("srcb", 6,  "Sunita Ramesh Patil",           "Maharashtra",       "Hindu",     "Maratha",   "SAVINGS",  "B",
     {"fig_amount": 35000,  "fig_words": "Thirty Five Thousand Only",
      "wrong_words": "Twenty Five Thousand Only"}),
    ("srcb", 7,  "Gurpreet Singh Bhatia",         "Punjab",            "Sikh",      "Khatri",    "SAVINGS",  "I",
     {"amount": 280000}),
    ("srcb", 8,  "Fatima Bi Hussain Ansari",      "Uttar Pradesh",     "Muslim",    "Ansari",    "SAVINGS",  "J",
     {"amount": 75000}),
    ("srcb", 9,  "Thomas Varghese Mathew",        "Kerala",            "Christian", "Syrian",    "CURRENT",  "L",
     {"amount": 750000, "pps_amount": 500000}),
    ("srcb", 10, "Meena Jayshree Patel",          "Gujarat",           "Hindu",     "Patidar",   "SAVINGS",  "K",
     {"amount": 120000, "cbs_balance": 45000}),

    # ── VVSB (SMB-1) ────────────────────────────────────────────────────
    ("vvsb", 1,  "Arvind Balkrishna Kulkarni",    "Maharashtra",       "Hindu",     "CKP",       "SAVINGS",  "A",
     {"amount": 185000}),
    ("vvsb", 2,  "Sujata Narayan Deshpande",      "Maharashtra",       "Hindu",     "Brahmin",   "CURRENT",  "A",
     {"amount": 1200000, "high_value": True}),
    ("vvsb", 3,  "Rashid Ahmed Khan",             "Delhi",             "Muslim",    "Pathan",    "SAVINGS",  "C",
     {"orig_amount": 4500,  "orig_words": "Four Thousand Five Hundred Only",
      "fraud_amount": 45000, "fraud_words": "Forty Five Thousand Only"}),
    ("vvsb", 4,  "Lakshmi Venkataraman Iyer",     "Tamil Nadu",        "Hindu",     "Iyer",      "SAVINGS",  "D",
     {"amount": 200000,
      "orig_date": "22-09-2024", "tampered_date": "22-09-2026",
      "orig_year": "2024",  "new_year": "2026"}),
    ("vvsb", 5,  "Jaya Shankar Hegde",            "Karnataka",         "Hindu",     "GSB",       "CURRENT",  "E",
     {"amount": 320000}),
    ("vvsb", 6,  "Bipasha Sen Mukherjee",         "West Bengal",       "Hindu",     "Kayastha",  "SAVINGS",  "B",
     {"fig_amount": 60000,  "fig_words": "Sixty Thousand Only",
      "wrong_words": "Sixteen Thousand Only"}),
    ("vvsb", 7,  "Manjit Kaur Grewal",            "Punjab",            "Sikh",      "Jat",       "SAVINGS",  "I",
     {"amount": 95000}),
    ("vvsb", 8,  "Abdul Razzak Qureshi",          "Uttar Pradesh",     "Muslim",    "Qureshi",   "CURRENT",  "J",
     {"amount": 180000}),
    ("vvsb", 9,  "Maria Conceicao D'Souza",       "Goa",               "Christian", "Catholic",  "SAVINGS",  "L",
     {"amount": 500000, "pps_amount": 375000}),
    ("vvsb", 10, "Hemant Baldevbhai Desai",       "Gujarat",           "Hindu",     "Vaishya",   "SAVINGS",  "M",
     {"amount": 225000}),

    # ── KJSB (SMB-2) ────────────────────────────────────────────────────
    ("kjsb", 1,  "Vikram Singh Yadav",            "Uttar Pradesh",     "Hindu",     "OBC",       "SAVINGS",  "A",
     {"amount": 310000}),
    ("kjsb", 2,  "Pushpa Ramesh Gowda",           "Karnataka",         "Hindu",     "Vokkaliga",  "CURRENT",  "A",
     {"amount": 2250000, "high_value": True}),
    ("kjsb", 3,  "Salim Abdul Siddiqui",          "Bihar",             "Muslim",    "Siddiqui",  "SAVINGS",  "C",
     {"orig_amount": 8000,  "orig_words": "Eight Thousand Only",
      "fraud_amount": 80000, "fraud_words": "Eighty Thousand Only"}),
    ("kjsb", 4,  "Kamala Krishnaswamy Pillai",    "Kerala",            "Hindu",     "Nair",      "SAVINGS",  "D",
     {"amount": 150000,
      "orig_date": "08-07-2024", "tampered_date": "08-07-2026",
      "orig_year": "2024",  "new_year": "2026"}),
    ("kjsb", 5,  "Boman Sorab Mistry",            "Maharashtra",       "Parsi",     "Mistry",    "CURRENT",  "E",
     {"amount": 750000}),
    ("kjsb", 6,  "Deepa Suresh Naik",             "Goa",               "Hindu",     "Gaud",      "SAVINGS",  "B",
     {"fig_amount": 42000,  "fig_words": "Forty Two Thousand Only",
      "wrong_words": "Twenty Four Thousand Only"}),
    ("kjsb", 7,  "Harinder Singh Sandhu",         "Punjab",            "Sikh",      "Jat",       "CURRENT",  "I",
     {"amount": 450000}),
    ("kjsb", 8,  "Shabana Hussain Ansari",        "Maharashtra",       "Muslim",    "Ansari",    "SAVINGS",  "J",
     {"amount": 110000}),
    ("kjsb", 9,  "George Antony Fernandes",       "Goa",               "Christian", "Catholic",  "CURRENT",  "L",
     {"amount": 350000, "pps_amount": 280000}),
    ("kjsb", 10, "Savita Prakash Joshi",          "Rajasthan",         "Hindu",     "Brahmin",   "SAVINGS",  "G",
     {"amount": 85000}),

    # ── BCBK (SMB-3) ────────────────────────────────────────────────────
    ("bcbk", 1,  "Suresh Baburao Jadhav",         "Maharashtra",       "Hindu",     "Maratha",   "SAVINGS",  "A",
     {"amount": 160000}),
    ("bcbk", 2,  "Radha Krishnan Menon",          "Kerala",            "Hindu",     "Nair",      "CURRENT",  "A",
     {"amount": 900000, "high_value": True}),
    ("bcbk", 3,  "Imran Farooq Sheikh",           "Jammu & Kashmir",   "Muslim",    "Sheikh",    "SAVINGS",  "C",
     {"orig_amount": 5500,  "orig_words": "Five Thousand Five Hundred Only",
      "fraud_amount": 55000, "fraud_words": "Fifty Five Thousand Only"}),
    ("bcbk", 4,  "Padmavathi Rajan Subramaniam",  "Tamil Nadu",        "Hindu",     "Brahmin",   "SAVINGS",  "D",
     {"amount": 75000,
      "orig_date": "30-11-2024", "tampered_date": "30-11-2026",
      "orig_year": "2024",  "new_year": "2026"}),
    ("bcbk", 5,  "Noshir Fali Contractor",        "Maharashtra",       "Parsi",     "Contractor", "CURRENT", "E",
     {"amount": 600000}),
    ("bcbk", 6,  "Rita Mohan Banerjee",           "West Bengal",       "Hindu",     "Brahmin",   "SAVINGS",  "B",
     {"fig_amount": 38000,  "fig_words": "Thirty Eight Thousand Only",
      "wrong_words": "Eighty Three Thousand Only"}),
    ("bcbk", 7,  "Kulwant Singh Dhillon",         "Punjab",            "Sikh",      "Jat",       "SAVINGS",  "I",
     {"amount": 170000}),
    ("bcbk", 8,  "Nasreen Begum Mirza",           "Uttar Pradesh",     "Muslim",    "Mirza",     "CURRENT",  "J",
     {"amount": 340000}),
    ("bcbk", 9,  "Lino Afonso Rodrigues",         "Goa",               "Christian", "Catholic",  "SAVINGS",  "L",
     {"amount": 250000, "pps_amount": 195000}),
    ("bcbk", 10, "Geeta Ramchandra Shekhawat",    "Rajasthan",         "Hindu",     "Rajput",    "SAVINGS",  "K",
     {"amount": 68000, "cbs_balance": 12000}),

    # ── DUCB (SMB-4) ────────────────────────────────────────────────────
    ("ducb", 1,  "Mahesh Dattatray Kale",         "Maharashtra",       "Hindu",     "Mali",      "SAVINGS",  "A",
     {"amount": 220000}),
    ("ducb", 2,  "Sumitra Gopal Krishnan",        "Tamil Nadu",        "Hindu",     "Mudaliar",  "CURRENT",  "A",
     {"amount": 1575000, "high_value": True}),
    ("ducb", 3,  "Wasim Akram Patel",             "Gujarat",           "Muslim",    "Patel",     "SAVINGS",  "C",
     {"orig_amount": 3500,  "orig_words": "Three Thousand Five Hundred Only",
      "fraud_amount": 35000, "fraud_words": "Thirty Five Thousand Only"}),
    ("ducb", 4,  "Champa Devi Mishra",            "Uttar Pradesh",     "Hindu",     "Brahmin",   "SAVINGS",  "D",
     {"amount": 180000,
      "orig_date": "14-04-2024", "tampered_date": "14-04-2026",
      "orig_year": "2024",  "new_year": "2026"}),
    ("ducb", 5,  "Pervez Hormusji Wadia",         "Maharashtra",       "Parsi",     "Wadia",     "CURRENT",  "E",
     {"amount": 850000}),
    ("ducb", 6,  "Aparajita Chowdhury Das",       "West Bengal",       "Hindu",     "Kayastha",  "SAVINGS",  "B",
     {"fig_amount": 52000,  "fig_words": "Fifty Two Thousand Only",
      "wrong_words": "Twenty Five Thousand Only"}),
    ("ducb", 7,  "Navdeep Kaur Randhawa",         "Punjab",            "Sikh",      "Jat",       "CURRENT",  "I",
     {"amount": 620000}),
    ("ducb", 8,  "Zainab Ali Shaikh",             "Maharashtra",       "Muslim",    "Shaikh",    "SAVINGS",  "J",
     {"amount": 260000}),
    ("ducb", 9,  "Mathew Chacko Thomas",          "Kerala",            "Christian", "Syrian",    "CURRENT",  "L",
     {"amount": 600000, "pps_amount": 410000}),
    ("ducb", 10, "Rajendra Babulal Mehta",        "Gujarat",           "Hindu",     "Vaishya",   "SAVINGS",  "M",
     {"amount": 380000}),
]

# Payees for each position (cycled across 50 cheques)
PAYEES = [
    "M/s Sunrise Trading Co.",
    "ABC Infrastructure Pvt. Ltd.",
    "National Co-operative Housing Society",
    "Raj Medical & Surgical Supplies",
    "Sharma & Sons Enterprises",
    "M/s Patel Agro Industries",
    "Karnataka Silk Weavers Co-op",
    "Kerala Cashew Export Board Ltd.",
    "Bengal Jute Corporation Ltd.",
    "Deccan Auto Components Pvt. Ltd.",
    "M/s Coastal Fisheries Co-op Society",
    "North India Construction Corp.",
    "M/s Himalayan Herbs & Spices Pvt. Ltd.",
    "Western India Textiles Ltd.",
    "Eastern Spice Traders Pvt. Ltd.",
    "M/s Apex Steel Fabricators",
    "Global Pharma Distributors",
    "Heritage Food Products Ltd.",
    "Pioneer Engineering Works",
    "United Builders & Developers",
    "M/s Ganesh Transport Services",
    "Lotus Agro Exports",
    "M/s New India Hardware Store",
    "Om Sai Construction Co.",
    "M/s Mahaveer Textiles",
    "M/s Silver Line Shipping",
    "Indian Ocean Marine Products",
    "M/s Crown Packaging Industries",
    "Rajdhani Logistics Pvt. Ltd.",
    "M/s Trimurti Chemical Works",
    "Excellent Realty Pvt. Ltd.",
    "Progressive Industries Ltd.",
    "Allied Technical Services",
    "M/s Metro Catering Supplies",
    "National Seeds Corporation Ltd.",
    "M/s Sai Krupa Enterprises",
    "M/s Hanuman Traders",
    "Coastal Infrastructure Dev. Corp.",
    "M/s Global IT Solutions",
    "Kerala Rubber Board Growers Co-op",
    "M/s Dharma Constructions",
    "Punjab Grains & Allied Trade",
    "M/s Nova Scientific Instruments",
    "Bengal Paper Mills Co-op Ltd.",
    "M/s Western Ghats Plantation Corp.",
    "M/s Indus Motor Dealers",
    "Rajasthan Gems & Jewellers Ltd.",
    "M/s Deccan Agricultural Co-op",
    "National Handloom Board",
    "M/s Saurashtra Salt Works",
]

# Cheque dates — all within recent valid period except Cat D (tampered)
CHEQUE_DATES = [
    "12-05-2026", "18-04-2026", "25-05-2026", "03-06-2026", "15-05-2026",
    "22-04-2026", "08-05-2026", "30-04-2026", "19-05-2026", "07-04-2026",
    "14-05-2026", "21-04-2026", "28-05-2026", "05-06-2026", "16-05-2026",
    "23-04-2026", "09-05-2026", "01-05-2026", "20-05-2026", "10-04-2026",
    "13-05-2026", "20-04-2026", "27-05-2026", "04-06-2026", "14-05-2026",
    "24-04-2026", "11-05-2026", "02-05-2026", "21-05-2026", "11-04-2026",
    "15-05-2026", "22-04-2026", "29-05-2026", "06-06-2026", "17-05-2026",
    "25-04-2026", "12-05-2026", "03-05-2026", "22-05-2026", "12-04-2026",
    "16-05-2026", "23-04-2026", "30-05-2026", "07-06-2026", "18-05-2026",
    "26-04-2026", "13-05-2026", "04-05-2026", "23-05-2026", "13-04-2026",
]


# ── Vision LLM analysis templates ────────────────────────────────────────────

def vision_llm_clean(model="Qwen2-VL-7B"):
    return {
        "alteration_detected": False,
        "void_stamp_detected": False,
        "overall_tamper_risk": 0.02,
        "confidence": 0.97,
        "model": model,
        "analysis": "No anomalies detected. All fields consistent. Ink density uniform across document. No correction fluid traces. Signature area deferred to Siamese SNN vault comparison.",
        "flagged_fields": [],
        "annotations": [],
        "ocr_vs_vision": {
            "verdict": "ALIGNED",
            "note": "OCR and Vision LLM outputs consistent. No divergence detected."
        }
    }


def vision_llm_overwrite(s):
    """Category C — overwritten amount."""
    return {
        "alteration_detected": True,
        "void_stamp_detected": False,
        "overall_tamper_risk": 0.93,
        "confidence": 0.97,
        "model": "Qwen2-VL-7B (L1) → Qwen2-VL-72B (L2 escalated)",
        "analysis": (
            f"CRITICAL ALERT: Amount field alteration detected. "
            f"Ink density analysis reveals two distinct writing layers in the amount figures field. "
            f"Primary (original) layer shows '₹{s['orig_amount']:,}' with ink absorption profile "
            f"consistent with original cheque fill. Secondary overwrite layer detected with 93% confidence — "
            f"correction fluid residue (UV signature detected) beneath overwrite. "
            f"Amount words field was also re-written over erasure. "
            f"Original instrument value: ₹{s['orig_amount']:,} ({s['orig_words']}). "
            f"Fraudulently altered to: ₹{s['fraud_amount']:,} ({s['fraud_words']}). "
            f"NOTE: OCR reads the overwritten value as valid — only Vision LLM ink-layer analysis "
            f"reveals the fraud. This is a classic cheque washing/overwrite fraud."
        ),
        "flagged_fields": ["amount_figures", "amount_words"],
        "annotations": [
            {
                "field": "amount_figures",
                "issue": "OVERWRITE_DETECTED",
                "bbox": {"x": 0.42, "y": 0.35, "w": 0.28, "h": 0.08},
                "original_value": f"₹{s['orig_amount']:,}",
                "current_value": f"₹{s['fraud_amount']:,}",
                "confidence": 0.93,
                "detail": "Ink pressure variance: original strokes at 0.8N, overwrite at 1.4N. Correction fluid UV signature positive.",
                "highlight_color": "#ff4444"
            },
            {
                "field": "amount_words",
                "issue": "OVERWRITE_DETECTED",
                "bbox": {"x": 0.08, "y": 0.44, "w": 0.72, "h": 0.07},
                "original_value": s["orig_words"],
                "current_value": s["fraud_words"],
                "confidence": 0.89,
                "detail": "Handwriting baseline inconsistency. Words field shows erasure marks beneath current text.",
                "highlight_color": "#ff4444"
            }
        ],
        "ocr_vs_vision": {
            "verdict": "DIVERGENT — FRAUD DETECTED",
            "ocr_reads": f"₹{s['fraud_amount']:,} — {s['fraud_words']} ← OCR PASSES",
            "vision_llm_detects": f"Original ₹{s['orig_amount']:,} — {s['orig_words']} ← VISION LLM OVERRIDES",
            "note": (
                "THIS IS THE KEY VALUE DIFFERENTIATOR: OCR cannot detect ink-layer anomalies. "
                "Vision LLM spatial reasoning identifies the original ink layer beneath the overwrite, "
                "catching a fraud that would pass conventional OCR processing."
            )
        }
    }


def vision_llm_date_tamper(s):
    """Category D — tampered date (year changed to avoid stale detection)."""
    return {
        "alteration_detected": True,
        "void_stamp_detected": False,
        "overall_tamper_risk": 0.88,
        "confidence": 0.96,
        "model": "Qwen2-VL-7B (L1) → Qwen2-VL-72B (L2 escalated)",
        "analysis": (
            f"CRITICAL ALERT: Date field tampering detected. "
            f"Year portion of date field shows ink inconsistency with the rest of the document. "
            f"Digit '{s['new_year']}' has a distinctly different ink absorption profile compared to "
            f"the day and month portions, which appear original. "
            f"Correction fluid (Whiteout/Tipp-Ex) residue detected beneath year digits — "
            f"UV channel shows characteristic bright bloom. "
            f"Original year reconstructed as '{s['orig_year']}', making this cheque stale "
            f"(issued {s['orig_date']}, now >90 days old). "
            f"The year was altered from '{s['orig_year']}' to '{s['new_year']}' to circumvent "
            f"the RBI stale cheque rule. "
            f"NOTE: OCR reads date as {s['tampered_date']} and PASSES the stale check. "
            f"Only Vision LLM ink analysis reveals the year was tampered."
        ),
        "flagged_fields": ["date"],
        "annotations": [
            {
                "field": "date",
                "issue": "DATE_YEAR_TAMPERING",
                "bbox": {"x": 0.65, "y": 0.17, "w": 0.22, "h": 0.07},
                "original_value": s["orig_date"],
                "current_value": s["tampered_date"],
                "confidence": 0.88,
                "detail": (
                    f"Year digits '{s['new_year']}' show: (1) higher ink density than remainder of date, "
                    f"(2) correction fluid UV bloom, (3) slight misalignment vs date baseline. "
                    f"Original year '{s['orig_year']}' reconstructed from residual ink traces."
                ),
                "highlight_color": "#ff8800"
            }
        ],
        "ocr_vs_vision": {
            "verdict": "DIVERGENT — DATE FRAUD DETECTED",
            "ocr_reads": f"Date: {s['tampered_date']} — VALID (not stale) ← OCR PASSES",
            "vision_llm_detects": (
                f"Original date: {s['orig_date']} — STALE (>{90} days old). "
                f"Year fraudulently altered {s['orig_year']}→{s['new_year']}. ← VISION LLM OVERRIDES"
            ),
            "note": (
                "OCR is a character reader — it cannot detect that '2026' was written over '2024'. "
                "Vision LLM's spatial ink analysis catches the physical tampering that OCR is blind to."
            )
        }
    }


def vision_llm_cancelled():
    """Category E — CANCELLED stamp (OCR misses it)."""
    return {
        "alteration_detected": False,
        "void_stamp_detected": True,
        "overall_tamper_risk": 0.97,
        "confidence": 0.98,
        "model": "Qwen2-VL-7B (L1)",
        "analysis": (
            "CRITICAL ALERT: CANCELLED instrument detected. "
            "A diagonal 'CANCELLED' bank stamp in red ink is overlaid across the face of this cheque. "
            "The stamp pattern is consistent with an official bank rubber stamp used to void instruments. "
            "Stamp dimensions: ~180mm diagonal, text height ~12mm, serif font consistent with standard bank voids. "
            "Red ink hue: 0°–8° (pure red channel dominant, green/blue <0.15). "
            "The stamp covers approximately 65% of the cheque face. "
            "CTS-2010 Rule 8.3 and RBI Circular DPSS.CO.CHD.No.1404/04.07.05/2012-13: "
            "Cancelled instruments must not be presented for clearing. "
            "NOTE: OCR successfully extracted all text fields from beneath the stamp overlay — "
            "OCR character recognition is not affected by the stamp but has no stamp-detection capability. "
            "Only Vision LLM spatial analysis identifies the void stamp."
        ),
        "flagged_fields": ["overall_image"],
        "annotations": [
            {
                "field": "overall_image",
                "issue": "VOID_STAMP_DETECTED",
                "bbox": {"x": 0.05, "y": 0.10, "w": 0.90, "h": 0.80},
                "confidence": 0.98,
                "detail": (
                    "Diagonal CANCELLED stamp detected. Red ink (R:220, G:32, B:28). "
                    "Stamp text: 'CANCELLED'. Orientation: 30° diagonal. "
                    "Coverage: 65% of instrument face. Official bank stamp pattern confirmed."
                ),
                "highlight_color": "#cc0000"
            }
        ],
        "ocr_vs_vision": {
            "verdict": "DIVERGENT — VOID INSTRUMENT DETECTED",
            "ocr_reads": "All text fields extracted successfully. Amount, payee, date — all valid. ← OCR PASSES",
            "vision_llm_detects": "CANCELLED stamp across instrument face. Void cheque. Must not be cleared. ← VISION LLM OVERRIDES",
            "note": (
                "OCR reads text. It does not understand that a red diagonal stamp means VOID. "
                "Vision LLM's document understanding recognises the stamp as a cancellation mark "
                "— a capability impossible with OCR alone."
            )
        }
    }


# ── Drawee account number assignment ─────────────────────────────────────────

# Each bank has 'drawer accounts' — accounts held by non-customers whose cheques
# are deposited at the presentee bank.
# These accounts exist in the DRAWEE bank's CBS/vault.

# Drawer account number scheme: drawee_bank.acct_prefix + "9" + 5-digit serial
# Series 90001-90005: reserved for drawee-side failure scenarios
# Series 90011-90050: regular accounts for Cat A cheques from each presentee bank

def drawer_acct(drawee_bank_id: str, serial: int) -> str:
    prefix = BANK_BY_ID[drawee_bank_id]["acct_prefix"]
    return f"{prefix}9{serial:05d}"


def drawer_name_for(cat: str, bank_id: str) -> str:
    """Name of the account holder at the drawee bank."""
    names = {
        "I":  {"srcb": "Devidas Narayan Limaye",    "vvsb": "Kantilal Ishwarbhai Vyas",
                "kjsb": "Ramamurthy Krishnaswamy",  "bcbk": "Bhimrao Sahebrao Gaikwad",
                "ducb": "Ambadas Tukaram Patil"},
        "J":  {"srcb": "Sunil Ramakant Sawant",     "vvsb": "Dilnawaz Hussain Siddiqui",
                "kjsb": "Pramod Bhaurao Wagh",      "bcbk": "Chandrakant Dinkar Kadam",
                "ducb": "Rajaram Vithal Shinde"},
        "K":  {"srcb": "Prashant Nandkumar Mane",   "vvsb": "Vishwanath Gopal Tathe",
                "kjsb": "Balasaheb Ganpat More",    "bcbk": "Shriram Bhimrao Jadhav",
                "ducb": "Dattatray Vishnu Lokhande"},
        "L":  {"srcb": "Ashok Narayan Bhosale",     "vvsb": "Ravindra Keshav Pawar",
                "kjsb": "Shailendra Kishor Desai",  "bcbk": "Vasant Laxman Kulkarni",
                "ducb": "Madhav Shankar Joshi"},
        "M":  {"srcb": "Dinkar Pandurang Chavan",   "vvsb": "Santosh Arun Kakade",
                "kjsb": "Vitthal Bapurao Khandare", "bcbk": "Sudhakar Ramrao Rane",
                "ducb": "Govind Sitaram Sawant"},
        "A":  {"srcb": "Nandkumar Pandit Deshpande", "vvsb": "Arun Balkrishna Salve",
                "kjsb": "Shripad Damodar Vaze",     "bcbk": "Moreshwar Ganesh Gokhale",
                "ducb": "Prakash Haribhau Shinde"},
        "A2": {"srcb": "Rajendra Vishnu Mahajan",   "vvsb": "Suresh Ramchandra Dhole",
                "kjsb": "Pradeep Vasant Kale",      "bcbk": "Dinesh Shankar Deshpande",
                "ducb": "Krishnarao Bhagwan Pol"},
    }
    return names.get(cat, {}).get(bank_id, "Ramesh Dattatray Khot")


# ── Build drawee processing data ─────────────────────────────────────────────

def build_drawee_processing(cat: str, cheque_amount: int, drawee_bank_id: str, special: dict):
    """Simulate what the drawee bank finds when it receives the inward cheque."""
    base = {
        "received_from_npci": True,
        "drawee_bank_id": drawee_bank_id,
        "iet_deadline_minutes": 180,
        "iet_risk": "LOW",
    }

    if cat in ("B", "C", "D", "E", "G", "H"):
        # Never reaches drawee — returned at presentment
        return None

    if cat == "A":
        return {**base,
            "signature_match_score": 0.94,
            "signature_verdict": "MATCH",
            "signature_specimens_checked": 2,
            "cbs_balance": cheque_amount + 125000,
            "balance_sufficient": True,
            "account_status": "ACTIVE",
            "stop_payment_active": False,
            "pps_registered": False,
            "pps_check_result": "NOT_APPLICABLE",
            "fraud_score": round(0.04 + (cheque_amount % 7) * 0.005, 3),
            "fraud_verdict": "CLEAN",
            "drawee_decision": "CONFIRM",
            "drawee_reason": None,
            "ngch_ack": f"NGCH-ACK-{drawee_bank_id.upper()}-{cheque_amount % 99999:05d}",
        }

    if cat == "I":
        return {**base,
            "signature_match_score": 0.41,
            "signature_verdict": "MISMATCH",
            "signature_specimens_checked": 2,
            "signature_detail": "SNN match score 0.41 below threshold 0.85. Neither of 2 registered specimens match. Recommend physical verification.",
            "cbs_balance": cheque_amount + 80000,
            "balance_sufficient": True,
            "account_status": "ACTIVE",
            "stop_payment_active": False,
            "pps_registered": False,
            "pps_check_result": "NOT_APPLICABLE",
            "fraud_score": 0.67,
            "fraud_verdict": "ELEVATED",
            "drawee_decision": "HUMAN_REVIEW",
            "drawee_reason": "SIGNATURE_MISMATCH",
            "drawee_reason_detail": f"Siamese SNN: match score 0.41 (threshold: 0.85). Specimen 1: 0.41, Specimen 2: 0.39. Neither specimen satisfies threshold. Routed to ops reviewer for physical cheque inspection.",
        }

    if cat == "J":
        return {**base,
            "signature_match_score": 0.91,
            "signature_verdict": "MATCH",
            "signature_specimens_checked": 2,
            "cbs_balance": cheque_amount + 50000,
            "balance_sufficient": True,
            "account_status": "ACTIVE",
            "stop_payment_active": True,
            "stop_payment_detail": "Stop payment instruction filed by account holder on 01-06-2026 14:22 IST. Reason: Cheque lost/stolen. Filed at home branch. Valid until 31-12-2026.",
            "pps_registered": False,
            "pps_check_result": "NOT_APPLICABLE",
            "fraud_score": 0.12,
            "fraud_verdict": "CLEAN",
            "drawee_decision": "AUTO_RETURN",
            "drawee_reason": "STOP_PAYMENT_ACTIVE",
            "drawee_reason_detail": "CBS confirms active stop payment instruction. Instrument returned per RBI guidelines. No further processing required.",
        }

    if cat == "K":
        cbs_balance = special.get("cbs_balance", 12000)
        return {**base,
            "signature_match_score": 0.92,
            "signature_verdict": "MATCH",
            "signature_specimens_checked": 2,
            "cbs_balance": cbs_balance,
            "balance_sufficient": False,
            "balance_shortfall": cheque_amount - cbs_balance,
            "account_status": "ACTIVE",
            "stop_payment_active": False,
            "pps_registered": False,
            "pps_check_result": "NOT_APPLICABLE",
            "fraud_score": 0.08,
            "fraud_verdict": "CLEAN",
            "drawee_decision": "RETURN",
            "drawee_reason": "INSUFFICIENT_FUNDS",
            "drawee_reason_detail": f"CBS: Available balance ₹{cbs_balance:,} < Cheque amount ₹{cheque_amount:,}. Shortfall: ₹{cheque_amount - cbs_balance:,}. Instrument returned per CTS-2010 Return Reason Code 30.",
        }

    if cat == "L":
        pps_amt = special["pps_amount"]
        chq_amt = special["amount"]
        return {**base,
            "signature_match_score": 0.93,
            "signature_verdict": "MATCH",
            "signature_specimens_checked": 2,
            "cbs_balance": chq_amt + 200000,
            "balance_sufficient": True,
            "account_status": "ACTIVE",
            "stop_payment_active": False,
            "pps_registered": True,
            "pps_registered_amount": pps_amt,
            "pps_cheque_amount": chq_amt,
            "pps_check_result": "MISMATCH",
            "pps_detail": f"PPS registered amount: ₹{pps_amt:,}. Presented amount: ₹{chq_amt:,}. Variance: ₹{chq_amt - pps_amt:,} ({round((chq_amt - pps_amt) / pps_amt * 100, 1)}% above registered). PPS policy: amounts must match exactly. Routed to human review.",
            "fraud_score": 0.51,
            "fraud_verdict": "SUSPICIOUS",
            "drawee_decision": "HUMAN_REVIEW",
            "drawee_reason": "PPS_AMOUNT_MISMATCH",
            "drawee_reason_detail": f"PPS amount ₹{pps_amt:,} ≠ presented ₹{chq_amt:,}. High-value instrument requires exact PPS match per bank policy.",
        }

    if cat == "M":
        return {**base,
            "signature_match_score": None,
            "signature_verdict": "NOT_CHECKED",
            "account_status": "FROZEN",
            "account_frozen_reason": "Court attachment order (Court Order No. CO-2026-HC-{}-{})".format(
                drawee_bank_id.upper(), cheque_amount % 9999),
            "account_frozen_date": "14-05-2026",
            "cbs_balance": None,
            "balance_sufficient": None,
            "stop_payment_active": False,
            "pps_registered": False,
            "pps_check_result": "NOT_APPLICABLE",
            "fraud_score": None,
            "fraud_verdict": "NOT_SCORED",
            "drawee_decision": "AUTO_RETURN",
            "drawee_reason": "ACCOUNT_FROZEN",
            "drawee_reason_detail": "CBS: Account status FROZEN. Court attachment active. All debits blocked. Instrument returned immediately without further processing.",
        }

    return base


# ── OCR output builder ────────────────────────────────────────────────────────

def build_ocr_output(cat: str, cheque_amount: int, amount_words: str,
                     payee: str, cheque_date: str, serial: str,
                     micr_line: str, special: dict):
    """What GOT-OCR2.0 extracts from the cheque image."""

    # For Cat C (overwrite fraud): OCR reads the FRAUD values — it was overwritten convincingly
    if cat == "C":
        ocr_amount_figures = special["fraud_amount"]
        ocr_words = special["fraud_words"]
        words_match = True  # fraudster also rewrote the words
        ocr_date = cheque_date
        flags = []
    elif cat == "D":
        # OCR reads the TAMPERED date (year was changed)
        ocr_amount_figures = cheque_amount
        ocr_words = amount_words
        words_match = True
        ocr_date = special["tampered_date"]
        flags = []
    elif cat == "B":
        # Amount mismatch — figures and words genuinely differ
        ocr_amount_figures = special["fig_amount"]
        ocr_words = special["wrong_words"]
        words_match = False
        ocr_date = cheque_date
        flags = ["AMOUNT_FIGURES_WORDS_MISMATCH"]
    else:
        ocr_amount_figures = cheque_amount
        ocr_words = amount_words
        words_match = True
        ocr_date = cheque_date
        flags = []

    # Stale cheque check (Cat D: OCR reads tampered date so passes)
    is_stale = False

    return {
        "engine": "GOT-OCR2.0",
        "serial_number": serial,
        "amount_figures": f"₹{ocr_amount_figures:,}",
        "amount_figures_raw": ocr_amount_figures,
        "amount_words": ocr_words,
        "amount_words_match": words_match,
        "payee_name": payee,
        "date": ocr_date,
        "is_stale": is_stale,
        "micr_line": micr_line,
        "confidence_overall": 0.978,
        "confidence_by_field": {
            "amount_figures": 0.99,
            "amount_words": 0.97,
            "payee_name": 0.98,
            "date": 0.99,
            "micr": 0.995,
        },
        "ocr_verdict": "FAIL" if flags else "PASS",
        "ocr_flags": flags,
    }


# ── Build a complete cheque record ────────────────────────────────────────────

def build_cheque(bank_id: str, cust_idx: int, name: str, cat: str, special: dict,
                 payee: str, cheque_date: str, global_idx: int):
    bank = BANK_BY_ID[bank_id]
    drawee_bank_id = DRAWEE_RING[bank_id]
    drawee_bank = BANK_BY_ID[drawee_bank_id]

    # Serial and account numbers
    serial = f"{100000 + global_idx:06d}"
    acct_num = f"{bank['acct_prefix']}{cust_idx:06d}"
    customer_id = f"{bank_id.upper()}-C{cust_idx:03d}"
    cheque_id = f"CHQ-{bank_id.upper()}-C{cust_idx:03d}-001"

    # Drawee account (at drawee bank)
    drawer_serial = 10 + global_idx
    drawer_acct_num = drawer_acct(drawee_bank_id, drawer_serial)
    drawer_name = drawer_name_for(cat if cat not in ("A",) else ("A" if cust_idx == 1 else "A2"), bank_id)

    # Amount
    if cat == "C":
        cheque_amount = special["fraud_amount"]   # what the cheque NOW shows (after fraud)
        amount_words = special["fraud_words"]
    elif cat == "B":
        cheque_amount = special["fig_amount"]
        amount_words = special["wrong_words"]     # intentionally wrong for this category
    else:
        cheque_amount = special.get("amount", 100000)
        amount_words = amount_to_words(cheque_amount)

    # MICR line: ⑈SERIAL⑆MICR_CODE⑉ACCT_SUFFIX
    acct_suffix = acct_num[-9:]
    micr_line = f"⑈{serial}⑆{drawee_bank['micr_code']}⑉{acct_suffix}"

    # OCR output
    ocr = build_ocr_output(cat, cheque_amount, amount_words, payee, cheque_date,
                           serial, micr_line, special)

    # Vision LLM output
    if cat == "C":
        vision = vision_llm_overwrite(special)
    elif cat == "D":
        vision = vision_llm_date_tamper(special)
    elif cat == "E":
        vision = vision_llm_cancelled()
    else:
        vision = vision_llm_clean()

    # CTS-2010 compliance
    cts_violations = []
    if cat == "H":
        cts_violations = [{"rule": "IMAGE_DPI", "detail": "DPI 68 < required 100"}]
    cts_compliance = {
        "checks_run": 8,
        "checks_passed": 8 - len(cts_violations),
        "violations": cts_violations,
        "passed": len(cts_violations) == 0,
    }

    # Presentment decision
    pres_decision_map = {
        "A": ("PASS",   None),
        "B": ("FAIL",   "AMOUNT_FIGURES_WORDS_MISMATCH"),
        "C": ("FLAGGED","VISION_LLM_ALTERATION_DETECTED"),
        "D": ("FLAGGED","VISION_LLM_DATE_TAMPERING_DETECTED"),
        "E": ("FAIL",   "CANCELLED_LEAF_DETECTED"),
        "F": ("FAIL",   "STALE_CHEQUE"),
        "G": ("FAIL",   "DUPLICATE_INSTRUMENT"),
        "H": ("FAIL",   "CTS_IMAGE_QUALITY_FAILURE"),
        "I": ("PASS",   None),
        "J": ("PASS",   None),
        "K": ("PASS",   None),
        "L": ("PASS",   None),
        "M": ("PASS",   None),
    }
    pres_decision, pres_reason = pres_decision_map.get(cat, ("PASS", None))

    # Final decision
    final_map = {
        "A": ("STP_CONFIRM",  None),
        "B": ("HUMAN_REVIEW", "AMOUNT_FIGURES_WORDS_MISMATCH"),
        "C": ("HUMAN_REVIEW", "ALTERATION_DETECTED"),
        "D": ("HUMAN_REVIEW", "DATE_TAMPERING_DETECTED"),
        "E": ("AUTO_RETURN",  "CANCELLED_LEAF_DETECTED"),
        "F": ("AUTO_RETURN",  "STALE_CHEQUE"),
        "G": ("AUTO_RETURN",  "DUPLICATE_INSTRUMENT"),
        "H": ("RETURN",       "CTS_IMAGE_QUALITY_FAILURE"),
        "I": ("HUMAN_REVIEW", "SIGNATURE_MISMATCH"),
        "J": ("AUTO_RETURN",  "STOP_PAYMENT_ACTIVE"),
        "K": ("RETURN",       "INSUFFICIENT_FUNDS"),
        "L": ("HUMAN_REVIEW", "PPS_AMOUNT_MISMATCH"),
        "M": ("AUTO_RETURN",  "ACCOUNT_FROZEN"),
    }
    final_decision, final_reason = final_map.get(cat, ("HUMAN_REVIEW", "UNKNOWN"))

    # Drawee processing
    drawee_proc = build_drawee_processing(cat, cheque_amount, drawee_bank_id, special)

    # Lot assignment (only for presentment-passed cheques)
    lot_id = f"LOT-{bank_id.upper()}-{(global_idx // 10) + 1:03d}" if pres_decision == "PASS" else None

    return {
        "cheque_id": cheque_id,
        "customer_id": customer_id,
        "customer_name": name,
        "serial_number": serial,
        "cheque_date": cheque_date,
        "payee_name": payee,
        "amount_figures": cheque_amount,
        "amount_words": amount_words,
        "micr_line": micr_line,

        "presentee_bank_id": bank_id,
        "presentee_bank_name": bank["name"],
        "presentee_account": acct_num,
        "presentee_ifsc": f"{bank['ifsc_prefix']}0000001",

        "drawee_bank_id": drawee_bank_id,
        "drawee_bank_name": drawee_bank["name"],
        "drawee_account": drawer_acct_num,
        "drawee_customer_name": drawer_name,
        "drawee_ifsc": f"{drawee_bank['ifsc_prefix']}0000001",

        "category": cat,
        "category_description": {
            "A": "Clean STP — passes all checks",
            "B": "Amount figures vs words mismatch — OCR detects",
            "C": "Overwritten amount — OCR misses, Vision LLM catches",
            "D": "Tampered date (year changed) — OCR misses, Vision LLM catches",
            "E": "CANCELLED stamp — OCR misses, Vision LLM catches",
            "F": "Stale cheque (>90 days) — rule engine",
            "G": "Duplicate instrument — registry check",
            "H": "CTS image quality failure",
            "I": "Signature mismatch — drawee vault",
            "J": "Stop payment active — drawee CBS",
            "K": "Insufficient funds — drawee CBS",
            "L": "PPS amount mismatch — drawee PPS vault",
            "M": "Account frozen — drawee CBS",
        }.get(cat, "Unknown"),

        "image_paths": {
            "front_bw":   f"images/{bank_id}/{cheque_id}_front_bw.jpg",
            "front_gray": f"images/{bank_id}/{cheque_id}_front_gray.jpg",
            "front_uv":   f"images/{bank_id}/{cheque_id}_front_uv.jpg",
            "back_bw":    f"images/{bank_id}/{cheque_id}_back_bw.jpg",
            "back_gray":  f"images/{bank_id}/{cheque_id}_back_gray.jpg",
        },

        "ocr_output": ocr,
        "vision_llm_output": vision,
        "cts_compliance": cts_compliance,

        "lot_id": lot_id,
        "presentment_decision": pres_decision,
        "presentment_reason": pres_reason,

        "drawee_processing": drawee_proc,

        "final_decision": final_decision,
        "final_reason": final_reason,

        "return_reason_code": {
            "AMOUNT_FIGURES_WORDS_MISMATCH": "20",
            "ALTERATION_DETECTED":           "14",
            "DATE_TAMPERING_DETECTED":       "14",
            "CANCELLED_LEAF_DETECTED":       "26",
            "STALE_CHEQUE":                  "08",
            "DUPLICATE_INSTRUMENT":          "25",
            "CTS_IMAGE_QUALITY_FAILURE":     "95",
            "SIGNATURE_MISMATCH":            "22",
            "STOP_PAYMENT_ACTIVE":           "16",
            "INSUFFICIENT_FUNDS":            "30",
            "PPS_AMOUNT_MISMATCH":           "23",
            "ACCOUNT_FROZEN":                "28",
        }.get(final_reason, "00"),
    }


# ── Customer record builder ───────────────────────────────────────────────────

def build_customer(bank_id, idx, name, state, religion, community, acct_type, _cat, special):
    bank = BANK_BY_ID[bank_id]
    acct_num = f"{bank['acct_prefix']}{idx:06d}"
    # Mobile: realistic 10-digit Indian mobile
    mobile = f"9{bank['port_api']}{idx:07d}"[-10:]

    return {
        "customer_id": f"{bank_id.upper()}-C{idx:03d}",
        "bank_id": bank_id,
        "name": name,
        "name_initials": "".join(w[0] for w in name.split()[:2]).upper(),
        "state": state,
        "religion": religion,
        "community": community,
        "account_number": acct_num,
        "account_type": acct_type,
        "ifsc": f"{bank['ifsc_prefix']}0000001",
        "mobile": f"9{80000 + bank['port_ui'] * 10 + idx:07d}"[:10],
        "email": f"{name.split()[0].lower()}.{name.split()[-1].lower()}{idx:02d}@email.in",
        "address": f"{idx * 7 + 1}/A, {'Shastri' if idx % 3 == 0 else 'Gandhi' if idx % 3 == 1 else 'Nehru'} Nagar, {bank['city']}",
        "branch": bank["branch"],
        "signature_specimen_paths": [
            f"images/{bank_id}/{bank_id.upper()}-C{idx:03d}_specimen_1.jpg",
            f"images/{bank_id}/{bank_id.upper()}-C{idx:03d}_specimen_2.jpg",
        ],
    }


# ── CBS accounts (drawer side — at drawee banks) ──────────────────────────────

def build_cbs_accounts():
    accounts = {}
    for defn in CUSTOMER_DEFS:
        bank_id, idx, name, state, religion, community, acct_type, cat, special = defn
        drawee_bank_id = DRAWEE_RING[bank_id]
        drawer_serial = 10 + (CUSTOMER_DEFS.index(defn))
        acct = drawer_acct(drawee_bank_id, drawer_serial)
        cheque_amount = special.get("amount", special.get("fraud_amount", special.get("fig_amount", 100000)))

        if cat == "A":
            acct_data = {
                "account_number": acct,
                "bank_id": drawee_bank_id,
                "status": "ACTIVE",
                "balance": cheque_amount + 125000,
                "stop_payment_active": False,
                "stop_payment_details": None,
                "frozen_reason": None,
            }
        elif cat == "I":
            acct_data = {
                "account_number": acct, "bank_id": drawee_bank_id,
                "status": "ACTIVE", "balance": cheque_amount + 80000,
                "stop_payment_active": False, "stop_payment_details": None, "frozen_reason": None,
            }
        elif cat == "J":
            acct_data = {
                "account_number": acct, "bank_id": drawee_bank_id,
                "status": "ACTIVE", "balance": cheque_amount + 50000,
                "stop_payment_active": True,
                "stop_payment_details": {
                    "filed_on": "01-06-2026 14:22",
                    "reason": "Cheque lost / stolen",
                    "valid_until": "31-12-2026",
                    "filed_at": f"{BANK_BY_ID[drawee_bank_id]['branch']}",
                },
                "frozen_reason": None,
            }
        elif cat == "K":
            cbs_balance = special.get("cbs_balance", 12000)
            acct_data = {
                "account_number": acct, "bank_id": drawee_bank_id,
                "status": "ACTIVE", "balance": cbs_balance,
                "stop_payment_active": False, "stop_payment_details": None, "frozen_reason": None,
            }
        elif cat == "L":
            acct_data = {
                "account_number": acct, "bank_id": drawee_bank_id,
                "status": "ACTIVE", "balance": special["amount"] + 200000,
                "stop_payment_active": False, "stop_payment_details": None, "frozen_reason": None,
            }
        elif cat == "M":
            acct_data = {
                "account_number": acct, "bank_id": drawee_bank_id,
                "status": "FROZEN",
                "balance": None,
                "stop_payment_active": False,
                "stop_payment_details": None,
                "frozen_reason": f"Court attachment order CO-2026-HC-{drawee_bank_id.upper()}-{idx:04d}",
                "frozen_date": "14-05-2026",
            }
        else:
            # Cat B, C, D, E, G, H — cheque never reaches drawee; account still exists
            acct_data = {
                "account_number": acct, "bank_id": drawee_bank_id,
                "status": "ACTIVE", "balance": cheque_amount + 100000,
                "stop_payment_active": False, "stop_payment_details": None, "frozen_reason": None,
            }

        accounts[acct] = acct_data
    return accounts


# ── Signature vault ───────────────────────────────────────────────────────────

def build_signature_vault():
    vault = {}
    for defn in CUSTOMER_DEFS:
        bank_id, idx, name, state, religion, community, acct_type, cat, special = defn
        drawee_bank_id = DRAWEE_RING[bank_id]
        drawer_serial = 10 + CUSTOMER_DEFS.index(defn)
        acct = drawer_acct(drawee_bank_id, drawer_serial)

        if cat == "I":
            vault[acct] = {
                "account_number": acct,
                "bank_id": drawee_bank_id,
                "specimens": [
                    {"path": f"images/{drawee_bank_id}/{acct}_specimen_1.jpg", "enrolled_on": "12-03-2024"},
                    {"path": f"images/{drawee_bank_id}/{acct}_specimen_2.jpg", "enrolled_on": "12-03-2024"},
                ],
                "match_threshold": 0.85,
                "note": "Signature mismatch scenario — cheque signature deliberately different from specimens",
            }
        else:
            vault[acct] = {
                "account_number": acct,
                "bank_id": drawee_bank_id,
                "specimens": [
                    {"path": f"images/{drawee_bank_id}/{acct}_specimen_1.jpg", "enrolled_on": "15-01-2024"},
                    {"path": f"images/{drawee_bank_id}/{acct}_specimen_2.jpg", "enrolled_on": "15-01-2024"},
                ],
                "match_threshold": 0.85,
                "note": "Regular account — signatures should match",
            }
    return vault


# ── PPS records ───────────────────────────────────────────────────────────────

def build_pps_records():
    records = {}
    for defn in CUSTOMER_DEFS:
        bank_id, idx, name, state, religion, community, acct_type, cat, special = defn
        if cat != "L":
            continue
        drawee_bank_id = DRAWEE_RING[bank_id]
        drawer_serial = 10 + CUSTOMER_DEFS.index(defn)
        acct = drawer_acct(drawee_bank_id, drawer_serial)
        pps_amt = special["pps_amount"]
        chq_amt = special["amount"]

        records[acct] = {
            "account_number": acct,
            "bank_id": drawee_bank_id,
            "registered_amount": pps_amt,
            "registered_amount_words": amount_to_words(pps_amt),
            "payee": PAYEES[(CUSTOMER_DEFS.index(defn) + 8) % len(PAYEES)],
            "registered_on": "10-05-2026",
            "valid_until": "10-06-2026",
            "note": f"Cheque will present for ₹{chq_amt:,} but PPS shows ₹{pps_amt:,} → MISMATCH",
        }
    return records


# ── Cancelled leaves ──────────────────────────────────────────────────────────

def build_cancelled_leaves():
    leaves = {}
    for defn in CUSTOMER_DEFS:
        bank_id, idx, name, state, religion, community, acct_type, cat, special = defn
        if cat != "E":
            continue
        drawee_bank_id = DRAWEE_RING[bank_id]
        drawer_serial = 10 + CUSTOMER_DEFS.index(defn)
        acct = drawer_acct(drawee_bank_id, drawer_serial)
        global_idx = CUSTOMER_DEFS.index(defn)
        serial = f"{100000 + global_idx:06d}"

        leaves[acct] = {
            "account_number": acct,
            "bank_id": drawee_bank_id,
            "cancelled_serials": [serial],
            "cancelled_series": [{"from": serial, "to": serial}],
            "note": "Cheque marked CANCELLED by account holder on 15-04-2026",
        }
    return leaves


# ── Duplicate registry ────────────────────────────────────────────────────────

def build_duplicate_registry(cheques):
    """KJSB customer 10 (Savita Joshi, Cat G) has a duplicate entry."""
    registry = {}
    for chq in cheques:
        if chq["category"] == "G":
            import hashlib
            key = hashlib.sha256(
                f"{chq['presentee_bank_id']}:{chq['drawee_account']}:{chq['serial_number']}:{chq['amount_figures']}".encode()
            ).hexdigest()[:32]
            registry[key] = {
                "instrument_hash": key,
                "serial_number": chq["serial_number"],
                "drawee_account": chq["drawee_account"],
                "amount_figures": chq["amount_figures"],
                "first_presented_on": "20-05-2026 09:14",
                "first_presented_by": chq["presentee_bank_id"],
                "note": "This cheque was already cleared on 20-05-2026. Second presentation is a duplicate.",
            }
    return registry


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("ASTRA Demo Seed Data Generator")
    print("=" * 50)

    # 1. Banks
    write_json("banks.json", BANKS)
    print(f"  [OK] banks.json -- {len(BANKS)} banks")

    # 2. Customers
    customers = []
    for defn in CUSTOMER_DEFS:
        bank_id, idx, name, state, religion, community, acct_type, cat, special = defn
        customers.append(build_customer(bank_id, idx, name, state, religion, community, acct_type, cat, special))
    write_json("customers.json", customers)
    print(f"  [OK] customers.json -- {len(customers)} customers across {len(BANKS)} banks")

    # 3. Cheques
    cheques = []
    for i, defn in enumerate(CUSTOMER_DEFS):
        bank_id, idx, name, state, religion, community, acct_type, cat, special = defn
        payee = PAYEES[i % len(PAYEES)]
        date = CHEQUE_DATES[i % len(CHEQUE_DATES)]
        chq = build_cheque(bank_id, idx, name, cat, special, payee, date, i)
        cheques.append(chq)
    write_json("cheques.json", cheques)
    print(f"  [OK] cheques.json -- {len(cheques)} cheques")

    # Breakdown by category
    from collections import Counter
    cats = Counter(c["category"] for c in cheques)
    for cat in sorted(cats):
        print(f"      Cat {cat}: {cats[cat]} cheques")

    # 4. CBS accounts
    cbs = build_cbs_accounts()
    write_json("cbs_accounts.json", cbs)
    print(f"  [OK] cbs_accounts.json -- {len(cbs)} drawer accounts")

    # 5. Signature vault
    vault = build_signature_vault()
    write_json("signature_vault.json", vault)
    print(f"  [OK] signature_vault.json -- {len(vault)} accounts")

    # 6. PPS records
    pps = build_pps_records()
    write_json("pps_records.json", pps)
    print(f"  [OK] pps_records.json -- {len(pps)} PPS records")

    # 7. Cancelled leaves
    leaves = build_cancelled_leaves()
    write_json("cancelled_leaves.json", leaves)
    print(f"  [OK] cancelled_leaves.json -- {len(leaves)} cancelled accounts")

    # 8. Duplicate registry
    dup_reg = build_duplicate_registry(cheques)
    write_json("duplicate_registry.json", dup_reg)
    print(f"  [OK] duplicate_registry.json -- {len(dup_reg)} duplicate entries")

    print()
    print("All seed data written to demo/seed/")
    print()
    print("Next: python demo/generate_images.py")


def write_json(filename: str, data):
    path = OUT / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
