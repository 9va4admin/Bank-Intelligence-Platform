"""
Demo pipeline orchestrator.

Runs simulated presentment and drawee cheque processing pipelines with
realistic step timings and failure injection. No GPU or external services
required — designed for bank demos where full infra is unavailable.

Failure injection is deterministic (based on item index), so the same set
of files always produces the same mix of success/failure cases for a
repeatable demo.
"""
import asyncio
import json
import random
import time
from typing import AsyncGenerator, Dict, List, Optional

import structlog

from modules.cts.demo.models import (
    DemoItem,
    DemoSession,
    DraweeStep,
    ItemStatus,
    PresentmentStep,
    SessionPhase,
    StepResult,
    StepStatus,
)

log = structlog.get_logger()

# ── Simulated drawee bank pool (NPCI routing targets) ─────────────────────────

DRAWEE_BANKS = [
    {"name": "State Bank of India",     "ifsc": "SBIN0000001", "short": "SBI"},
    {"name": "HDFC Bank Ltd",           "ifsc": "HDFC0000001", "short": "HDFC"},
    {"name": "ICICI Bank Ltd",          "ifsc": "ICIC0000001", "short": "ICICI"},
    {"name": "Axis Bank Ltd",           "ifsc": "UTIB0000001", "short": "AXIS"},
]

# ── Step definitions: (enum value, display label, min_ms, max_ms) ─────────────

PRESENTMENT_STEPS = [
    (PresentmentStep.FILE_DETECTED,   "File detected in input folder",        40,   150),
    (PresentmentStep.IMAGE_LOAD,      "Image loaded and decoded",             80,   250),
    (PresentmentStep.OCR_MICR,        "GOT-OCR2.0 — MICR line extraction",   350,  750),
    (PresentmentStep.CTS_COMPLIANCE,  "CTS-2010 compliance — 8 checks",      120,  350),
    (PresentmentStep.VISION_LLM,      "Qwen2-VL — alteration detection",     500, 1100),
    (PresentmentStep.DATA_EXTRACTION, "Field extraction and cross-check",     150,  400),
    (PresentmentStep.LOT_ASSIGNMENT,  "Assigned to clearing lot",             60,   160),
    (PresentmentStep.DECISION,        "Presentment decision rendered",        40,   120),
]

DRAWEE_STEPS = [
    (DraweeStep.FILE_RECEIPT,    "Received from NPCI clearing grid",          60,   180),
    (DraweeStep.OCR_REEXTRACT,   "GOT-OCR2.0 — field re-extraction",         300,  650),
    (DraweeStep.RBI_CHECKLIST,   "RBI CTS-2010 checklist — 11 items",        180,  420),
    (DraweeStep.SIGNATURE_VAULT, "Siamese SNN — signature match",             280,  600),
    (DraweeStep.ACCOUNT_STATUS,  "CBS Finacle — account status check",        180,  380),
    (DraweeStep.STOP_PAYMENT,    "CBS stop-payment lookup",                   220,  450),
    (DraweeStep.PPS_CHECK,       "PPS positive pay validation",               130,  300),
    (DraweeStep.FRAUD_SCORE,     "XGBoost + SHAP — fraud score",             280,  580),
    (DraweeStep.VISION_LLM,      "Qwen2-VL — final verification",            480, 1000),
    (DraweeStep.DECISION,        "IET-safe decision filed to NGCH",           50,   140),
]

# ── Deterministic failure injection ───────────────────────────────────────────

def _presentment_failure(index: int) -> Optional[dict]:
    """Returns failure spec for presentment, or None if item should succeed."""
    if index % 7 == 6:
        return {
            "step": PresentmentStep.DATA_EXTRACTION.value,
            "reason": "AMOUNT_MISMATCH",
            "detail": f"Amount figures ₹{(index % 5 + 1) * 10000:,} do not match words — discrepancy detected by cross-validator.",
        }
    if index % 13 == 12:
        return {
            "step": PresentmentStep.VISION_LLM.value,
            "reason": "ALTERATION_DETECTED",
            "detail": "Qwen2-VL reports overwriting in amount field (tamper confidence 0.91). Instrument rejected per CTS-2010 §5.2.",
        }
    if index % 19 == 18:
        return {
            "step": PresentmentStep.CTS_COMPLIANCE.value,
            "reason": "CTS_IMAGE_QUALITY",
            "detail": "Image DPI below CTS-2010 minimum (96 DPI required, detected 68 DPI). Re-scan required.",
        }
    return None


