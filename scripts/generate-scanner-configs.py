#!/usr/bin/env python3
"""
ASTRA CTS — Generate Scanner Agent Config Files from Branch Master

Queries cts.branches JOIN cts.scanner_configs for a given SB or SMB bank ID
and produces one .env file per scanning-enabled branch.

The .env file is placed in the scanner agent's install directory on the teller PC
(or pre-generated for the bank IT team to deploy alongside the installer).

Usage:
  # Generate configs for a Sponsor Bank (SB) — all branches:
  python scripts/generate-scanner-configs.py --bank-id saraswat-coop

  # Generate configs for a Sub-Member Bank (SMB) — that SMB's branches only:
  python scripts/generate-scanner-configs.py --bank-id smb-ucb-001 --smb

  # Custom DB URL:
  python scripts/generate-scanner-configs.py --bank-id saraswat-coop \\
      --db-url "postgresql://astra_ro:pw@localhost:15433/astra"

  # Output to a specific directory:
  python scripts/generate-scanner-configs.py --bank-id saraswat-coop \\
      --out-dir /tmp/scanner-configs/saraswat

  # Dry run (print configs, don't write files):
  python scripts/generate-scanner-configs.py --bank-id saraswat-coop --dry-run

Output:
  scanner-configs/<bank_id>/<branch_ifsc>.env    — one file per enabled branch

Each .env file contains all environment variables for the ASTRA CTS Scanner Agent:
  ASTRA_API_URL, BANK_ID, BANK_IFSC, OPERATOR_ID, SESSION_PREFIX,
  SCANNER_PORT, ENABLE_UV_SCAN, ENABLE_IMPRINTER, ENDORSEMENT_TEXT, LISTEN_ADDR
  (ASTRA_API_TOKEN is NOT in this file — stored in Windows Credential Manager)

These files are copied to the teller PC by the bank IT team and loaded by the
installer (install.ps1 reads them as environment variable overrides).
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Any, Optional

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)


# ── Database query ────────────────────────────────────────────────────────────

QUERY = """
SELECT
    b.branch_id,
    b.bank_id,
    b.smb_id,
    b.branch_name,
    b.branch_ifsc,
    b.city,
    b.state,
    b.pu_id,
    b.address,
    b.phone_number,
    -- Scanner config (may be NULL if no config row yet)
    sc.scanner_oem,
    sc.scanner_model,
    sc.scanner_config_id,
    sc.drop_folder_path,
    sc.image_naming_pattern,
    sc.output_format,
    sc.field_mapping,
    sc.image_side_mapping
FROM cts.branches b
LEFT JOIN cts.scanner_configs sc
    ON sc.branch_id = b.branch_id
    AND sc.is_active = TRUE
WHERE
    b.bank_id = %(bank_id)s
    AND b.is_scanning_enabled = TRUE
    AND b.is_active = TRUE
ORDER BY b.branch_ifsc
"""

QUERY_SMB = """
SELECT
    b.branch_id,
    b.bank_id,
    b.smb_id,
    b.branch_name,
    b.branch_ifsc,
    b.city,
    b.state,
    b.pu_id,
    b.address,
    b.phone_number,
    sc.scanner_oem,
    sc.scanner_model,
    sc.scanner_config_id,
    sc.drop_folder_path,
    sc.image_naming_pattern,
    sc.output_format,
    sc.field_mapping,
    sc.image_side_mapping
FROM cts.branches b
LEFT JOIN cts.scanner_configs sc
    ON sc.branch_id = b.branch_id
    AND sc.is_active = TRUE
WHERE
    b.smb_id = %(bank_id)s
    AND b.is_scanning_enabled = TRUE
    AND b.is_active = TRUE
