"""
LotStore — CHI Spec Rev 3.00 NGCH file builder.

Reads accepted instruments for a sealed lot from cts.outward_scan_events
(for instrument_ids) + cts.cheque_instruments (for all field values + image
MinIO keys), calls the spec-compliant build_ngch_file core builder, and
uploads both the CXF XML and CIBF binary to MinIO.

Returns (cxf_object_key, sha256_hex_of_cxf_bytes).

Usage:
    store = LotStore(db_pool=pool, minio_client=minio, bucket="astra-cts")
    cxf_path, sha256 = await store.build_ngch_file(
        lot_number="LOT_SVCB0000002_20260901_AM_01",
        bank_id="saraswat-coop",
        bank_ifsc="SVCB0000002",
        session_id="SES-SVCB-20260901-001",
        clearing_date="2026-09-01",
        routing_no="000550050",
        clearing_type="14",
        file_id="0001",
        date_ddmmyyyy="01092026",
        time_hhmmss="103000",
        hsm=hsm_client,
    )
"""
from __future__ import annotations

import hashlib
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, List, Optional

import structlog

log = structlog.get_logger()


class LotStore:
    """
    Dependency-injected at worker startup.  `db_pool` is an asyncpg pool;
    `minio_client` is a minio.Minio instance (sync — called in executor or
    directly since upload latency dominates).
    """

    def __init__(
        self,
        *,
        db_pool: Any,
        minio_client: Any,
        bucket: str = "astra-cts",
    ) -> None:
        self._db = db_pool
        self._minio = minio_client
        self._bucket = bucket

    # ------------------------------------------------------------------
    # Public API (called from build_ngch_file activity)
    # ------------------------------------------------------------------

    async def build_ngch_file(
        self,
        lot_number: str,
        bank_id: str,
        bank_ifsc: str,
        session_id: str,
        clearing_date: str,
        routing_no: str,
        clearing_type: str,
        file_id: str = "0001",
        date_ddmmyyyy: Optional[str] = None,
        time_hhmmss: Optional[str] = None,
        hsm: Any = None,
    ) -> tuple[str, str]:
        """
        Assembles CHI Spec Rev 3.00 compliant CXF + CIBF for the lot.

        Returns (cxf_object_key, sha256_hex_of_cxf_bytes).
        Also uploads CIBF to MinIO as a side effect.

        Empty lot → uploads a minimal stub CXF (no CIBF) and returns its path.
        """
        # Derive date/time if not supplied
        if date_ddmmyyyy is None:
            dt = datetime.strptime(clearing_date, "%Y-%m-%d")
            date_ddmmyyyy = dt.strftime("%d%m%Y")
        if time_hhmmss is None:
            time_hhmmss = datetime.now(timezone.utc).strftime("%H%M%S")

        instrument_rows = await self._fetch_lot_instruments(bank_id, lot_number)

        if not instrument_rows:
            return self._upload_empty_lot(lot_number, bank_id, bank_ifsc, clearing_date)

        instrument_inputs = self._build_instrument_inputs(instrument_rows, date_ddmmyyyy, lot_number)

        # Import here to avoid circular imports at module load time
        from modules.cts.workflows.activities.build_ngch_file import (
            build_ngch_file as _core,
            BuildNGCHFileInput,
        )

        build_inp = BuildNGCHFileInput(
            bank_id=bank_id,
            lot_number=lot_number,
            session_id=session_id,
            routing_no=routing_no,
            clearing_type=clearing_type,
            file_id=file_id,
            date_ddmmyyyy=date_ddmmyyyy,
            time_hhmmss=time_hhmmss,
            instruments=instrument_inputs,
        )
        result = _core(build_inp, hsm=hsm)

        cxf_key = f"cts/ngch/{bank_id}/{lot_number}/{result.cxf_filename}"
        cibf_key = f"cts/ngch/{bank_id}/{lot_number}/{result.cibf_filename}"

        self._upload(cxf_key, result.cxf_bytes, content_type="application/xml")
        self._upload(cibf_key, result.cibf_bytes, content_type="application/octet-stream")

        checksum = hashlib.sha256(result.cxf_bytes).hexdigest()

        log.info(
            "lot_store.ngch_file_built",
            lot_number=lot_number,
            bank_id=bank_id,
            instrument_count=result.instrument_count,
            cxf_key=cxf_key,
            cibf_key=cibf_key,
            checksum_prefix=checksum[:8],
        )
        return cxf_key, checksum

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Endorsement support (called from stamp_endorsement activity)
    # ------------------------------------------------------------------

    async def fetch_instrument_images(self, lot_number: str, bank_id: str) -> List[tuple]:
        """[(instrument_id, account_last4, front_bytes, rear_bytes)] for every instrument in the lot."""
        import asyncio
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT instrument_id::text AS instrument_id, account_last4, image_front_bw_key, image_back_bw_key "
                "FROM cts.cheque_instruments WHERE lot_id = $1 AND bank_id = $2 AND direction = 'OUTWARD' "
                "ORDER BY received_at LIMIT 100",
                lot_number, bank_id,
            )
        out = []
        for r in rows:
            front = await asyncio.to_thread(self._fetch_image, r["image_front_bw_key"])
            rear = await asyncio.to_thread(self._fetch_image, r["image_back_bw_key"])
            out.append((r["instrument_id"], r["account_last4"], front, rear))
        return out

    async def store_endorsed_rear(self, bank_id: str, instrument_id: str, data: bytes) -> str:
        """Upload the stamped rear image and record its key on the instrument row."""
        import asyncio
        key = f"{bank_id}/outward/endorsed/{instrument_id}/back_endorsed.tiff"
        await asyncio.to_thread(self._upload, key, data, "image/tiff")
        async with self._db.acquire() as conn:
            await conn.execute(
                "UPDATE cts.cheque_instruments SET image_back_endorsed_key = $1 "
                "WHERE instrument_id = $2::uuid AND bank_id = $3",
                key, instrument_id, bank_id,
            )
        return key

    async def endorsement_context(self, bank_id: str, lot_number: str) -> dict:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT b.bank_name AS bank_name, COALESCE(br.branch_name, '') AS branch_name "
                "FROM platform.banks b "
                "LEFT JOIN cts.lots l ON l.lot_id = $2 AND l.bank_id = b.bank_id "
                "LEFT JOIN cts.branches br ON br.branch_id = l.branch_id "
                "WHERE b.bank_id = $1",
                bank_id, lot_number,
            )
        if row is None:
            raise ValueError(f"bank {bank_id} not found in platform.banks")
        return {"bank_name": row["bank_name"], "branch_name": row["branch_name"]}

    async def _fetch_lot_instruments(self, bank_id: str, lot_number: str) -> List[dict]:
        """
        Fetches all CHI Spec Rev 3.00 fields needed by InstrumentBuildInput, for every instrument in this lot.

        Historical bug (found live): this used to look up instrument_ids from cts.outward_scan_events (which
        carries the scan's own text id, e.g. "058475-fc7a") and then query cheque_instruments by
        `instrument_id = ANY(those ids)` — but cheque_instruments.instrument_id is a UUID column
        (persist_outward_instrument.py maps the scan id through to_instrument_uuid), so the query raised
        "invalid UUID" the moment a real lot reached this path. cheque_instruments already carries its own
        lot_id (added alongside that mapping), so this queries it directly — one lookup, no id translation.

        Columns: standard cts.cheque_instruments fields plus the extended columns added for CHI Spec
        compliance (payor_bank_rout_no, presenting_bank_rout_no, trans_code, doc_type, image MinIO keys,
        image dimensions).
        """
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    instrument_id::text AS instrument_id,
                    cheque_number,
                    micr_code,
                    drawee_ifsc,
                    presenting_ifsc,
                    presenting_bank_rout_no,
                    payor_bank_rout_no,
                    trans_code,
                    doc_type,
                    amount_paise,
                    cheque_date::TEXT AS cheque_date,
                    account_last4,
                    image_front_bw_key,
                    image_back_bw_key,
                    image_front_gray_key,
                    width_px,
                    height_px,
                    dpi,
                    bit_depth,
                    cycle_no
                FROM cts.cheque_instruments
                WHERE lot_id = $1
                  AND bank_id = $2
                  AND direction = 'OUTWARD'
                ORDER BY received_at
                """,
                lot_number,
                bank_id,
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Instrument input builder
    # ------------------------------------------------------------------

    def _build_instrument_inputs(
        self,
        rows: List[dict],
        date_ddmmyyyy: str,
        lot_number: str,
    ):
        """Convert DB rows + MinIO image bytes → List[InstrumentBuildInput]."""
        from modules.cts.workflows.activities.build_ngch_file import InstrumentBuildInput

        inputs = []
        for seq, row in enumerate(rows, start=1):
            front_bw = self._fetch_image(row["image_front_bw_key"])
            back_bw = self._fetch_image(row["image_back_bw_key"])
            front_gray = self._fetch_image(row["image_front_gray_key"])

            inputs.append(InstrumentBuildInput(
                item_seq_no=str(seq).zfill(14),
                payor_bank_rout_no=row.get("payor_bank_rout_no") or row["micr_code"][:9],
                account_no=f"****{row['account_last4']}",
                serial_no=row["cheque_number"],
                trans_code=row.get("trans_code") or "01",
                doc_type=row.get("doc_type") or "01",
                micr_line=row["micr_code"],
                drawee_ifsc=row["drawee_ifsc"],
                amount_paise=row["amount_paise"],
                front_bw_bytes=front_bw,
                back_bw_bytes=back_bw,
                front_gray_bytes=front_gray,
                width_px=row.get("width_px") or 1728,
                height_px=row.get("height_px") or 816,
                dpi=row.get("dpi") or 200,
                bit_depth=row.get("bit_depth") or 1,
                presenting_bank_rout_no=row.get("presenting_bank_rout_no") or "",
                cycle_no=row.get("cycle_no") or "AM",
                presentment_date=date_ddmmyyyy,
                batch_id=lot_number,
            ))
        return inputs

    # ------------------------------------------------------------------
    # MinIO helpers
    # ------------------------------------------------------------------

    def _fetch_image(self, object_key: str) -> bytes:
        """Fetch image bytes from MinIO by object key."""
        bucket, key = self._bucket, object_key
        if object_key.startswith("s3://"):
            bucket, _, key = object_key[len("s3://"):].partition("/")
        response = self._minio.get_object(bucket, key)
        return response.read()

    def _upload(self, object_key: str, data: bytes, content_type: str = "application/xml") -> None:
        self._minio.put_object(
            self._bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def _upload_empty_lot(
        self,
        lot_number: str,
        bank_id: str,
        bank_ifsc: str,
        clearing_date: str,
    ) -> tuple[str, str]:
        """Build a minimal stub CXF for an empty lot and upload it."""
        root = ET.Element("CXF", {"version": "2.0"})
        header = ET.SubElement(root, "BatchHeader")
        ET.SubElement(header, "InstitutionCode").text = bank_ifsc
        ET.SubElement(header, "BatchNumber").text = lot_number
        ET.SubElement(header, "BatchDate").text = clearing_date
        ET.SubElement(header, "ItemCount").text = "0"
        ET.SubElement(root, "Items")

        buf = io.BytesIO()
        ET.ElementTree(root).write(buf, encoding="utf-8", xml_declaration=True)
        xml_bytes = buf.getvalue()

        checksum = hashlib.sha256(xml_bytes).hexdigest()
        object_key = f"cts/ngch/{bank_id}/{lot_number}/ngch_file.xml"
        self._upload(object_key, xml_bytes)

        log.info(
            "lot_store.ngch_file_built_empty",
            lot_number=lot_number,
            bank_id=bank_id,
            object_key=object_key,
        )
        return object_key, checksum
