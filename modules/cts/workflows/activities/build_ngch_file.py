"""
build_ngch_file — Temporal activity that wires IQAEngine + NGCHSigner +
CIBFAssembler + CXFBuilder into a spec-compliant outward submission bundle.

Pipeline per instrument (synchronous, CPU-bound):
  1. IQAEngine.run(IQAInput) → IQAResult → 3 user fields (BFB:, BBB:, BFG:)
  2. NGCHSigner.sign_micr(micr_line) → MICRDS (344-char Base64)
  3. NGCHSigner.sign_image(front_bw_bytes) → ImageDS (256-byte raw binary)
  4. CIBFAssembler.assemble(CIBFInput) → CIBFResult (binary bundle)
  5. Build CXFItem (3 IQA user fields per CHI Spec Rev 3.0)
  After all instruments:
  6. CXFBuilder.build(items, session_id=...) → CXF XML bytes

Returns BuildNGCHFileResult with:
  - cxf_bytes: CXF XML ready for NGCHAdapter.submit (SFTP or REST)
  - cibf_bytes_per_instrument: {item_seq_no → CIBF binary bytes}
  - instrument_count: number of processed instruments

OTel span wraps the entire activity. Every instrument signs via the injected
HSM — no private key material is held in Python memory.

HSM contract (duck-typed, same as NGCHSigner):
  hsm.sign(data: bytes) -> bytes   # RSA-SHA256 PKCS#1v15, 256-byte output
"""
from __future__ import annotations

from typing import Any, Dict, List

import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict

from modules.cts.ngch.cibf_assembler import CIBFAssembler, CIBFInput
from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem
from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput
from modules.cts.ngch.signer import NGCHSigner

log = structlog.get_logger()
tracer = trace.get_tracer("astra.cts.activities")


class InstrumentBuildInput(BaseModel):
    """Per-instrument data needed to produce one CIBF + one CXFItem."""
    model_config = ConfigDict(frozen=True)

    item_seq_no: str
    micr_line: str
    drawee_ifsc: str
    drawee_account: str
    amount_paise: int
    front_bw_bytes: bytes
    back_bw_bytes: bytes
    front_gray_bytes: bytes
    width_px: int
    height_px: int
    dpi: int
    bit_depth: int
    presenting_bank_rout_no: str
    cycle_no: str
    presentment_date: str
    batch_id: str


class BuildNGCHFileInput(BaseModel):
    """Input to the build_ngch_file activity."""
    model_config = ConfigDict(frozen=True)

    bank_id: str
    lot_number: str
    session_id: str
    instruments: List[InstrumentBuildInput]


class BuildNGCHFileResult(BaseModel):
    """Output of the build_ngch_file activity."""
    model_config = ConfigDict(frozen=True)

    lot_number: str
    bank_id: str
    cxf_bytes: bytes
    cibf_bytes_per_instrument: Dict[str, bytes]
    instrument_count: int


def build_ngch_file(inp: BuildNGCHFileInput, *, hsm: Any) -> BuildNGCHFileResult:
    """Orchestrate IQAEngine + NGCHSigner + CIBFAssembler + CXFBuilder.

    This is a synchronous activity — all operations are CPU-bound or HSM calls.
    The hsm argument must implement sign(data: bytes) -> bytes (RSA-SHA256).

    Raises ValueError if inp.instruments is empty (CXF spec requires ≥1 item).
    """
    with tracer.start_as_current_span("activity.build_ngch_file") as span:
        span.set_attribute("bank_id", inp.bank_id)
        span.set_attribute("lot_number", inp.lot_number)
        span.set_attribute("session_id", inp.session_id)
        span.set_attribute("instrument_count", len(inp.instruments))

        if not inp.instruments:
            raise ValueError(
                "build_ngch_file: instruments list is empty — "
                "CXF requires at least one instrument per submission."
            )

        signer = NGCHSigner(hsm=hsm)
        iqa_engine = IQAEngine()
        cibf_assembler = CIBFAssembler()

        cxf_items: List[CXFItem] = []
        cibf_map: Dict[str, bytes] = {}

        for instrument in inp.instruments:
            seq = instrument.item_seq_no

            # Step 1 — IQA
            iqa_result = iqa_engine.run(IQAInput(
                front_bw_bytes=instrument.front_bw_bytes,
                back_bw_bytes=instrument.back_bw_bytes,
                front_gray_bytes=instrument.front_gray_bytes,
                width_px=instrument.width_px,
                height_px=instrument.height_px,
                dpi=instrument.dpi,
                bit_depth=instrument.bit_depth,
            ))
            # Three IQA user fields per CHI Spec Rev 3.0
            uf_front_bw   = iqa_result.user_field_front_bw()
            uf_back_bw    = iqa_result.user_field_back_bw()
            uf_front_gray = iqa_result.user_field()

            # Step 2 — MICRDS (sign MICR line)
            micrds = signer.sign_micr(instrument.micr_line)

            # Step 3 — ImageDS (sign front B/W image)
            image_ds = signer.sign_image(instrument.front_bw_bytes)

            # Step 4 — CIBF assembly (embeds ImageDS at offset 512)
            cibf_result = cibf_assembler.assemble(CIBFInput(
                front_bw=instrument.front_bw_bytes,
                back_bw=instrument.back_bw_bytes,
                front_gray=instrument.front_gray_bytes,
                image_ds=image_ds,
            ))
            cibf_map[seq] = cibf_result.cibf_bytes

            # Step 5 — Build CXFItem (3 IQA user fields per CHI Spec Rev 3.0)
            cxf_items.append(CXFItem(
                item_seq_no=seq,
                micr_line=instrument.micr_line,
                micrds=micrds,
                iqa_user_field_front_bw=uf_front_bw,
                iqa_user_field_back_bw=uf_back_bw,
                iqa_user_field_front_gray=uf_front_gray,
                amount_paise=instrument.amount_paise,
                drawee_ifsc=instrument.drawee_ifsc,
                drawee_account=instrument.drawee_account,
                presenting_bank_rout_no=instrument.presenting_bank_rout_no,
                cycle_no=instrument.cycle_no,
                presentment_date=instrument.presentment_date,
                batch_id=instrument.batch_id,
            ))

        # Step 6 — CXF XML
        cxf_bytes = CXFBuilder().build(cxf_items, session_id=inp.session_id)

        log.info(
            "build_ngch_file.complete",
            bank_id=inp.bank_id,
            lot_number=inp.lot_number,
            session_id=inp.session_id,
            instrument_count=len(inp.instruments),
            cxf_bytes=len(cxf_bytes),
        )
        span.set_attribute("cxf_bytes", len(cxf_bytes))

        return BuildNGCHFileResult(
            lot_number=inp.lot_number,
            bank_id=inp.bank_id,
            cxf_bytes=cxf_bytes,
            cibf_bytes_per_instrument=cibf_map,
            instrument_count=len(inp.instruments),
        )
