"""
CSV generation for demo pipeline results.

write_success_csv — items with status SUCCESS (presentment or drawee phase)
write_failure_csv — items with status FAILED (both phases)
"""
import csv
import io
from typing import List

from modules.cts.demo.models import DemoItem, ItemStatus, StepStatus


def write_success_csv(items: List[DemoItem], phase: str = "presentment") -> str:
    """Returns a CSV string containing only accepted/confirmed items."""
    output = io.StringIO()

    if phase == "presentment":
        fieldnames = ["#", "Filename", "MICR_Line", "Payee", "Amount", "Date", "Lot", "Status", "Total_ms"]
    else:
        fieldnames = ["#", "Filename", "Payee", "Amount", "Date", "Sig_Score", "Fraud_Score", "Decision", "Total_ms"]

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    row_num = 0
    for item in items:
        if item.status != ItemStatus.SUCCESS:
            continue
        row_num += 1
        ext = item.extracted or {}

        if phase == "presentment":
            micr_step = next((s for s in item.steps if s.step == "ocr_micr"), None)
            micr      = (micr_step.data or {}).get("micr_line", "-") if micr_step else "-"
            lot_step  = next((s for s in item.steps if s.step == "lot_assignment"), None)
            lot_id    = (lot_step.data or {}).get("lot_id", "-") if lot_step else "-"
            writer.writerow({
                "#":         row_num,
                "Filename":  item.filename,
                "MICR_Line": micr,
                "Payee":     ext.get("payee", "-"),
                "Amount":    ext.get("amount_figures", "-"),
                "Date":      ext.get("date", "-"),
                "Lot":       lot_id,
                "Status":    "ACCEPTED",
                "Total_ms":  item.total_ms,
            })
        else:
            sig_step    = next((s for s in item.steps if s.step == "signature_vault"), None)
            fraud_step  = next((s for s in item.steps if s.step == "fraud_score"), None)
            sig_score   = (sig_step.data or {}).get("match_score", "-")   if sig_step   else "-"
            fraud_score = (fraud_step.data or {}).get("fraud_score", "-") if fraud_step else "-"
            writer.writerow({
                "#":           row_num,
                "Filename":    item.filename,
                "Payee":       ext.get("payee", "-"),
                "Amount":      ext.get("amount_figures", "-"),
                "Date":        ext.get("date", "-"),
                "Sig_Score":   sig_score,
                "Fraud_Score": fraud_score,
                "Decision":    item.decision or "CONFIRMED",
                "Total_ms":    item.total_ms,
            })

    return output.getvalue()


def write_failure_csv(items: List[DemoItem]) -> str:
    """Returns a CSV string containing only failed/returned items."""
    output = io.StringIO()
    fieldnames = ["#", "Filename", "Reject_Reason", "Detail", "Failed_At_Step", "Total_ms"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    row_num = 0
    for item in items:
        if item.status != ItemStatus.FAILED:
            continue
        row_num += 1
        failed_step = next(
            (s for s in item.steps if s.status == StepStatus.FAILED),
            None,
        )
        writer.writerow({
            "#":              row_num,
            "Filename":       item.filename,
            "Reject_Reason":  item.reject_reason or "-",
            "Detail":         (failed_step.detail if failed_step else None) or "-",
            "Failed_At_Step": (failed_step.step   if failed_step else None) or "-",
            "Total_ms":       item.total_ms,
        })

    return output.getvalue()
