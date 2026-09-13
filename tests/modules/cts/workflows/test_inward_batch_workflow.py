"""
Tests for InwardBatchIngestionWorkflow + inward_batch_activities.

The workflow receives notification that an inward batch (PXF + CXF + CIBF)
has been deposited to MinIO by the NGCH adapter. It:
  1. Downloads PXF, CXF, and CIBF from MinIO
  2. Parses PXF (IET deadlines + PPS flags) and CXF (instrument metadata + byte offsets)
  3. Parses CIBF to extract per-instrument images using CXF byte offsets
  4. Uploads each instrument's images to MinIO (individual keys)
  5. Starts one ChequeProcessingWorkflow per instrument (fan-out, parallel)
  6. Returns InwardBatchResult (instruments_started, failure_count)

IET safety rule: IET deadline per instrument comes from PXF, NOT from config.
Each ChequeProcessingWorkflow receives the per-instrument iet_deadline from PXF.

RED phase: tests must fail before implementation exists.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


# ── Input / Result model tests ───────────────────────────────────────────────

class TestInwardBatchInput:
    def test_input_model_importable(self):
        from modules.cts.workflows.inward_batch_workflow import InwardBatchInput
        assert InwardBatchInput is not None

    def test_input_is_frozen(self):
        from modules.cts.workflows.inward_batch_workflow import InwardBatchInput
        inp = InwardBatchInput(
            batch_id="BCH0001",
            bank_id="saraswat",
            session_id="SES0001",
            clearing_date="2026-09-13",
            pxf_minio_key="cts/inward/saraswat/SES0001/pxf.xml",
            cxf_minio_key="cts/inward/saraswat/SES0001/cxf.xml",
            cibf_minio_key="cts/inward/saraswat/SES0001/cibf.img",
        )
        with pytest.raises(Exception):
            inp.batch_id = "changed"

    def test_input_has_required_fields(self):
        from modules.cts.workflows.inward_batch_workflow import InwardBatchInput
        inp = InwardBatchInput(
            batch_id="BCH0001",
            bank_id="saraswat",
            session_id="SES0001",
            clearing_date="2026-09-13",
            pxf_minio_key="cts/inward/saraswat/SES0001/pxf.xml",
            cxf_minio_key="cts/inward/saraswat/SES0001/cxf.xml",
            cibf_minio_key="cts/inward/saraswat/SES0001/cibf.img",
        )
        assert inp.batch_id == "BCH0001"
        assert inp.bank_id == "saraswat"
        assert inp.session_id == "SES0001"


class TestInwardBatchResult:
    def test_result_model_importable(self):
        from modules.cts.workflows.inward_batch_workflow import InwardBatchResult
        assert InwardBatchResult is not None

    def test_result_is_frozen(self):
        from modules.cts.workflows.inward_batch_workflow import InwardBatchResult
        r = InwardBatchResult(
            batch_id="BCH0001",
            bank_id="saraswat",
            instruments_started=5,
            failure_count=0,
        )
        with pytest.raises(Exception):
            r.instruments_started = 999

    def test_result_has_instruments_started(self):
        from modules.cts.workflows.inward_batch_workflow import InwardBatchResult
        r = InwardBatchResult(
            batch_id="BCH0001",
            bank_id="saraswat",
            instruments_started=42,
            failure_count=0,
        )
        assert r.instruments_started == 42


# ── Temporal decorator tests ─────────────────────────────────────────────────

class TestInwardBatchWorkflowTemporal:
    def test_workflow_defn_decorator_present(self):
        from modules.cts.workflows.inward_batch_workflow import InwardBatchIngestionWorkflow
        assert hasattr(InwardBatchIngestionWorkflow, "__temporal_workflow_definition")

    def test_run_method_exists(self):
        from modules.cts.workflows.inward_batch_workflow import InwardBatchIngestionWorkflow
        assert callable(getattr(InwardBatchIngestionWorkflow, "run", None))

    def test_workflow_id_format(self):
        from modules.cts.workflows.inward_batch_workflow import InwardBatchIngestionWorkflow
        wf = InwardBatchIngestionWorkflow()
        wid = wf.workflow_id("saraswat", "BCH0001")
        assert "saraswat" in wid
        assert "BCH0001" in wid

    def test_workflow_id_deterministic(self):
        from modules.cts.workflows.inward_batch_workflow import InwardBatchIngestionWorkflow
        wf = InwardBatchIngestionWorkflow()
        assert wf.workflow_id("bank-a", "BCH-1") == wf.workflow_id("bank-a", "BCH-1")

    def test_workflow_id_unique_per_batch(self):
        from modules.cts.workflows.inward_batch_workflow import InwardBatchIngestionWorkflow
        wf = InwardBatchIngestionWorkflow()
        assert wf.workflow_id("bank-a", "BCH-1") != wf.workflow_id("bank-a", "BCH-2")


# ── Activity: parse_inward_batch ──────────────────────────────────────────────

class TestParseInwardBatchActivity:
    def test_activity_importable(self):
        from modules.cts.workflows.activities.inward_batch_activities import (
            parse_inward_batch,
        )
        assert callable(parse_inward_batch)

    def test_activity_defn_decorator_present(self):
        from modules.cts.workflows.activities.inward_batch_activities import (
            parse_inward_batch,
        )
        assert hasattr(parse_inward_batch, "__temporal_activity_definition")

    def test_parse_input_model_importable(self):
        from modules.cts.workflows.activities.inward_batch_activities import (
            ParseInwardBatchInput,
        )
        assert ParseInwardBatchInput is not None

    @pytest.mark.asyncio
    async def test_no_minio_returns_empty(self):
        from modules.cts.workflows.activities.inward_batch_activities import (
            ParseInwardBatchInput,
            parse_inward_batch,
        )
        inp = ParseInwardBatchInput(
            batch_id="BCH0001",
            bank_id="saraswat",
            session_id="SES0001",
            pxf_minio_key="cts/inward/saraswat/SES0001/pxf.xml",
            cxf_minio_key="cts/inward/saraswat/SES0001/cxf.xml",
            cibf_minio_key="cts/inward/saraswat/SES0001/cibf.img",
            minio_bucket="cts-files",
        )
        result = await parse_inward_batch(inp, minio_client=None)
        assert result.instrument_count == 0
        assert result.parse_error is not None

    def test_parse_result_model_importable(self):
        from modules.cts.workflows.activities.inward_batch_activities import (
            ParseInwardBatchResult,
        )
        assert ParseInwardBatchResult is not None


# ── Activity: upload_instrument_images ────────────────────────────────────────

class TestUploadInstrumentImagesActivity:
    def test_activity_importable(self):
        from modules.cts.workflows.activities.inward_batch_activities import (
            upload_instrument_images,
        )
        assert callable(upload_instrument_images)

    def test_activity_defn_decorator_present(self):
        from modules.cts.workflows.activities.inward_batch_activities import (
            upload_instrument_images,
        )
        assert hasattr(upload_instrument_images, "__temporal_activity_definition")

    def test_input_uses_cibf_staging_key_not_raw_bytes(self):
        """Input must carry cibf_staging_key + offsets — raw image bytes must not be in input."""
        from modules.cts.workflows.activities.inward_batch_activities import (
            UploadInstrumentImagesInput,
        )
        import inspect
        fields = inspect.signature(UploadInstrumentImagesInput).parameters
        assert "cibf_staging_key" in fields, "Input must have cibf_staging_key field"
        assert "front_bw_image_offset" in fields
        assert "front_bw_image_length" in fields
        assert "back_bw_image_offset" in fields
        assert "back_bw_image_length" in fields
        assert "front_gray_image_offset" in fields
        assert "front_gray_image_length" in fields
        assert "front_bw_bytes" not in fields, \
            "Raw bytes must not be in input — they bloat Temporal history"

    @pytest.mark.asyncio
    async def test_no_minio_returns_failure(self):
        from modules.cts.workflows.activities.inward_batch_activities import (
            UploadInstrumentImagesInput,
            upload_instrument_images,
        )
        inp = UploadInstrumentImagesInput(
            bank_id="saraswat",
            batch_id="BCH0001",
            item_seq_no="00055005000001",
            cibf_staging_key="cts/inward/saraswat/SES001/staging/BCH0001_cibf.img",
            front_bw_image_offset=256,  front_bw_image_length=8860,
            back_bw_image_offset=9372,  back_bw_image_length=1122,
            front_gray_image_offset=10750, front_gray_image_length=8860,
            minio_bucket="cts-files",
        )
        result = await upload_instrument_images(inp, minio_client=None)
        assert result.uploaded is False

    @pytest.mark.asyncio
    async def test_activity_slices_cibf_and_uploads_correct_bytes(self):
        """Activity must download CIBF, slice at given offsets, upload each view."""
        import io
        from unittest.mock import call
        from modules.cts.workflows.activities.inward_batch_activities import (
            UploadInstrumentImagesInput,
            upload_instrument_images,
        )
        # Build a fake CIBF: 3 distinct regions
        front_bw  = b"\x49\x49\x2a\x00" + b"\xAA" * 100  # 104 bytes at offset 0
        back_bw   = b"\x49\x49\x2a\x00" + b"\xBB" * 80   # 84 bytes at offset 256
        front_gray = b"\xFF\xD8\xFF\xe0" + b"\xCC" * 200  # 204 bytes at offset 512
        cibf = (b"\x00" * 256 + front_bw   # DS then front_bw at 256
              + b"\x00" * 256 + back_bw    # DS then back_bw at 256+104+256=616
              + b"\x00" * 256 + front_gray)

        captured_uploads = {}
        def fake_put(bucket_name, object_name, data, length, content_type):
            captured_uploads[object_name] = data.read()

        mock_minio = MagicMock()
        mock_minio.put_object.side_effect = fake_put

        # CIBF returned on get_object
        mock_resp = MagicMock()
        mock_resp.read.return_value = cibf
        mock_resp.close = MagicMock()
        mock_resp.release_conn = MagicMock()
        mock_minio.get_object.return_value = mock_resp

        inp = UploadInstrumentImagesInput(
            bank_id="saraswat",
            batch_id="BCH0001",
            item_seq_no="00055005000001",
            cibf_staging_key="cts/inward/saraswat/SES001/staging/BCH0001_cibf.img",
            front_bw_image_offset=256,  front_bw_image_length=len(front_bw),
            back_bw_image_offset=256 + len(front_bw) + 256,
            back_bw_image_length=len(back_bw),
            front_gray_image_offset=256 + len(front_bw) + 256 + len(back_bw) + 256,
            front_gray_image_length=len(front_gray),
            minio_bucket="cts-files",
        )
        result = await upload_instrument_images(inp, minio_client=mock_minio)

        assert result.uploaded is True
        assert result.front_bw_key and "saraswat" in result.front_bw_key
        assert result.back_bw_key
        assert result.front_gray_key

        # Verify the CIBF was downloaded once
        mock_minio.get_object.assert_called_once()

        # Verify the correct bytes were uploaded for each view
        front_bw_uploaded  = captured_uploads.get(result.front_bw_key)
        back_bw_uploaded   = captured_uploads.get(result.back_bw_key)
        front_gray_uploaded = captured_uploads.get(result.front_gray_key)
        assert front_bw_uploaded == front_bw,  "Front BW bytes don't match CIBF slice"
        assert back_bw_uploaded == back_bw,    "Back BW bytes don't match CIBF slice"
        assert front_gray_uploaded == front_gray, "Front Gray bytes don't match CIBF slice"

    @pytest.mark.asyncio
    async def test_upload_result_carries_iet_deadline(self):
        from modules.cts.workflows.activities.inward_batch_activities import (
            UploadInstrumentImagesInput, upload_instrument_images,
        )
        cibf = b"\x00" * 512 + b"\x49\x49\x2a\x00" * 50
        mock_resp = MagicMock()
        mock_resp.read.return_value = cibf
        mock_resp.close = MagicMock()
        mock_resp.release_conn = MagicMock()
        mock_minio = MagicMock()
        mock_minio.get_object.return_value = mock_resp

        inp = UploadInstrumentImagesInput(
            bank_id="saraswat",
            batch_id="BCH0001",
            item_seq_no="00055005000001",
            cibf_staging_key="cts/inward/saraswat/SES001/staging/BCH0001_cibf.img",
            front_bw_image_offset=0,   front_bw_image_length=100,
            back_bw_image_offset=100,  back_bw_image_length=100,
            front_gray_image_offset=200, front_gray_image_length=100,
            minio_bucket="cts-files",
            iet_deadline=9_999_999_999.0,
        )
        result = await upload_instrument_images(inp, minio_client=mock_minio)
        assert result.iet_deadline == 9_999_999_999.0


# ── Workflow CIBF staging key wiring ─────────────────────────────────────────

class TestWorkflowCIBFWiring:
    """Verify workflow passes cibf_staging_key and offsets to upload activity."""

    def _src(self):
        import inspect
        import modules.cts.workflows.inward_batch_workflow as wf_mod
        return inspect.getsource(wf_mod)

    def test_workflow_passes_cibf_staging_key(self):
        src = self._src()
        assert "cibf_staging_key" in src, \
            "Workflow must pass cibf_staging_key from parse_result to upload activity"

    def test_workflow_passes_image_offsets(self):
        src = self._src()
        assert "front_bw_image_offset" in src
        assert "front_bw_image_length" in src

    def test_workflow_does_not_pass_raw_bytes(self):
        src = self._src()
        assert 'front_bw_bytes=b""' not in src, \
            "Workflow must not pass empty raw bytes to upload activity"


# ── Audit event registration ──────────────────────────────────────────────────

class TestInwardBatchAuditEvents:
    def test_batch_ingested_event_registered(self):
        from modules.cts.workflows.activities.write_audit import _VALID_EVENT_TYPES
        assert "CTS_IN_BATCH_INGESTED" in _VALID_EVENT_TYPES

    def test_batch_ingest_failed_event_registered(self):
        from modules.cts.workflows.activities.write_audit import _VALID_EVENT_TYPES
        assert "CTS_IN_BATCH_INGEST_FAILED" in _VALID_EVENT_TYPES


# ── IET safety ───────────────────────────────────────────────────────────────

class TestInwardBatchIETSafety:
    def test_iet_deadline_field_in_upload_result(self):
        """UploadInstrumentImagesResult must carry iet_deadline from PXF."""
        from modules.cts.workflows.activities.inward_batch_activities import (
            UploadInstrumentImagesResult,
        )
        r = UploadInstrumentImagesResult(
            item_seq_no="00055005000001",
            uploaded=True,
            front_bw_key="k1",
            back_bw_key="k2",
            front_gray_key="k3",
            iet_deadline=9999999999.0,
        )
        assert r.iet_deadline == 9999999999.0

    def test_parse_result_carries_per_item_iet(self):
        """ParseInwardBatchResult.items must be iterable with iet_deadline per item."""
        from modules.cts.workflows.activities.inward_batch_activities import (
            ParsedBatchItem,
        )
        item = ParsedBatchItem(
            item_seq_no="00055005000001",
            iet_deadline=9999999999.0,
            pps_flag="P",
            micr_line="000042510123456789",
            drawee_ifsc="SBIN0000001",
            drawee_account="SB12345678",
            amount_paise=10000000,
            front_bw_ds_offset=0,
            front_bw_image_offset=256,
            front_bw_image_length=50000,
            back_bw_ds_offset=50256,
            back_bw_image_offset=50512,
            back_bw_image_length=45000,
            front_gray_ds_offset=95512,
            front_gray_image_offset=95768,
            front_gray_image_length=120000,
        )
        assert item.iet_deadline == 9999999999.0
        assert item.pps_flag == "P"


# ── Workflow audit wiring ─────────────────────────────────────────────────────

class TestInwardBatchWorkflowAuditWiring:
    """Verify InwardBatchIngestionWorkflow calls write_audit for both outcomes."""

    def _src(self):
        import inspect
        import modules.cts.workflows.inward_batch_workflow as wf_mod
        return inspect.getsource(wf_mod)

    def test_workflow_imports_write_audit(self):
        src = self._src()
        assert "write_audit" in src, \
            "InwardBatchIngestionWorkflow must import write_audit"

    def test_workflow_imports_write_audit_input(self):
        src = self._src()
        assert "WriteAuditInput" in src, \
            "InwardBatchIngestionWorkflow must import WriteAuditInput"

    def test_workflow_audits_batch_ingested_on_success(self):
        src = self._src()
        assert "CTS_IN_BATCH_INGESTED" in src, \
            "Workflow must write CTS_IN_BATCH_INGESTED audit on successful batch completion"

    def test_workflow_audits_batch_ingest_failed_on_parse_error(self):
        src = self._src()
        assert "CTS_IN_BATCH_INGEST_FAILED" in src, \
            "Workflow must write CTS_IN_BATCH_INGEST_FAILED audit when parse fails"

    def test_audit_payload_includes_instrument_count(self):
        src = self._src()
        assert "instruments_started" in src, \
            "Audit payload must include instruments_started count"

    def test_audit_payload_includes_session_id(self):
        src = self._src()
        assert "session_id" in src, \
            "Audit payload must include session_id for RBI traceability"

    def test_audit_uses_unlimited_retry(self):
        """Audit write must use unlimited retry (_AUDIT_RETRY) — same as outward workflow."""
        src = self._src()
        assert "_AUDIT_RETRY" in src, \
            "Audit write must use _AUDIT_RETRY (maximum_attempts=0 = unlimited)"