def _drawee_failure(index: int) -> Optional[dict]:
    """Returns failure spec for drawee, or None if item should confirm."""
    if index % 11 == 10:
        return {
            "step": DraweeStep.STOP_PAYMENT.value,
            "reason": "STOP_PAYMENT_ACTIVE",
            "detail": "CBS confirms stop-payment instruction active. Instruction filed: 2026-06-29 14:32. Instrument returned.",
        }
    if index % 17 == 16:
        return {
            "step": DraweeStep.SIGNATURE_VAULT.value,
            "reason": "SIGNATURE_MISMATCH",
            "detail": "Siamese SNN match score 0.42 (threshold 0.85). 2 registered specimens on record. Human review required.",
        }
    if index % 23 == 22:
        return {
            "step": DraweeStep.ACCOUNT_STATUS.value,
            "reason": "ACCOUNT_FROZEN",
            "detail": "CBS: account status FROZEN (court order ref CO-2026-MUM-4421). Instrument returned immediately.",
        }
    return None


# ── Simulated extraction data ──────────────────────────────────────────────────

_AMOUNTS = [10_000, 25_000, 45_000, 72_500, 1_00_000, 2_00_000, 3_50_000, 5_00_000]
_WORDS   = [
    "Ten Thousand Only", "Twenty Five Thousand Only", "Forty Five Thousand Only",
    "Seventy Two Thousand Five Hundred Only", "One Lakh Only",
    "Two Lakhs Only", "Three Lakhs Fifty Thousand Only", "Five Lakhs Only",
]
_PAYEES  = [
    "M/s Sunshine Traders", "ABC Enterprises Pvt Ltd", "R.K. Construction Co.",
    "Priya Hospital Trust", "National Exports Ltd",
    "Kotak Mahindra Bank Ltd", "Future Tech Solutions", "Rajesh Kumar",
]


def _micr_data(index: int) -> dict:
    cheque_no = str(800_001 + index).zfill(6)
    account   = "".join(str((index * 31 + i * 7) % 10) for i in range(11))
    ifsc_tail = "".join(str((index * 13 + i * 3) % 10) for i in range(7))
    return {
        "micr_line":     f"⑈{cheque_no}⑆SBIN{ifsc_tail}⑉{account[:9]}",
        "cheque_number": cheque_no,
        "ifsc_code":     f"SBIN{ifsc_tail}",
        "account_number": f"****{account[-4:]}",
        "confidence":    round(0.97 + (index % 3) * 0.01, 2),
    }


def _extraction_data(index: int) -> dict:
    amt_i  = index % len(_AMOUNTS)
    amount = _AMOUNTS[amt_i]
    word   = _WORDS[amt_i]
    payee  = _PAYEES[index % len(_PAYEES)]
    # Inject mismatch for AMOUNT_MISMATCH failures
    if index % 7 == 6:
        word = word.replace("Five", "Six").replace("Ten", "Eleven")
    day   = str((index % 28) + 1).zfill(2)
    month = str((index % 12) + 1).zfill(2)
    return {
        "amount_figures": f"₹{amount:,}",
        "amount_words":   word,
        "payee":          payee,
        "date":           f"{day}-{month}-2026",
        "match_ok":       index % 7 != 6,
    }


# ── Pipeline class ─────────────────────────────────────────────────────────────

