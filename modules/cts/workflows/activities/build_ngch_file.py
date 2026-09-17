"""
build_ngch_file — Temporal activity: outward CXF + CIBF bundle per CHI Spec Rev 3.00.

Pipeline per instrument:
  1. IQAEngine.run()            → IQAResult → 3 UserFields (21 chars: BFB/BBB/BFG)
  2. NGCHSigner.sign_micr()     → MICRDSResult (fingerprint + 344-char Base64 sig)
  3. NGCHSigner.sign_image() ×3 → 3 × 256-byte ImageDS (front BW, back BW, front gray)
  4. Accumulate CIBFInstrumentInput (DS + images for lot assembler)
  5. Build CXFItem (all fields as attributes; offsets populated after lot assembly)

After all instruments:
  6. CIBFAssembler.assemble_lot() → CIBFLotResult (single lot-level binary + offsets)
  7. Backfill CIBF byte offsets into CXFItems
  8. CXFBuilder.build()          → CXF XML bytes
  9. Generate spec-compliant CXF + CIBF filenames via filenames.py

Returns BuildNGCHFileResult with:
  - cxf_bytes, cibf_bytes (lot-level)
  - cxf_filename, cibf_filename (spec format)
  - instrument_count

OTel span wraps the entire activity. HSM is injected — no private key in Python.
"""
from __future__ import annotations

from typing import Any, List

import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict

from modules.cts.ngch.cibf_assembler import (
    CIBFAssembler, CIBFInstrumentInput,
)
from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem
from modules.cts.ngch.filenames import make_cxf_filename, make_cibf_filename
from modules.cts.ngch.iqa_engine import IQAEngine, IQAInput
from modules.cts.ngch.signer import NGCHSigner

log = structlog.get_logger()
tracer = trace.get_tracer("astra.cts.activities")


class InstrumentBuildInput(BaseModel):
    """Per-instrument data needed to build one CIBF segment and one CXFItem."""
    model_config = ConfigDict(frozen=True)

    item_seq_no: str               # exactly 14 chars
    payor_bank_rout_no: str        # 9-digit NPCI routing of drawee bank
    account_no: str                # masked (last-4 only) for logging
    serial_no: str                 # MICR cheque serial number
    trans_code: str                # MICR transaction code
    doc_type: str                  # document type code, e.g. "01"
    micr_line: str
    drawee_ifsc: str
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
    presentment_date: str          # DDMMYYYY
    batch_id: str


class BuildNGCHFileInput(BaseModel):
    """Input to the build_ngch_file activity."""
    model_config = ConfigDict(frozen=True)

    bank_id: str
    lot_number: str
    session_id: str
    routing_no: str                # presenting bank NPCI routing number (for filename)
    clearing_type: str             # "14" or "99"
    file_id: str                   # e.g. "0001"
    date_ddmmyyyy: str             # e.g. "01042026"
    time_hhmmss: str               # e.g. "103000"
    instruments: List[InstrumentBuildInput]


class BuildNGCHFileResult(BaseModel):
    """Output of the build_ngch_file activity."""
    model_config = ConfigDict(frozen=True)

    lot_number: str
    bank_id: str
    cxf_bytes: bytes
    cibf_bytes: bytes
    cxf_filename: str
    cibf_filename: str
    instrument_count: int


