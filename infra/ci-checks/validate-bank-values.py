#!/usr/bin/env python3
"""
validate-bank-values.py — CI check for bank Helm values completeness.

Validates that every bank's values files under infra/helm/values/banks/{bank_id}/
contain the required fields before ArgoCD can sync them to a cluster.

Usage:
    python infra/ci-checks/validate-bank-values.py
    python infra/ci-checks/validate-bank-values.py --bank saraswat-coop

Exits 1 if any bank has missing required fields. Run in CI as part of the
lint stage (before helm lint, before build).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed — pip install pyyaml")
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parents[2]
BANKS_DIR = REPO_ROOT / "infra" / "helm" / "values" / "banks"

# ── Required fields (dot-notation → nested dict path) ────────────────────────
# If a bank has the file, these fields must be present and non-empty.

PLATFORM_REQUIRED = [
    "bank_id",
    "global.bank_id",
    "global.registry",
    "modules.cts.enabled",
    "modules.ej.enabled",
    "minio.endpoint",
    "hsm.transit_key_name",
    "astra.platform_chart_version",
]

CTS_REQUIRED = [
    "bank_id",
    "global.bank_id",
    "global.registry",
    "kafka.bootstrap_servers",
    "astra.cts_chart_version",
]

EJ_REQUIRED = [
    "bank_id",
    "global.bank_id",
    "global.registry",
    "astra.ej_chart_version",
]

# Fields that must be consistent across platform.yaml and cts.yaml (if both exist)
CROSS_FILE_CONSISTENT = [
    "bank_id",
    "global.bank_id",
    "global.registry",
]


def get_nested(data: dict, dot_key: str):
    """Return value at dot_key path, or _MISSING sentinel."""
    keys = dot_key.split(".")
    cur = data
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return _MISSING
        cur = cur[k]
    return cur


_MISSING = object()


def check_required_fields(
    values: dict, required: list[str], label: str
) -> list[str]:
    errors = []
    for field in required:
        val = get_nested(values, field)
        if val is _MISSING:
            errors.append(f"  MISSING: {field}")
        elif val == "" or val is None:
            errors.append(f"  EMPTY:   {field} (must be non-empty)")
    return errors


def check_cross_file_consistency(
    platform: dict, cts: dict, bank_id: str
) -> list[str]:
    errors = []
    for field in CROSS_FILE_CONSISTENT:
        pv = get_nested(platform, field)
        cv = get_nested(cts, field)
        if pv is _MISSING or cv is _MISSING:
            continue  # field-level checks already caught these
        if pv != cv:
            errors.append(
                f"  MISMATCH: {field} — platform.yaml={pv!r} vs cts.yaml={cv!r}"
            )
    return errors


def validate_bank(bank_dir: Path) -> list[str]:
    bank_id = bank_dir.name
    errors: list[str] = []

    platform_file = bank_dir / "platform.yaml"
    cts_file = bank_dir / "cts.yaml"
    ej_file = bank_dir / "ej.yaml"

    # platform.yaml is MANDATORY for every bank
    if not platform_file.exists():
        return [f"[{bank_id}] MISSING FILE: platform.yaml (required for every bank)"]

    platform = yaml.safe_load(platform_file.read_text(encoding="utf-8")) or {}
    pf_errors = check_required_fields(platform, PLATFORM_REQUIRED, "platform.yaml")
    for e in pf_errors:
        errors.append(f"[{bank_id}/platform.yaml] {e.strip()}")

    # Cross-file consistency if cts.yaml exists
    if cts_file.exists():
        cts = yaml.safe_load(cts_file.read_text(encoding="utf-8")) or {}
        cf_errors = check_required_fields(cts, CTS_REQUIRED, "cts.yaml")
        for e in cf_errors:
            errors.append(f"[{bank_id}/cts.yaml] {e.strip()}")

        consistency_errors = check_cross_file_consistency(platform, cts, bank_id)
        for e in consistency_errors:
            errors.append(f"[{bank_id}] {e.strip()}")

    # EJ file validation
    if ej_file.exists():
        ej = yaml.safe_load(ej_file.read_text(encoding="utf-8")) or {}
        ej_errors = check_required_fields(ej, EJ_REQUIRED, "ej.yaml")
        for e in ej_errors:
            errors.append(f"[{bank_id}/ej.yaml] {e.strip()}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate bank Helm values completeness")
    parser.add_argument("--bank", help="Only validate this specific bank (default: all)")
    args = parser.parse_args()

    if not BANKS_DIR.exists():
        print(f"ERROR: {BANKS_DIR} does not exist", file=sys.stderr)
        return 1

    bank_dirs = (
        [BANKS_DIR / args.bank]
        if args.bank
        else [d for d in BANKS_DIR.iterdir() if d.is_dir()]
    )

    all_errors: list[str] = []
    for bank_dir in sorted(bank_dirs):
        if not bank_dir.is_dir():
            print(f"WARNING: {bank_dir} does not exist — skipping", file=sys.stderr)
            continue
        errs = validate_bank(bank_dir)
        all_errors.extend(errs)

    if all_errors:
        print("Bank values validation FAILED:\n")
        for e in all_errors:
            print(f"  {e}")
        print(f"\n{len(all_errors)} error(s) found. Fix before ArgoCD sync.")
        return 1

    banks_checked = len(bank_dirs)
    print(f"Bank values validation PASSED — {banks_checked} bank(s) OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
