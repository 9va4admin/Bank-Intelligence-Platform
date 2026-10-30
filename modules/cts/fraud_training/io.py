"""Loader for the bank's labelled fraud dataset (see docs/fraud/labelled-data-contract.md).

An empty cell is MISSING (None), never zero. Columns outside the contract are refused, in particular any that
look like raw account numbers or customer names: the training set must carry no identifiable customer data.
"""
from __future__ import annotations

import csv

from modules.cts.fraud_training.features import FEATURES
from shared.messages import get_message

REQUIRED = ["timestamp", "is_fraud"] + [f.name for f in FEATURES]
_FORBIDDEN_HINTS = ("account_number", "account_no", "acct", "name", "payee_name", "drawer", "mobile", "pan", "aadhaar")


class ContractViolation(Exception):
    pass


def load_labelled_csv(path: str):
    """-> (X: dict[feature -> list[float | None]], y: list[int], timestamps: list[float])"""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames or []
        missing = [c for c in REQUIRED if c not in cols]
        if missing:
            raise ContractViolation(get_message("CTS_MISSING_REQUIRED_COLUMNS", missing=missing))
        extra = [c for c in cols if c not in REQUIRED]
        bad = [c for c in extra if any(h in c.lower() for h in _FORBIDDEN_HINTS)]
        if bad:
            raise ContractViolation(get_message("CTS_COLUMNS_THAT_MAY_CARRY_CUSTOMER", bad=bad))
        X: dict[str, list] = {f.name: [] for f in FEATURES}
        y: list[int] = []
        ts: list[float] = []
        for n, row in enumerate(reader, start=2):
            label = row["is_fraud"].strip()
            if label not in ("0", "1"):
                raise ContractViolation(f"line {n}: is_fraud must be 0 or 1, got {label!r}")
            y.append(int(label))
            try:
                ts.append(float(row["timestamp"]))
            except ValueError:
                raise ContractViolation(get_message("CTS_LINE_TIMESTAMP_MUST_BE_A", n=n))
            for f in FEATURES:
                cell = (row.get(f.name) or "").strip()
                X[f.name].append(None if cell == "" else float(cell))
    return X, y, ts