def build_ngch_file(inp: BuildNGCHFileInput, *, hsm: Any) -> BuildNGCHFileResult:
    """Orchestrate IQA + signing + CIBF assembly + CXF build for one lot.

    Synchronous — all operations are CPU-bound or HSM calls.
    The hsm argument must implement sign(data: bytes) -> bytes (RSA-SHA256, 256 bytes out).
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

        # Accumulate data in two passes:
        #   Pass 1: IQA + signing + collect CIBF inputs and partial CXF items
        #   Pass 2: assemble lot-level CIBF, then backfill byte offsets into CXF items

        cibf_inputs: List[CIBFInstrumentInput] = []
        # Store partial CXFItem kwargs (missing offset fields until after CIBF assembly)
        partial_cxf_kwargs: List[dict] = []

        for instrument in inp.instruments:
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

            # Step 2 — MICRDS (sign field values, not raw MICR line)
            micrds_result = signer.sign_micr(
                presentment_date=instrument.presentment_date,
                presenting_bank_rout_no=instrument.presenting_bank_rout_no,
                cycle_no=instrument.cycle_no,
                item_seq_no=instrument.item_seq_no,
                amount=instrument.amount_paise,
                serial_no=instrument.serial_no,
                trans_code=instrument.trans_code,
            )

            # Step 3 — ImageDS × 3 (one per image view)
            ds_front_bw   = signer.sign_image(instrument.front_bw_bytes)
            ds_back_bw    = signer.sign_image(instrument.back_bw_bytes)
            ds_front_gray = signer.sign_image(instrument.front_gray_bytes)

            cibf_inputs.append(CIBFInstrumentInput(
                item_seq_no=instrument.item_seq_no,
                front_bw=instrument.front_bw_bytes,
                back_bw=instrument.back_bw_bytes,
                front_gray=instrument.front_gray_bytes,
                ds_front_bw=ds_front_bw,
                ds_back_bw=ds_back_bw,
                ds_front_gray=ds_front_gray,
            ))

            partial_cxf_kwargs.append(dict(
                item_seq_no=instrument.item_seq_no,
                payor_bank_rout_no=instrument.payor_bank_rout_no,
                account_no=instrument.account_no,
                serial_no=instrument.serial_no,
                trans_code=instrument.trans_code,
                doc_type=instrument.doc_type,
                micr_line=instrument.micr_line,
                micrds_fingerprint=micrds_result.fingerprint,
                micrds_signature=micrds_result.signature_b64,
                iqa_user_field_front_bw=iqa_result.user_field_front_bw(),
                iqa_user_field_back_bw=iqa_result.user_field_back_bw(),
                iqa_user_field_front_gray=iqa_result.user_field(),
                amount_paise=instrument.amount_paise,
                drawee_ifsc=instrument.drawee_ifsc,
                presenting_bank_rout_no=instrument.presenting_bank_rout_no,
                cycle_no=instrument.cycle_no,
                presentment_date=instrument.presentment_date,
                batch_id=instrument.batch_id,
            ))

            log.debug(
                "build_ngch_file.instrument_signed",
                item_seq_no=instrument.item_seq_no,
                account_suffix=instrument.account_no,
            )

        # Step 4 — Lot-level CIBF assembly
        cibf_lot = CIBFAssembler().assemble_lot(cibf_inputs)

        # Step 5 — Backfill CIBF byte offsets into CXFItems
        cxf_items: List[CXFItem] = []
        for kwargs, off in zip(partial_cxf_kwargs, cibf_lot.instrument_offsets):
            cxf_items.append(CXFItem(
                **kwargs,
                front_bw_ds_offset=off.front_bw_ds_offset,
                front_bw_image_offset=off.front_bw_image_offset,
                front_bw_image_length=off.front_bw_image_length,
                back_bw_ds_offset=off.back_bw_ds_offset,
                back_bw_image_offset=off.back_bw_image_offset,
                back_bw_image_length=off.back_bw_image_length,
                front_gray_ds_offset=off.front_gray_ds_offset,
                front_gray_image_offset=off.front_gray_image_offset,
                front_gray_image_length=off.front_gray_image_length,
            ))

        # Step 6 — Generate spec-compliant filenames
        cxf_filename  = make_cxf_filename(
            inp.routing_no, inp.date_ddmmyyyy, inp.time_hhmmss, inp.clearing_type, inp.file_id
        )
        cibf_filename = make_cibf_filename(
            inp.routing_no, inp.date_ddmmyyyy, inp.time_hhmmss, inp.clearing_type, inp.file_id, "01"
        )

        # Step 7 — Build CXF XML
        cxf_bytes = CXFBuilder().build(cxf_items, session_id=inp.session_id, cibf_filename=cibf_filename)

        log.info(
            "build_ngch_file.complete",
            bank_id=inp.bank_id,
            lot_number=inp.lot_number,
            cxf_filename=cxf_filename,
            cibf_filename=cibf_filename,
            instrument_count=len(inp.instruments),
            cxf_bytes=len(cxf_bytes),
            cibf_bytes=len(cibf_lot.cibf_bytes),
        )
        span.set_attribute("cxf_bytes", len(cxf_bytes))
        span.set_attribute("cibf_bytes", len(cibf_lot.cibf_bytes))

        return BuildNGCHFileResult(
            lot_number=inp.lot_number,
            bank_id=inp.bank_id,
            cxf_bytes=cxf_bytes,
            cibf_bytes=cibf_lot.cibf_bytes,
            cxf_filename=cxf_filename,
            cibf_filename=cibf_filename,
            instrument_count=len(inp.instruments),
        )