class DemoPipeline:
    """
    In-memory demo pipeline.  Thread-safe for concurrent async use within a
    single event loop (one pod).  Not distributed across pods — demo-only.
    """

    MAX_CONCURRENT = 5

    def __init__(self) -> None:
        self._sessions: Dict[str, DemoSession] = {}
        self._queues:   Dict[str, asyncio.Queue] = {}

    # ── public: session management ────────────────────────────────────────────

    def create_session(self, bank_id: str = "demo-bank") -> DemoSession:
        session = DemoSession(bank_id=bank_id)
        self._sessions[session.session_id] = session
        self._queues[session.session_id]   = asyncio.Queue(maxsize=2000)
        return session

    def get_session(self, session_id: str) -> Optional[DemoSession]:
        return self._sessions.get(session_id)

    def add_items(self, session_id: str, filenames: List[str]) -> DemoSession:
        session = self._sessions[session_id]
        for fn in filenames:
            session.items.append(DemoItem(filename=fn))
        return session

    # ── public: SSE stream ────────────────────────────────────────────────────

    async def events(self, session_id: str) -> AsyncGenerator[str, None]:
        """Yields SSE-formatted strings until processing ends or timeout."""
        q = self._queues.get(session_id)
        if not q:
            return
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue

            if msg is None:  # sentinel — end of stream
                yield "event: done\ndata: {}\n\n"
                return

            payload = json.dumps(msg["data"], default=str)
            yield f"event: {msg['event']}\ndata: {payload}\n\n"

    # ── public: pipelines ─────────────────────────────────────────────────────

    async def run_presentment(self, session_id: str) -> None:
        session = self._sessions[session_id]
        session.phase = SessionPhase.PRESENTMENT

        await self._emit(session_id, "session_started", {
            "session_id":  session_id,
            "phase":       "presentment",
            "total_items": len(session.items),
        })

        sem   = asyncio.Semaphore(self.MAX_CONCURRENT)
        tasks = [
            self._process_presentment(session_id, item, idx, sem)
            for idx, item in enumerate(session.items)
        ]
        await asyncio.gather(*tasks)

        # Build NPCI groupings from accepted items
        session.npci_output = self._npci_groups(session)
        session.phase        = SessionPhase.NPCI_SIMULATION

        success = sum(1 for it in session.items if it.status == ItemStatus.SUCCESS)
        failed  = sum(1 for it in session.items if it.status == ItemStatus.FAILED)
        await self._emit(session_id, "presentment_complete", {
            "session_id":  session_id,
            "success":     success,
            "failed":      failed,
            "npci_groups": {bank: len(ids) for bank, ids in session.npci_output.items()},
        })

    async def run_drawee(self, session_id: str, bank_name: str) -> None:
        session = self._sessions[session_id]
        session.phase = SessionPhase.DRAWEE

        bank_items = [
            it for it in session.items
            if it.status == ItemStatus.SUCCESS and it.drawee_bank == bank_name
        ]

        # Fresh DemoItem objects for the drawee pass (separate pipeline)
        session.drawee_items = [
            DemoItem(filename=it.filename, extracted=it.extracted)
            for it in bank_items
        ]

        await self._emit(session_id, "drawee_started", {
            "bank":        bank_name,
            "total_items": len(session.drawee_items),
        })

        sem   = asyncio.Semaphore(self.MAX_CONCURRENT)
        tasks = [
            self._process_drawee(session_id, item, idx, sem)
            for idx, item in enumerate(session.drawee_items)
        ]
        await asyncio.gather(*tasks)

        session.phase = SessionPhase.COMPLETE
        success = sum(1 for it in session.drawee_items if it.status == ItemStatus.SUCCESS)
        failed  = sum(1 for it in session.drawee_items if it.status == ItemStatus.FAILED)
        await self._emit(session_id, "drawee_complete", {
            "session_id": session_id,
            "bank":       bank_name,
            "success":    success,
            "failed":     failed,
        })

        # Close SSE stream
        await self._queues[session_id].put(None)

    # ── private helpers ───────────────────────────────────────────────────────

    async def _emit(self, session_id: str, event: str, data: dict) -> None:
        q = self._queues.get(session_id)
        if q:
            await q.put({"event": event, "data": data})

    def _npci_groups(self, session: DemoSession) -> Dict[str, List[str]]:
        groups: Dict[str, List[str]] = {}
        for item in session.items:
            if item.status == ItemStatus.SUCCESS and item.drawee_bank:
                groups.setdefault(item.drawee_bank, []).append(item.item_id)
        return groups

    async def _process_presentment(
        self,
        session_id: str,
        item: DemoItem,
        index: int,
        sem: asyncio.Semaphore,
    ) -> None:
        async with sem:
            item.status     = ItemStatus.PROCESSING
            item.started_at = time.time()
            failure         = _presentment_failure(index)

            await self._emit(session_id, "item_started", {
                "item_id":  item.item_id,
                "filename": item.filename,
                "phase":    "presentment",
            })

            for step_enum, label, min_ms, max_ms in PRESENTMENT_STEPS:
                step_name = step_enum.value

                await self._emit(session_id, "step_started", {
                    "item_id": item.item_id,
                    "step":    step_name,
                    "label":   label,
                })

                delay_s   = random.randint(min_ms, max_ms) / 1000
                await asyncio.sleep(delay_s)
                actual_ms = int(delay_s * 1000)

                if failure and failure["step"] == step_name:
                    item.steps.append(StepResult(
                        step=step_name, status=StepStatus.FAILED,
                        duration_ms=actual_ms, detail=failure["detail"],
                    ))
                    item.status       = ItemStatus.FAILED
                    item.decision     = "REJECTED"
                    item.reject_reason = failure["reason"]
                    item.completed_at = time.time()
                    item.total_ms     = int((item.completed_at - item.started_at) * 1000)
                    await self._emit(session_id, "step_failed", {
                        "item_id":    item.item_id,
                        "step":       step_name,
                        "reason":     failure["reason"],
                        "detail":     failure["detail"],
                        "duration_ms": actual_ms,
                    })
                    await self._emit(session_id, "item_complete", {
                        "item_id":  item.item_id,
                        "decision": "REJECTED",
                        "reason":   failure["reason"],
                        "total_ms": item.total_ms,
                        "phase":    "presentment",
                    })
                    return

                # Build per-step data
                step_data = None
                if step_name == PresentmentStep.OCR_MICR.value:
                    step_data = _micr_data(index)
                elif step_name == PresentmentStep.DATA_EXTRACTION.value:
                    step_data = _extraction_data(index)
                    item.extracted = step_data
                elif step_name == PresentmentStep.VISION_LLM.value:
                    step_data = {
                        "tamper_risk": round(0.01 + random.random() * 0.03, 3),
                        "confidence":  round(0.95 + random.random() * 0.04, 3),
                        "model":       "Qwen2-VL-7B",
                    }
                elif step_name == PresentmentStep.CTS_COMPLIANCE.value:
                    step_data = {"checks_passed": 8, "checks_total": 8, "standard": "CTS-2010"}
                elif step_name == PresentmentStep.LOT_ASSIGNMENT.value:
                    step_data = {
                        "lot_id":       f"LOT-{(index // 25) + 1:03d}",
                        "lot_position": (index % 25) + 1,
                    }

                item.steps.append(StepResult(
                    step=step_name, status=StepStatus.PASSED,
                    duration_ms=actual_ms, data=step_data,
                ))
                await self._emit(session_id, "step_complete", {
                    "item_id":    item.item_id,
                    "step":       step_name,
                    "label":      label,
                    "duration_ms": actual_ms,
                    "data":       step_data,
                })

            item.status       = ItemStatus.SUCCESS
            item.decision     = "ACCEPTED"
            item.drawee_bank  = DRAWEE_BANKS[index % len(DRAWEE_BANKS)]["name"]
            item.completed_at = time.time()
            item.total_ms     = int((item.completed_at - item.started_at) * 1000)
            await self._emit(session_id, "item_complete", {
                "item_id":     item.item_id,
                "decision":    "ACCEPTED",
                "total_ms":    item.total_ms,
                "drawee_bank": item.drawee_bank,
                "phase":       "presentment",
            })

    async def _process_drawee(
        self,
        session_id: str,
        item: DemoItem,
        index: int,
        sem: asyncio.Semaphore,
    ) -> None:
        async with sem:
            item.status     = ItemStatus.PROCESSING
            item.started_at = time.time()
            failure         = _drawee_failure(index)

            await self._emit(session_id, "item_started", {
                "item_id":  item.item_id,
                "filename": item.filename,
                "phase":    "drawee",
            })

            for step_enum, label, min_ms, max_ms in DRAWEE_STEPS:
                step_name = step_enum.value

                await self._emit(session_id, "step_started", {
                    "item_id": item.item_id,
                    "step":    step_name,
                    "label":   label,
                    "phase":   "drawee",
                })

                delay_s   = random.randint(min_ms, max_ms) / 1000
                await asyncio.sleep(delay_s)
                actual_ms = int(delay_s * 1000)

                if failure and failure["step"] == step_name:
                    item.steps.append(StepResult(
                        step=step_name, status=StepStatus.FAILED,
                        duration_ms=actual_ms, detail=failure["detail"],
                    ))
                    item.status       = ItemStatus.FAILED
                    item.decision     = "RETURNED"
                    item.reject_reason = failure["reason"]
                    item.completed_at = time.time()
                    item.total_ms     = int((item.completed_at - item.started_at) * 1000)
                    await self._emit(session_id, "step_failed", {
                        "item_id":    item.item_id,
                        "step":       step_name,
                        "reason":     failure["reason"],
                        "detail":     failure["detail"],
                        "duration_ms": actual_ms,
                        "phase":      "drawee",
                    })
                    await self._emit(session_id, "item_complete", {
                        "item_id":  item.item_id,
                        "decision": "RETURNED",
                        "reason":   failure["reason"],
                        "total_ms": item.total_ms,
                        "phase":    "drawee",
                    })
                    return

                step_data = None
                if step_name == DraweeStep.SIGNATURE_VAULT.value:
                    step_data = {"match_score": round(0.88 + random.random() * 0.10, 3), "specimens": 2, "model": "Siamese-SNN"}
                elif step_name == DraweeStep.FRAUD_SCORE.value:
                    step_data = {"fraud_score": round(random.random() * 0.15, 3), "threshold": 0.72, "shap_top_feature": "account_age"}
                elif step_name == DraweeStep.RBI_CHECKLIST.value:
                    step_data = {"checks": 11, "passed": 11, "failed": 0}
                elif step_name == DraweeStep.ACCOUNT_STATUS.value:
                    step_data = {"status": "ACTIVE", "balance_sufficient": True}
                elif step_name == DraweeStep.VISION_LLM.value:
                    step_data = {"tamper_risk": round(0.01 + random.random() * 0.02, 3), "confidence": round(0.95 + random.random() * 0.04, 3), "model": "Qwen2-VL-7B"}
                elif step_name == DraweeStep.PPS_CHECK.value:
                    step_data = {"pps_registered": True, "amount_match": True}

                item.steps.append(StepResult(
                    step=step_name, status=StepStatus.PASSED,
                    duration_ms=actual_ms, data=step_data,
                ))
                await self._emit(session_id, "step_complete", {
                    "item_id":    item.item_id,
                    "step":       step_name,
                    "label":      label,
                    "duration_ms": actual_ms,
                    "data":       step_data,
                    "phase":      "drawee",
                })

            item.status       = ItemStatus.SUCCESS
            item.decision     = "CONFIRMED"
            item.completed_at = time.time()
            item.total_ms     = int((item.completed_at - item.started_at) * 1000)
            await self._emit(session_id, "item_complete", {
                "item_id":  item.item_id,
                "decision": "CONFIRMED",
                "total_ms": item.total_ms,
                "phase":    "drawee",
            })


# Global singleton — demo pipeline is stateless across sessions
demo_pipeline = DemoPipeline()
