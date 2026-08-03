"""
Demo pipeline API router.

Provides endpoints for the end-to-end cheque processing demonstration:
  - Session management (create, upload files, get state)
  - SSE stream for real-time step events
  - Trigger presentment / drawee pipelines
  - Download success/failure CSVs

All state is in-memory (demo_pipeline singleton).
No auth required on demo endpoints — demo mode only.
"""
import asyncio
from typing import List, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from modules.cts.demo.csv_writer import write_failure_csv, write_success_csv
from modules.cts.demo.pipeline import DRAWEE_BANKS, demo_pipeline

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/demo", tags=["Demo Pipeline"])


# ── Request models ─────────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    bank_id:   str = "demo-bank"
    filenames: Optional[List[str]] = None


class RunDraweeRequest(BaseModel):
    bank_name: Optional[str] = None


# ── Session endpoints ──────────────────────────────────────────────────────────

@router_v1.post("/sessions")
async def create_session(body: CreateSessionRequest):
    session = demo_pipeline.create_session(bank_id=body.bank_id)
    if body.filenames:
        demo_pipeline.add_items(session.session_id, body.filenames)
    return {
        "session_id": session.session_id,
        "bank_id":    session.bank_id,
        "item_count": len(session.items),
    }


@router_v1.post("/sessions/{session_id}/upload")
async def upload_cheques(session_id: str, files: List[UploadFile] = File(...)):
    """Accept cheque image files from browser drag-and-drop upload."""
    session = demo_pipeline.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    filenames = [f.filename or f"file_{i}.jpg" for i, f in enumerate(files)]
    demo_pipeline.add_items(session_id, filenames)
    log.info("demo.files_uploaded", session_id=session_id, count=len(filenames))
    return {"session_id": session_id, "uploaded": len(filenames), "filenames": filenames}


@router_v1.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session = demo_pipeline.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id":  session.session_id,
        "bank_id":     session.bank_id,
        "phase":       session.phase.value,
        "total":       len(session.items),
        "success":     sum(1 for it in session.items if it.status.value == "success"),
        "failed":      sum(1 for it in session.items if it.status.value == "failed"),
        "in_progress": sum(1 for it in session.items if it.status.value in ("queued", "processing")),
        "npci_groups": {k: len(v) for k, v in (session.npci_output or {}).items()},
        "drawee_banks": [b["name"] for b in DRAWEE_BANKS],
        "items": [
            {
                "item_id":      it.item_id,
                "filename":     it.filename,
                "status":       it.status.value,
                "decision":     it.decision,
                "reject_reason": it.reject_reason,
                "total_ms":     it.total_ms,
                "steps":        [{"step": s.step, "status": s.status.value, "duration_ms": s.duration_ms} for s in it.steps],
                "drawee_bank":  it.drawee_bank,
            }
            for it in session.items
        ],
        "drawee_items": [
            {
                "item_id":      it.item_id,
                "filename":     it.filename,
                "status":       it.status.value,
                "decision":     it.decision,
                "reject_reason": it.reject_reason,
                "total_ms":     it.total_ms,
            }
            for it in session.drawee_items
        ],
    }


# ── SSE stream ─────────────────────────────────────────────────────────────────

@router_v1.get("/sessions/{session_id}/stream")
async def stream_events(session_id: str):
    """Server-Sent Events stream — subscribe before triggering pipeline runs."""
    session = demo_pipeline.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return StreamingResponse(
        demo_pipeline.events(session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "Connection":       "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Pipeline triggers ──────────────────────────────────────────────────────────

@router_v1.post("/sessions/{session_id}/run-presentment")
async def run_presentment(session_id: str, background_tasks: BackgroundTasks):
    """Kick off presentment pipeline. Subscribe to /stream first for live events."""
    session = demo_pipeline.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.items:
        raise HTTPException(status_code=400, detail="No cheques in session. Upload files first.")

    background_tasks.add_task(demo_pipeline.run_presentment, session_id)
    log.info("demo.presentment_started", session_id=session_id, items=len(session.items))
    return {"status": "started", "session_id": session_id, "items": len(session.items)}


@router_v1.post("/sessions/{session_id}/run-drawee")
async def run_drawee(session_id: str, body: RunDraweeRequest = RunDraweeRequest()):
    """Kick off drawee pipeline for a specific bank (or first bank in NPCI groups)."""
    session = demo_pipeline.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    bank_name = body.bank_name
    if not bank_name and session.npci_output:
        bank_name = next(iter(session.npci_output))
    if not bank_name:
        raise HTTPException(status_code=400, detail="No bank specified and no NPCI output available. Run presentment first.")

    asyncio.create_task(demo_pipeline.run_drawee(session_id, bank_name))
    log.info("demo.drawee_started", session_id=session_id, bank=bank_name)
    return {"status": "started", "session_id": session_id, "bank": bank_name}


# ── CSV downloads ──────────────────────────────────────────────────────────────

@router_v1.get("/sessions/{session_id}/csv/presentment-success")
async def download_presentment_success(session_id: str):
    session = demo_pipeline.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    content = write_success_csv(session.items, phase="presentment")
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="presentment_success_{session_id[:8]}.csv"'},
    )


@router_v1.get("/sessions/{session_id}/csv/presentment-failure")
async def download_presentment_failure(session_id: str):
    session = demo_pipeline.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    content = write_failure_csv(session.items)
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="presentment_failure_{session_id[:8]}.csv"'},
    )


@router_v1.get("/sessions/{session_id}/csv/drawee-success")
async def download_drawee_success(session_id: str):
    session = demo_pipeline.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    content = write_success_csv(session.drawee_items, phase="drawee")
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="drawee_success_{session_id[:8]}.csv"'},
    )


@router_v1.get("/sessions/{session_id}/csv/drawee-failure")
async def download_drawee_failure(session_id: str):
    session = demo_pipeline.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    content = write_failure_csv(session.drawee_items)
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="drawee_failure_{session_id[:8]}.csv"'},
    )
