"""
Reader for NPCI's CIIF (cheque issue information) file, the input of the Positive Payment System.

Source: NPCI PPS Interface File Specification v1.19 (2 Nov 2023), Appx 1.1.2-1.1.4. CSV and XML forms.
Field rules are the specification's attribute table; every rule is enforced and reported per record
(line number + field + a message that never echoes the value, since values are account numbers and names).

Not implemented here (and not claimed): the file-name convention, file-level reject reasons (Appx 1.1.5) and
the acknowledgement / response files. This module only turns a CIIF file into validated records.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

_AN_CHARS = re.compile(r"^[A-Za-z0-9_ '\,\.]+$")        # a-z A-Z 0-9 _ blank apostrophe comma full stop
_MAX_AGE_DAYS = 90

CSV_COLUMNS = ["PayeeAccountNumber", "SerialNumber", "IssueDate", "Amount", "Transactioncode", "DraweeBankName",
               "DraweeBranchRoutingNumber", "PayeeName", "San", "Optional1", "Optional2", "Optional3"]
_XML_ATTRS = {  # CSV column -> XML attribute
    "PayeeAccountNumber": "payeeaccno", "SerialNumber": "serialno", "IssueDate": "issue-date", "Amount": "amount",
    "Transactioncode": "transcode", "DraweeBankName": "draweebankname", "DraweeBranchRoutingNumber": "draweebranchroutingno",
    "PayeeName": "payeename", "San": "san", "Optional1": "optional1", "Optional2": "optional2", "Optional3": "optional3",
}


@dataclass(frozen=True)
class CIIFRecord:
    drawer_account: str            # the spec calls it "payeeaccno" but defines it as the DRAWER's account number
    serial_no: Optional[str]
    issue_date: date
    amount: int
    transaction_code: str
    drawee_bank_name: Optional[str]
    drawee_routing_no: str
    payee_name: str
    san: str
    optional1: Optional[str] = None
    optional2: Optional[str] = None
    optional3: Optional[str] = None


@dataclass(frozen=True)
class CIIFError:
    line: int
    field: str
    message: str


def _an(value: str, lo: int, hi: int) -> Optional[str]:
    if not (lo <= len(value) <= hi):
        return f"length must be {lo}-{hi} characters"
    if not _AN_CHARS.match(value):
        return "contains a character the specification does not allow"
    if value != value.strip():
        return "must not start or end with a space"
    return None


def _validate(row: dict, line: int, today: date, names: dict) -> tuple[Optional[CIIFRecord], list[CIIFError]]:
    """row maps CSV column names to stripped-or-raw string values; names maps column -> label used in errors."""
    errs: list[CIIFError] = []

    def bad(col: str, msg: str) -> None:
        errs.append(CIIFError(line, names[col], msg))

    g = lambda col: row.get(col) or ""

    acct = g("PayeeAccountNumber")
    if not acct:
        bad("PayeeAccountNumber", "mandatory")
    elif (m := _an(acct, 1, 25)):
        bad("PayeeAccountNumber", m)

    serial = g("SerialNumber") or None
    if serial is not None and not (len(serial) == 6 and serial.isdigit() and int(serial) > 0):
        bad("SerialNumber", "must be 6 digits, zero padded, greater than 0")

    issue = None
    d = g("IssueDate")
    if not d:
        bad("IssueDate", "mandatory")
    else:
        try:
            if not (len(d) == 8 and d.isdigit()):
                raise ValueError
            issue = datetime.strptime(d, "%d%m%Y").date()
        except ValueError:
            bad("IssueDate", "must be a real date in DDMMYYYY format")
        else:
            if issue < today - timedelta(days=_MAX_AGE_DAYS):
                bad("IssueDate", f"older than {_MAX_AGE_DAYS} days")
                issue = None

    amount = None
    a = g("Amount")
    if not a:
        bad("Amount", "mandatory")
    elif not (a.isdigit() and 1 <= len(a) <= 18):
        bad("Amount", "must be 1-18 digits, numeric only")
    else:
        amount = int(a)

    tc = g("Transactioncode")
    if not (tc.isdigit() and 2 <= len(tc) <= 3):
        bad("Transactioncode", "mandatory, 2-3 digits")

    bank = g("DraweeBankName") or None
    if bank is not None and (m := _an(bank, 1, 50)):
        bad("DraweeBankName", m)

    rt = g("DraweeBranchRoutingNumber")
    if not (len(rt) == 9 and rt.isdigit() and int(rt) > 0):
        bad("DraweeBranchRoutingNumber", "mandatory, 9 digits, greater than 0")

    pn = g("PayeeName")
    if not pn:
        bad("PayeeName", "mandatory")
    elif (m := _an(pn, 1, 50)):
        bad("PayeeName", m)

    san = g("San")
    if not san:
        bad("San", "mandatory (use 000000 when the customer has none)")
    elif not (san.isdigit() and 6 <= len(san) <= 7):
        bad("San", "must be 6-7 digits")

    opts = []
    for col in ("Optional1", "Optional2", "Optional3"):
        v = g(col) or None
        if v is not None and (m := _an(v, 1, 50)):
            bad(col, m)
        opts.append(v)

    if errs:
        return None, errs
    return CIIFRecord(acct, serial, issue, amount, tc, bank, rt, pn, san, *opts), []


def parse_ciif_csv(text: str, today: date) -> tuple[list[CIIFRecord], list[CIIFError]]:
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return [], [CIIFError(1, "header", "empty file")]
    if [h.strip().lower() for h in header] != [c.lower() for c in CSV_COLUMNS]:
        return [], [CIIFError(1, "header", "header does not match the specification's column order")]
    names = {c: c for c in CSV_COLUMNS}
    recs, errs = [], []
    for n, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        cells = (cells + [""] * len(CSV_COLUMNS))[: len(CSV_COLUMNS)]
        rec, e = _validate(dict(zip(CSV_COLUMNS, cells)), n, today, names)
        (recs.append(rec) if rec else errs.extend(e))
    return recs, errs


def parse_ciif_xml(text: str, today: date) -> tuple[list[CIIFRecord], list[CIIFError], dict]:
    """XML form. DOCTYPE/entity declarations are refused outright (no external entity or expansion attacks)."""
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
        return [], [CIIFError(0, "file", "DOCTYPE and entity declarations are not allowed")], {}
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return [], [CIIFError(0, "file", "not well-formed XML")], {}
    if root.tag != "ciif-root":
        return [], [CIIFError(0, "file", "root element must be ciif-root")], {}
    meta = {"version": root.get("Version"), "file_id": root.get("Fileid"),
            "test_file": (root.get("Testfileindicator") or "").upper() == "T",
            "drawee_routing_no": root.get("draweebranchroutingno")}
    names = dict(_XML_ATTRS)
    recs, errs = [], []
    for n, item in enumerate(root.iter("item"), start=1):
        row = {col: (item.get(attr) or "") for col, attr in _XML_ATTRS.items()}
        rec, e = _validate(row, n, today, names)
        (recs.append(rec) if rec else errs.extend(e))
    return recs, errs, meta
