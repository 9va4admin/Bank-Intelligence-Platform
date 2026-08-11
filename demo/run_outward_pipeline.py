"""
Outward Pipeline Demo Runner — with Payee Account Validation
-------------------------------------------------------------
Picks real cheque images from demo/112/, extracts actual image metrics,
and drives OutwardScanWorkflow.run_with_mocks().

Payee validation uses the real cts.account_vault table (YugabyteDB).
CTS-2010 compliance uses InstrumentComplianceRecord (actual compliance/models.py).
Covers all 4 payee outcomes: PROCEED / NOT_FOUND / INACTIVE / NAME_MISMATCH.
Joint accounts: name matched against ALL holders in holder_names JSONB array.

Usage:  python demo/run_outward_pipeline.py
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from PIL import Image

DEMO_DIR  = Path(__file__).parent / "112"
BANK_ID   = "saraswat-coop"
BANK_IFSC = "SRCB0000001"

# Seeded test accounts (see demo seed script)
ACCT_ACTIVE_MATCH    = "100000000009"   # ACTIVE, joint: R***+V*** -> PROCEED when slip name starts V
ACCT_ACTIVE_MISMATCH = "100000000018"   # ACTIVE, P*** -> NAME_MISMATCH when slip starts with K
ACCT_FROZEN          = "100000000027"   # FROZEN -> ACCOUNT_INACTIVE
ACCT_UNKNOWN         = "999999999999"   # not in vault or CBS -> ACCOUNT_NOT_FOUND

DB_URL = "postgresql://yugabyte@localhost:15433/yugabyte"
PEPPER = "dev-pepper-saraswat-coop"


# ── Account Vault helper (direct DB read for demo) ────────────────────────────

def _acct_hash(account_number: str) -> str:
    return hmac.new(PEPPER.encode(), f"{BANK_ID}:{account_number}".encode(), hashlib.sha256).hexdigest()


def lookup_account_vault(account_number: str):
    """Return SimpleNamespace with vault row or None if not found.
    Reads holder_names JSONB (migration 20260811_account_vault_add_holder_names).
    Falls back to [holder_name_display] on older schema (column absent).
    """
    try:
        import psycopg2
        conn = psycopg2.connect(DB_URL)
        cur  = conn.cursor()
        cur.execute(
            """SELECT account_number_last4, account_status, holder_name_display,
                      holder_names
               FROM cts.account_vault
               WHERE bank_id=%s AND account_hash=%s""",
            (BANK_ID, _acct_hash(account_number)),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            raw_names = row[3]
            if isinstance(raw_names, str):
                all_holders = json.loads(raw_names)
            elif isinstance(raw_names, list):
                all_holders = raw_names
            else:
                all_holders = []
            if not all_holders and row[2]:
                all_holders = [row[2]]
            return SimpleNamespace(last4=row[0], account_status=row[1],
                                   holder_name_display=row[2], all_holders=all_holders)
        return None
    except Exception as exc:
        print(f"  [DB] {exc}")
        return None


def _name_matches_any(name_on_slip: str, all_holders: list[str]) -> tuple[bool, str | None]:
    """Check slip name first initial against EVERY holder — handles joint accounts."""
    if not name_on_slip or not all_holders:
        return False, None
    slip_initial = name_on_slip.strip()[0].upper()
    for h in all_holders:
        if h and h[0].upper() == slip_initial:
            return True, h
    return False, None


def make_payee_result(account_number: str, name_on_slip: str | None):
    """
    Simulate validate_payee_account using real vault data.
    Name match checks ALL holders in holder_names array (joint account support).
    """
    row = lookup_account_vault(account_number)

    if row is None:
        return SimpleNamespace(outcome="ACCOUNT_NOT_FOUND", account_status=None,
                               name_match_score=None, vault_hit=False, payee_display="***",
                               all_holders=[])

    if row.account_status in ("FROZEN", "CLOSED", "DORMANT", "NPA"):
        return SimpleNamespace(outcome="ACCOUNT_INACTIVE", account_status=row.account_status,
                               name_match_score=None, vault_hit=True,
                               payee_display=row.holder_name_display,
                               all_holders=row.all_holders)

    if name_on_slip:
        matched, matched_holder = _name_matches_any(name_on_slip, row.all_holders)
        if not matched:
            return SimpleNamespace(outcome="NAME_MISMATCH", account_status=row.account_status,
                                   name_match_score=0.3, vault_hit=True,
                                   payee_display=row.holder_name_display,
                                   all_holders=row.all_holders,
                                   matched_holder=None)

    return SimpleNamespace(outcome="PROCEED", account_status=row.account_status,
                           name_match_score=1.0, vault_hit=True,
                           payee_display=row.holder_name_display,
                           all_holders=getattr(row, 'all_holders', []))


# ── Image metrics ─────────────────────────────────────────────────────────────

def extract_metrics(path: Path):
    img = Image.open(path)
    w, h = img.size
    info = img.info
    dpi  = info.get("dpi", (200.0, 200.0))
    try:
        dpi_x = float(dpi[0])
    except Exception:
        dpi_x = 200.0
    depth = {"1": 1, "L": 8, "P": 8, "RGB": 24, "RGBA": 32}.get(img.mode, 24)
    return SimpleNamespace(
        width=w, height=h, dpi=int(dpi_x),
        colour_depth=depth, file_kb=round(path.stat().st_size / 1024, 1),
    )


# ── Pipeline runner ───────────────────────────────────────────────────────────

async def run_one(filename: str, scenario: str,
                  payee_account: str | None, payee_name: str | None) -> dict:
    path    = DEMO_DIR / filename
    metrics = extract_metrics(path)
    cheque_num   = filename.replace("Cheque ", "").replace(".jpeg", "").strip()
    scan_id      = f"SCAN-20260811-{cheque_num}"
    instrument_id = f"INS-{scan_id}"

    from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow, OutwardScanInput

    inp = OutwardScanInput(
        scan_id=scan_id,
        instrument_id=instrument_id,
        bank_id=BANK_ID,
        bank_ifsc=BANK_IFSC,
        session_id="SESSION-AM-20260811",
        image_front_url=f"s3://cts-images/{BANK_ID}/outward/{scan_id}/front.tiff",
        image_rear_url=f"s3://cts-images/{BANK_ID}/outward/{scan_id}/rear.tiff",
        cheque_number=cheque_num,
        front_dpi=200,
        rear_dpi=200,
        front_colour_depth=metrics.colour_depth,
        rear_colour_depth=metrics.colour_depth,
        front_file_size_kb=metrics.file_kb,
        rear_file_size_kb=metrics.file_kb,
        payee_account_number=payee_account,
        payee_name_from_slip=payee_name,
    )

    micr = SimpleNamespace(
        micr_line=f"C{cheque_num}C 000100009C 509180047C",
        amount_figures="50000.00",
        date="11-08-2026",
        overall_confidence=0.94,
        degraded=False,
        ifsc_code=None,
    )

    payee_mock = make_payee_result(payee_account, payee_name) if payee_account else None

    # Use actual InstrumentComplianceRecord — not a hardcoded stub
    from modules.cts.compliance.models import InstrumentComplianceRecord
    from modules.cts.workflows.activities.outward_scan_activities import CTS2010ValidationResult
    compliance_rec = InstrumentComplianceRecord(
        instrument_id=instrument_id, cheque_number=cheque_num, lot_number="",
        front_dpi=metrics.dpi, front_colour_depth=metrics.colour_depth,
        front_file_size_kb=metrics.file_kb, front_iqa_score=0.92,
        rear_dpi=0, rear_colour_depth=8, rear_file_size_kb=0.0, rear_iqa_score=0.0,
        micr_band_score=0.92,
        rear_image_required=False,  # bank default — blank reverse is not a failure
    )
    compliance_mock = CTS2010ValidationResult(
        is_compliant=compliance_rec.is_compliant,
        violations=compliance_rec.failure_reasons,
    )

    mock_results = {
        "micr":       micr,
        "compliance": compliance_mock,
        "vision_llm": SimpleNamespace(has_mismatch=False, mismatch_fields=[]),
        "payee":      payee_mock,
        "audit":      None,
    }

    wf = OutwardScanWorkflow()
    result = await wf.run_with_mocks(inp, mock_results)

    vault_info = ""
    if payee_mock:
        all_h = getattr(payee_mock, 'all_holders', [])
        holders_str = ' + '.join(all_h) if len(all_h) > 1 else (all_h[0] if all_h else getattr(payee_mock,'payee_display','—'))
        vault_info = (
            f"vault={'HIT' if getattr(payee_mock,'vault_hit',False) else 'MISS'}  "
            f"status={getattr(payee_mock,'account_status','—')}  "
            f"holders=[{holders_str}]"
        )

    return {
        "file":       filename,
        "cheque_num": cheque_num,
        "scenario":   scenario,
        "image":      f"{metrics.width}x{metrics.height}  {metrics.colour_depth}bpp  {metrics.file_kb}KB  DPI={metrics.dpi}",
        "payee_acct": f"...{payee_account[-4:]}" if payee_account else "(none)",
        "payee_name": payee_name or "(none)",
        "vault_info": vault_info,
        "outcome":    result.outcome,
        "violations": result.violations or [],
        "mismatch_id": result.mismatch_id or "",
    }


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    jobs = [
        # (filename,              scenario,           payee_account,       payee_name_on_slip)
        ("Cheque 083654.jpeg",  "PAYEE_MATCH",       ACCT_ACTIVE_MATCH,   "Ramesh Joshi"),
        ("Cheque 100828.jpeg",  "NAME_MISMATCH",     ACCT_ACTIVE_MISMATCH,"Kiran Desai"),
        ("Cheque 120611.jpeg",  "ACCT_FROZEN",       ACCT_FROZEN,         "Sanjay Patil"),
        ("Cheque 309062.jpeg",  "ACCT_NOT_FOUND",    ACCT_UNKNOWN,        "Anil Kumar"),
        ("Cheque 309091.jpeg",  "NO_PAYEE_SUPPLIED", None,                None),
    ]

    print()
    print("=" * 108)
    print("  ASTRA CTS  -  Outward Pipeline with Payee Account Validation")
    print("  Real cheque images  |  Real account_vault DB lookup  |  run_with_mocks()")
    print("=" * 108)
    print()

    results = []
    for filename, scenario, payee_acct, payee_name in jobs:
        try:
            r = await run_one(filename, scenario, payee_acct, payee_name)
            results.append(r)
        except Exception as exc:
            import traceback
            results.append({
                "file": filename, "cheque_num": "?", "scenario": scenario,
                "image": "?", "payee_acct": payee_acct or "(none)",
                "payee_name": payee_name or "(none)", "vault_info": "",
                "outcome": f"ERROR: {exc}", "violations": [], "mismatch_id": "",
            })
            traceback.print_exc()

    outcome_label = {
        "ACCEPTED":      "[ACCEPT]  ",
        "CTS_REJECTED":  "[REJECT]  ",
        "MISMATCH_HELD": "[MISMATCH]",
    }

    for i, r in enumerate(results, 1):
        label = outcome_label.get(r["outcome"], "[?]       ")
        print(f"  [{i}] Cheque #{r['cheque_num']}   Scenario: {r['scenario']}")
        print(f"      Image      : {r['image']}")
        print(f"      Payee Acct : {r['payee_acct']}   Name on slip: {r['payee_name']}")
        if r["vault_info"]:
            print(f"      Vault      : {r['vault_info']}")
        print(f"      Outcome    : {label} {r['outcome']}")
        if r["violations"]:
            print(f"      Violations : {', '.join(r['violations'])}")
        if r["mismatch_id"]:
            print(f"      Mismatch ID: {r['mismatch_id']}")
        print()

    accepted  = sum(1 for r in results if r["outcome"] == "ACCEPTED")
    rejected  = sum(1 for r in results if r["outcome"] == "CTS_REJECTED")
    mismatch  = sum(1 for r in results if r["outcome"] == "MISMATCH_HELD")
    errors    = sum(1 for r in results if "ERROR" in r["outcome"])

    print("=" * 108)
    print(f"  Total: {len(results)}   ACCEPTED: {accepted}   CTS_REJECTED: {rejected}   MISMATCH_HELD: {mismatch}   ERRORS: {errors}")
    print("=" * 108)
    print()


if __name__ == "__main__":
    asyncio.run(main())