ORDER BY b.branch_ifsc
"""


# ── Scanner OEM → default port mapping ────────────────────────────────────────

OEM_DEFAULT_PORT = {
    "CANON":         "USB",      # Canon CR-120 — USB via Ranger SDK
    "PANINI":        "USB",      # Panini Vision X
    "DIGITAL_CHECK": "COM3",     # Digital Check TellerScan — serial COM3 typical
    "MAGTEK":        "USB",      # MagTek Excella
    "RDM":           "USB",      # RDM EC9600
    "OPEX":          "TCP:9100", # Opex Falcon — network scanner
    "GENERIC":       "USB",
}


# ── Env file template ─────────────────────────────────────────────────────────

def build_env_content(row: dict, astra_api_url: str, endorsement_prefix: str) -> str:
    branch_ifsc   = row["branch_ifsc"]
    bank_id       = row["bank_id"]
    branch_name   = row["branch_name"] or branch_ifsc
    scanner_oem   = (row["scanner_oem"] or "CANON").upper()
    scanner_port  = OEM_DEFAULT_PORT.get(scanner_oem, "USB")
    drop_folder   = row["drop_folder_path"] or f"C:\\ASTRA\\drop\\{branch_ifsc}"

    # Session prefix: first 3 chars of city + branch suffix (e.g. MUM, BNG, CHN)
    city          = (row["city"] or "CTS").upper()[:3]
    session_prefix = f"{city}"

    endorsement   = f"{endorsement_prefix}/{branch_ifsc}"

    # UV scan only for CANON CR-120 UV units (flagged by scanner_model)
    scanner_model  = (row["scanner_model"] or "").upper()
    enable_uv     = "1" if "UV" in scanner_model else "0"

    generated_at  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return dedent(f"""\
        # ASTRA CTS Scanner Agent Configuration
        # Branch  : {branch_name}
        # IFSC    : {branch_ifsc}
        # OEM     : {scanner_oem} ({row['scanner_model'] or 'unknown model'})
        # City    : {row['city'] or 'unknown'}
        # Generated: {generated_at} by generate-scanner-configs.py
        #
        # NOTE: Copy this file to the teller PC alongside cts-scanner-bridge.exe
        # The installer (install.ps1) reads these values when registering the service.
        # ASTRA_API_TOKEN is NOT here — run install.ps1 interactively to supply it.
        # ──────────────────────────────────────────────────────────────────────────

        # Required — filled by generator
        ASTRA_API_URL={astra_api_url}
        BANK_ID={bank_id}
        BANK_IFSC={branch_ifsc}

        # Scanner hardware
        SCANNER_PORT={scanner_port}
        ENABLE_UV_SCAN={enable_uv}
        ENABLE_IMPRINTER=1

        # Clearing session
        SESSION_PREFIX={session_prefix}
        OPERATOR_ID=scanner-agent
        ENDORSEMENT_TEXT={endorsement}

        # Drop folder (for file-drop mode scanners only; not used by Canon Ranger SDK path)
        DROP_FOLDER_PATH={drop_folder}

        # HTTP control server (teller UI connects to this)
        LISTEN_ADDR=:9201

        # ── Set ASTRA_API_TOKEN separately via install.ps1 ──────────────────────
        # ASTRA_API_TOKEN=<from ASTRA Admin UI > Admin > Scanner Tokens>
    """)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Generate ASTRA scanner agent .env configs from Branch Master DB"
    )
    ap.add_argument("--bank-id",    required=True, help="Bank ID (SB or SMB)")
    ap.add_argument("--smb",        action="store_true",
                    help="Query by smb_id instead of bank_id (use for SMB banks)")
    ap.add_argument("--db-url",     default="",
                    help="PostgreSQL DSN. Default: reads ASTRA_DB_URL env var or "
                         "postgresql://astra_ro:astra_ro@localhost:15433/astra")
    ap.add_argument("--astra-api-url", default="",
                    help="ASTRA API URL to embed in .env files. "
                         "Default: reads ASTRA_API_URL env var")
    ap.add_argument("--endorsement-prefix", default="ASTRA/CTS",
                    help="Endorsement text prefix. Branch IFSC is appended. "
                         "Default: ASTRA/CTS")
    ap.add_argument("--out-dir",    default="",
                    help="Output directory. Default: scanner-configs/<bank_id>/")
    ap.add_argument("--dry-run",    action="store_true",
                    help="Print configs to stdout, do not write files")
    args = ap.parse_args()

    db_url = args.db_url or os.environ.get("ASTRA_DB_URL",
        "postgresql://astra_ro:astra_ro@localhost:15433/astra")
    astra_api_url = args.astra_api_url or os.environ.get("ASTRA_API_URL", "")
    if not astra_api_url:
        print("[WARN] ASTRA_API_URL not set. Pass --astra-api-url or set env var.")
        print("       .env files will have ASTRA_API_URL=<FILL_IN>")
        astra_api_url = "<FILL_IN>"

    out_dir = Path(args.out_dir) if args.out_dir else Path("scanner-configs") / args.bank_id

    print()
    print(f"  ASTRA Scanner Config Generator")
    print(f"  Bank ID  : {args.bank_id}  ({'SMB query' if args.smb else 'SB query'})")
    print(f"  DB       : {db_url.split('@')[-1] if '@' in db_url else db_url}")
    print(f"  Out dir  : {out_dir if not args.dry_run else '(dry run — no files written)'}")
    print()

    # ── Connect to DB ─────────────────────────────────────────────────────────
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        print(f"  [FAIL] DB connection failed: {e}")
        print(f"         Check DB URL: {db_url.split('@')[-1] if '@' in db_url else db_url}")
        sys.exit(1)

    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    query = QUERY_SMB if args.smb else QUERY
    cursor.execute(query, {"bank_id": args.bank_id})
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        query_type = "smb_id" if args.smb else "bank_id"
        print(f"  [WARN] No scanning-enabled branches found for {query_type}={args.bank_id}")
        print(f"         Check: is_scanning_enabled=TRUE and is_active=TRUE in cts.branches")
        sys.exit(0)

    print(f"  Found {len(rows)} scanning-enabled branch(es)")
    print()

    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    generated = 0
    warnings = []

    for row in rows:
        ifsc = row["branch_ifsc"]
        oem  = row["scanner_oem"] or "CANON"
        env_content = build_env_content(
            dict(row), astra_api_url, args.endorsement_prefix
        )

        if row["scanner_config_id"] is None:
            warnings.append(f"  [WARN] {ifsc} — no scanner_config row (using defaults for {oem})")

        if args.dry_run:
            print(f"  ── {ifsc}.env ──")
            print(env_content)
        else:
            out_file = out_dir / f"{ifsc}.env"
            out_file.write_text(env_content, encoding="utf-8")
            size = out_file.stat().st_size
            config_note = f"OEM: {oem}" if row["scanner_config_id"] else "OEM: default (no config row)"
            print(f"  [OK] {ifsc}.env  — {size} bytes  — {config_note}")

        generated += 1

    if warnings:
        print()
        for w in warnings:
            print(w)
        print()
        print("  Branches with warnings used OEM defaults.")
        print("  Add scanner_configs rows in the ASTRA Admin UI for full config.")

    print()
    if not args.dry_run:
        print(f"  Generated {generated} config file(s) in: {out_dir}")
        print()
        print("  Next steps for bank IT:")
        print("  1. Copy each {IFSC}.env to the teller PC alongside cts-scanner-bridge.exe")
        print("  2. Run: install.ps1 (reads ASTRA_API_URL, BANK_IFSC, etc. from the .env file)")
        print("  3. Supply ASTRA_API_TOKEN interactively (from Admin UI > Scanner Tokens)")
        print()
        print("  Or for silent MSI install:")
        print("    msiexec /i AstraScanner-Setup.msi /quiet \\")
        for row in rows[:1]:  # show example for first branch
            print(f"      ASTRA_API_URL={astra_api_url} \\")
            print(f"      BANK_ID={row['bank_id']} \\")
            print(f"      BANK_IFSC={row['branch_ifsc']}")
    else:
        print(f"  Dry run complete — {generated} config(s) would be written to {out_dir}")
    print()


if __name__ == "__main__":
    main()
