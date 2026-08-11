"""
Temporal activity: generate_session_report

Called at the end of every outward clearing session (after NGCH submission).
Produces:
  1. SessionReportData assembled from cts.outward_scan_events + cts.clearing_sessions
  2. HTML rendered by html_template.render_html()
  3. PDF rendered by pdf_renderer.render_pdf()
  4. Both uploaded to MinIO (WORM COMPLIANCE bucket)
  5. Metadata row written to cts.session_reports
  6. Immudb audit event written (SESSION_REPORT_GENERATED)

Returns GenerateReportResult with minio paths and report_id for downstream use.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()

_REPORT_BUCKET = "astra-cts-reports"


class GenerateReportInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id:  str
    bank_id:     str
    branch_id:   str
    branch_ifsc: str
    branch_name: str


class GenerateReportResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    report_id:       str
    html_minio_path: str
    pdf_minio_path:  str
    instrument_count: int
    status:          str   # READY | FAILED


@activity.defn
async def generate_session_report(inp: GenerateReportInput) -> GenerateReportResult:
    """
    Assemble, render, store, and audit a CTS outward session clearing report.
    Fails gracefully: on any error, writes a FAILED row to session_reports and
    returns status=FAILED so the workflow can continue without blocking NGCH flow.
    """
    from shared.config.config_service import config_service
    from shared.audit.audit_event import AuditEvent, AuditEventType

    report_id = str(uuid.uuid4())

    with activity.start_heartbeat_timeout():
        pass  # heartbeat not needed for this short activity

    log.info(
        "generate_session_report.start",
        session_id=inp.session_id,
        bank_id=inp.bank_id,
        branch_ifsc=inp.branch_ifsc,
    )

    try:
        db_url   = await config_service.get_secret(f"db.cts.dsn")
        minio_ep = await config_service.get("minio.endpoint")
        minio_ak = await config_service.get_secret("minio.access_key")
        minio_sk = await config_service.get_secret("minio.secret_key")

        report = await _assemble_report(inp, report_id, db_url)

        from modules.cts.reports.html_template import render_html
        from modules.cts.reports.pdf_renderer  import render_pdf
        from modules.cts.reports.session_report_builder import minio_path

        html_bytes = render_html(report).encode("utf-8")
        pdf_bytes  = render_pdf(render_html(report))

        html_path = minio_path(report, "html")
        pdf_path  = minio_path(report, "pdf")

        await _upload_minio(minio_ep, minio_ak, minio_sk, html_path, html_bytes, "text/html")
        await _upload_minio(minio_ep, minio_ak, minio_sk, pdf_path,  pdf_bytes,  "application/pdf")

        await _write_db_row(db_url, report, html_path, pdf_path, "READY")

        await _write_audit(
            bank_id=inp.bank_id,
            session_id=inp.session_id,
            report_id=report_id,
            html_path=html_path,
            pdf_path=pdf_path,
            instrument_count=report.instrument_count,
        )

        log.info(
            "generate_session_report.done",
            session_id=inp.session_id,
            report_id=report_id,
            instrument_count=report.instrument_count,
        )
        return GenerateReportResult(
            report_id=report_id,
            html_minio_path=html_path,
            pdf_minio_path=pdf_path,
            instrument_count=report.instrument_count,
            status="READY",
        )

    except Exception as exc:
        log.error(
            "generate_session_report.failed",
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        try:
            await _write_failed_row(db_url, inp, report_id, str(exc))
        except Exception:
            pass
        return GenerateReportResult(
            report_id=report_id,
            html_minio_path="",
            pdf_minio_path="",
            instrument_count=0,
            status="FAILED",
        )


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _assemble_report(
    inp: GenerateReportInput,
    report_id: str,
    db_url: str,
) -> "SessionReportData":
    from modules.cts.reports.session_report_builder import SessionReportData, InstrumentRow

    import asyncpg

    conn = await asyncpg.connect(db_url)
    try:
        session_row = await conn.fetchrow(
            """
            SELECT clearing_date, session_type, total_instruments, npci_ack_ref
            FROM cts.clearing_sessions
            WHERE session_id = $1 AND bank_id = $2
            """,
            inp.session_id, inp.bank_id,
        )

        events = await conn.fetch(
            """
            SELECT instrument_id, scan_id, micr_suffix, payee_display,
                   amount_range, outcome, lot_id, mismatch_fields,
                   reject_reason, scanned_at
            FROM cts.outward_scan_events
            WHERE session_id = $1 AND bank_id = $2
            ORDER BY scanned_at ASC
            """,
            inp.session_id, inp.bank_id,
        )

        clearing_date = session_row["clearing_date"]
        session_type  = session_row["session_type"] or "MORNING"
        npci_ack_ref  = session_row.get("npci_ack_ref")

        instruments = []
        accepted = rejected = held = comp_pass = comp_fail = 0
        lot_ids: set[str] = set()

        for ev in events:
            outcome = ev["outcome"] or "UNKNOWN"
            # Derive compliance result and violations from reject_reason / mismatch_fields
            if outcome == "CTS_REJECTED" and ev["reject_reason"]:
                reject = ev["reject_reason"]
                # reject_reason carries violation codes when CTS-2010 was the cause
                violations = [v.strip() for v in reject.split(",") if v.strip()]
                comp_result = "FAIL"
                comp_fail += 1
            else:
                violations = []
                comp_result = "PASS"
                comp_pass += 1

            # Payee status derived from mismatch_fields or outcome
            mf = ev["mismatch_fields"] or []
            if "ACCOUNT_INACTIVE" in mf:
                payee_status = "ACCOUNT_INACTIVE"
            elif "NAME_MISMATCH" in mf:
                payee_status = "NAME_MISMATCH"
            elif "PAYEE_NOT_FOUND" in mf:
                payee_status = "NOT_FOUND"
            else:
                payee_status = "PROCEED"

            if outcome == "ACCEPTED":
                accepted += 1
            elif outcome == "CTS_REJECTED":
                rejected += 1
            else:
                held += 1

            if ev["lot_id"]:
                lot_ids.add(ev["lot_id"])

            # payee_display already masked at write time (first initial + ***)
            payee_display = ev["payee_display"] or "—"
            amount_range  = ev["amount_range"] or "—"

            instruments.append(InstrumentRow(
                instrument_id=ev["instrument_id"] or ev["scan_id"],
                cheque_number=(ev["micr_suffix"] or "")[-6:] or "—",
                lot_number=ev["lot_id"] or "—",
                payee_display=payee_display,
                amount_range=amount_range,
                payee_status=payee_status,
                compliance_result=comp_result,
                compliance_violations=violations,
                outcome=outcome,
                scanned_at=ev["scanned_at"],
            ))

        return SessionReportData(
            report_id=report_id,
            session_id=inp.session_id,
            bank_id=inp.bank_id,
            branch_id=inp.branch_id,
            branch_ifsc=inp.branch_ifsc,
            branch_name=inp.branch_name,
            clearing_date=clearing_date,
            session_type=session_type,
            generated_at=datetime.now(timezone.utc),
            instrument_count=len(instruments),
            lot_count=len(lot_ids),
            accepted_count=accepted,
            rejected_count=rejected,
            held_count=held,
            compliance_pass_count=comp_pass,
            compliance_fail_count=comp_fail,
            instruments=instruments,
            npci_ack_ref=npci_ack_ref,
        )
    finally:
        await conn.close()


async def _upload_minio(
    endpoint: str,
    access_key: str,
    secret_key: str,
    object_path: str,
    data: bytes,
    content_type: str,
) -> None:
    from minio import Minio  # type: ignore
    import io

    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=False)
    if not client.bucket_exists(_REPORT_BUCKET):
        client.make_bucket(_REPORT_BUCKET)
    client.put_object(
        _REPORT_BUCKET,
        object_path,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


async def _write_db_row(
    db_url: str,
    report: "SessionReportData",
    html_path: str,
    pdf_path: str,
    status: str,
) -> None:
    import asyncpg
    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute(
            """
            INSERT INTO cts.session_reports (
                report_id, session_id, bank_id, branch_id, branch_ifsc,
                clearing_date, session_type, generated_at,
                html_minio_path, pdf_minio_path,
                instrument_count, lot_count,
                accepted_count, rejected_count, held_count,
                compliance_pass_count, compliance_fail_count,
                status
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                $11,$12,$13,$14,$15,$16,$17,$18
            )
            ON CONFLICT (session_id, bank_id) DO UPDATE SET
                html_minio_path = EXCLUDED.html_minio_path,
                pdf_minio_path  = EXCLUDED.pdf_minio_path,
                status          = EXCLUDED.status,
                generated_at    = EXCLUDED.generated_at
            """,
            report.report_id, report.session_id, report.bank_id,
            report.branch_id, report.branch_ifsc,
            report.clearing_date, report.session_type, report.generated_at,
            html_path, pdf_path,
            report.instrument_count, report.lot_count,
            report.accepted_count, report.rejected_count, report.held_count,
            report.compliance_pass_count, report.compliance_fail_count,
            status,
        )
    finally:
        await conn.close()


async def _write_failed_row(
    db_url: str,
    inp: GenerateReportInput,
    report_id: str,
    error: str,
) -> None:
    import asyncpg
    from datetime import date
    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute(
            """
            INSERT INTO cts.session_reports (
                report_id, session_id, bank_id, branch_id, branch_ifsc,
                clearing_date, session_type, status, error_detail
            ) VALUES ($1,$2,$3,$4,$5,CURRENT_DATE,$6,'FAILED',$7)
            ON CONFLICT (session_id, bank_id) DO UPDATE SET
                status = 'FAILED', error_detail = EXCLUDED.error_detail
            """,
            report_id, inp.session_id, inp.bank_id,
            inp.branch_id, inp.branch_ifsc, "UNKNOWN", error[:500],
        )
    finally:
        await conn.close()


async def _write_audit(
    bank_id: str,
    session_id: str,
    report_id: str,
    html_path: str,
    pdf_path: str,
    instrument_count: int,
) -> None:
    from shared.audit.audit_event import AuditEvent, AuditEventType
    from shared.messages import get_message

    event = AuditEvent(
        event_type=AuditEventType.SESSION_REPORT_GENERATED,
        bank_id=bank_id,
        actor="system",
        details={
            "session_id": session_id,
            "report_id": report_id,
            "html_minio_path": html_path,
            "pdf_minio_path": pdf_path,
            "instrument_count": instrument_count,
        },
    )
    await event.write()
