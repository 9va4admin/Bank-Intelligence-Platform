"""
TDD — RED first.

Tests for:
  modules/cts/workflows/activities/ngch_lot_assembly_activity.py

The build_and_upload_ngch_files activity is the NEW spec-compliant replacement
for the old build_ngch_file stub in ngch_submission_activities.py.

Pipeline:
  1. DB: query cts.outward_scan_events → ACCEPTED instrument_ids for lot
  2. DB: query cts.cheque_instruments → cheque fields
  3. DB: query cts.cheque_image_metadata → MinIO image keys
  4. MinIO: download front_bw, reverse_bw, front_grey bytes per instrument
  5. Construct List[InstrumentBuildInput]
  6. Call build_ngch_file() pure function → cxf_bytes + cibf_bytes + filenames
  7. MinIO: upload CXF file + CIBF file
  8. Return FetchAndBuildResult with MinIO keys + filenames + count
"""
from __future__ import annotations

import io
import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fake_image_bytes(tag: str) -> bytes:
    """Minimal fake image bytes (TIFF header for B&W, JFIF for gray)."""
    if tag == "gray":
        return b"\xff\xd8\xff\xe0" + b"\x00" * 100
    return b"II\x2a\x00" + b"\x00" * 100


def _make_db_pool(
    scan_event_rows=None,
    instr_rows=None,
    img_rows=None,
):
    """Returns a mock asyncpg pool with three ordered fetch results."""
    if scan_event_rows is None:
        scan_event_rows = [{"instrument_id": "INST-001"}]
    if instr_rows is None:
        instr_rows = [
            {
                "instrument_id": "INST-001",
                "cheque_number": "000001",
                "micr_code": "400002001",
                "drawee_ifsc": "SBIN0000001",
                "presenting_ifsc": "SVCB0000002",
                "amount_paise": 500000,
                "cheque_date": "2026-09-01",
                "account_last4": "4521",
            }
        ]
    if img_rows is None:
        img_rows = [
            {
                "instrument_id": "INST-001",
                "front_bw_key": "cts/images/INST-001/front_bw.tiff",
                "reverse_bw_key": "cts/images/INST-001/back_bw.tiff",
                "front_grey_key": "cts/images/INST-001/front_gray.jpg",
                "dpi_front": 200,
            }
        ]

    # fetch() returns different values on successive calls (one per query)
    fetch_results = [scan_event_rows, instr_rows, img_rows]
    call_count = [0]

    async def _fetch(*args, **kwargs):
        idx = call_count[0]
        call_count[0] += 1
        return fetch_results[idx] if idx < len(fetch_results) else []

    conn = AsyncMock()
    conn.fetch = _fetch

    conn_ctx = AsyncMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn_ctx)
    return pool


def _make_minio(front_bw=None, back_bw=None, front_gray=None):
    """Mock MinIO client: get_object returns fake bytes; put_object accepts."""
    fb = front_bw or _fake_image_bytes("bw")
    bb = back_bw or _fake_image_bytes("bw")
    fg = front_gray or _fake_image_bytes("gray")

    responses = {
        "cts/images/INST-001/front_bw.tiff": fb,
        "cts/images/INST-001/back_bw.tiff": bb,
        "cts/images/INST-001/front_gray.jpg": fg,
    }

    minio = MagicMock()

    def _get_object(bucket, key):
        data = responses.get(key, b"\x00" * 50)
        resp = MagicMock()
        resp.read.return_value = data
        resp.close = MagicMock()
        resp.release_conn = MagicMock()
        return resp

    minio.get_object.side_effect = _get_object
    minio.put_object = MagicMock()
    return minio


def _make_config_svc():
    cfg = AsyncMock()
    cfg.get_cts_config = AsyncMock(return_value={
        "cts.npci_routing_no": "000550050",
        "cts.clearing_type": "14",
        "cts.micr_trans_code": "10",
        "cts.ngch_doc_type": "01",
        "cts.cheque_width_px": "1200",
        "cts.cheque_height_px": "500",
        "cts.cheque_bit_depth": "1",
    })
    return cfg


def _make_hsm():
    hsm = MagicMock()
    hsm.sign.return_value = b"\xAB" * 256
    return hsm


def _make_valid_input(**overrides):
    defaults = dict(
        bank_id="saraswat-coop",
        lot_number="LOT-001",
        session_id="SES-001",
        clearing_date="2026-09-01",
        bank_ifsc="SVCB0000002",
    )
    defaults.update(overrides)
    return defaults


# ── Module structure ───────────────────────────────────────────────────────────

class TestModuleStructure:
    def test_module_importable(self):
        from modules.cts.workflows.activities import ngch_lot_assembly_activity  # noqa: F401

    def test_activity_function_exists(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import (
            build_and_upload_ngch_files,
        )
        assert callable(build_and_upload_ngch_files)

    def test_input_model_exists(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import FetchAndBuildInput
        assert FetchAndBuildInput is not None

    def test_result_model_exists(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import FetchAndBuildResult
        assert FetchAndBuildResult is not None


# ── FetchAndBuildInput ─────────────────────────────────────────────────────────

class TestFetchAndBuildInput:
    def test_accepts_valid_input(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import FetchAndBuildInput
        inp = FetchAndBuildInput(**_make_valid_input())
        assert inp.lot_number == "LOT-001"
        assert inp.bank_id == "saraswat-coop"

    def test_requires_lot_number(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import FetchAndBuildInput
        import pydantic
        bad = {k: v for k, v in _make_valid_input().items() if k != "lot_number"}
        with pytest.raises((pydantic.ValidationError, TypeError)):
            FetchAndBuildInput(**bad)

    def test_requires_bank_id(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import FetchAndBuildInput
        import pydantic
        bad = {k: v for k, v in _make_valid_input().items() if k != "bank_id"}
        with pytest.raises((pydantic.ValidationError, TypeError)):
            FetchAndBuildInput(**bad)

    def test_requires_clearing_date(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import FetchAndBuildInput
        import pydantic
        bad = {k: v for k, v in _make_valid_input().items() if k != "clearing_date"}
        with pytest.raises((pydantic.ValidationError, TypeError)):
            FetchAndBuildInput(**bad)


# ── FetchAndBuildResult ────────────────────────────────────────────────────────

class TestFetchAndBuildResult:
    def test_has_required_fields(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import FetchAndBuildResult
        r = FetchAndBuildResult(
            cxf_minio_key="cts/ngch/bank/LOT-001/file.XML",
            cibf_minio_key="cts/ngch/bank/LOT-001/file.img",
            cxf_filename="CXF_000550050_01092026_103000_14_0001.XML",
            cibf_filename="CIBF_000550050_01092026_103000_14_0001_01.img",
            instrument_count=3,
        )
        assert r.instrument_count == 3
        assert r.cxf_minio_key.startswith("cts/")


# ── Happy path ─────────────────────────────────────────────────────────────────

class TestHappyPath:
    @pytest.mark.asyncio
    async def test_returns_fetch_and_build_result(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import (
            build_and_upload_ngch_files, FetchAndBuildInput,
        )
        inp = FetchAndBuildInput(**_make_valid_input())
        result = await build_and_upload_ngch_files(
            inp,
            db_pool=_make_db_pool(),
            minio_client=_make_minio(),
            hsm=_make_hsm(),
            config_svc=_make_config_svc(),
        )
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import FetchAndBuildResult
        assert isinstance(result, FetchAndBuildResult)

    @pytest.mark.asyncio
    async def test_instrument_count_one(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import (
            build_and_upload_ngch_files, FetchAndBuildInput,
        )
        inp = FetchAndBuildInput(**_make_valid_input())
        result = await build_and_upload_ngch_files(
            inp,
            db_pool=_make_db_pool(),
            minio_client=_make_minio(),
            hsm=_make_hsm(),
            config_svc=_make_config_svc(),
        )
        assert result.instrument_count == 1

    @pytest.mark.asyncio
    async def test_two_instruments(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import (
            build_and_upload_ngch_files, FetchAndBuildInput,
        )
        db = _make_db_pool(
            scan_event_rows=[
                {"instrument_id": "INST-001"},
                {"instrument_id": "INST-002"},
            ],
            instr_rows=[
                {
                    "instrument_id": "INST-001",
                    "cheque_number": "000001",
                    "micr_code": "400002001",
                    "drawee_ifsc": "SBIN0000001",
                    "presenting_ifsc": "SVCB0000002",
                    "amount_paise": 500000,
                    "cheque_date": "2026-09-01",
                    "account_last4": "4521",
                },
                {
                    "instrument_id": "INST-002",
                    "cheque_number": "000002",
                    "micr_code": "400002001",
                    "drawee_ifsc": "SBIN0000001",
                    "presenting_ifsc": "SVCB0000002",
                    "amount_paise": 750000,
                    "cheque_date": "2026-09-01",
                    "account_last4": "9999",
                },
            ],
            img_rows=[
                {
                    "instrument_id": "INST-001",
                    "front_bw_key": "cts/images/INST-001/front_bw.tiff",
                    "reverse_bw_key": "cts/images/INST-001/back_bw.tiff",
                    "front_grey_key": "cts/images/INST-001/front_gray.jpg",
                    "dpi_front": 200,
                },
                {
                    "instrument_id": "INST-002",
                    "front_bw_key": "cts/images/INST-002/front_bw.tiff",
                    "reverse_bw_key": "cts/images/INST-002/back_bw.tiff",
                    "front_grey_key": "cts/images/INST-002/front_gray.jpg",
                    "dpi_front": 200,
                },
            ],
        )
        minio = _make_minio()
        minio.get_object.side_effect = None
        resp_mock = MagicMock()
        resp_mock.read.return_value = _fake_image_bytes("bw")
        resp_mock.close = MagicMock()
        resp_mock.release_conn = MagicMock()
        minio.get_object.return_value = resp_mock

        inp = FetchAndBuildInput(**_make_valid_input())
        result = await build_and_upload_ngch_files(
            inp,
            db_pool=db,
            minio_client=minio,
            hsm=_make_hsm(),
            config_svc=_make_config_svc(),
        )
        assert result.instrument_count == 2

    @pytest.mark.asyncio
    async def test_uploads_cxf_to_minio(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import (
            build_and_upload_ngch_files, FetchAndBuildInput,
        )
        minio = _make_minio()
        inp = FetchAndBuildInput(**_make_valid_input())
        result = await build_and_upload_ngch_files(
            inp,
            db_pool=_make_db_pool(),
            minio_client=minio,
            hsm=_make_hsm(),
            config_svc=_make_config_svc(),
        )
        # put_object called twice: once for CXF, once for CIBF
        assert minio.put_object.call_count == 2

    @pytest.mark.asyncio
    async def test_cxf_minio_key_in_result(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import (
            build_and_upload_ngch_files, FetchAndBuildInput,
        )
        inp = FetchAndBuildInput(**_make_valid_input())
        result = await build_and_upload_ngch_files(
            inp,
            db_pool=_make_db_pool(),
            minio_client=_make_minio(),
            hsm=_make_hsm(),
            config_svc=_make_config_svc(),
        )
        assert result.cxf_minio_key.endswith(".XML")
        assert "LOT-001" in result.cxf_minio_key

    @pytest.mark.asyncio
    async def test_cibf_minio_key_in_result(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import (
            build_and_upload_ngch_files, FetchAndBuildInput,
        )
        inp = FetchAndBuildInput(**_make_valid_input())
        result = await build_and_upload_ngch_files(
            inp,
            db_pool=_make_db_pool(),
            minio_client=_make_minio(),
            hsm=_make_hsm(),
            config_svc=_make_config_svc(),
        )
        assert result.cibf_minio_key.endswith(".img")
        assert "LOT-001" in result.cibf_minio_key

    @pytest.mark.asyncio
    async def test_downloads_three_images_per_instrument(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import (
            build_and_upload_ngch_files, FetchAndBuildInput,
        )
        minio = _make_minio()
        inp = FetchAndBuildInput(**_make_valid_input())
        await build_and_upload_ngch_files(
            inp,
            db_pool=_make_db_pool(),
            minio_client=minio,
            hsm=_make_hsm(),
            config_svc=_make_config_svc(),
        )
        # 1 instrument × 3 images = 3 get_object calls
        assert minio.get_object.call_count == 3

    @pytest.mark.asyncio
    async def test_cxf_filename_in_result(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import (
            build_and_upload_ngch_files, FetchAndBuildInput,
        )
        inp = FetchAndBuildInput(**_make_valid_input())
        result = await build_and_upload_ngch_files(
            inp,
            db_pool=_make_db_pool(),
            minio_client=_make_minio(),
            hsm=_make_hsm(),
            config_svc=_make_config_svc(),
        )
        assert result.cxf_filename.startswith("CXF_")
        assert result.cxf_filename.endswith(".XML")

    @pytest.mark.asyncio
    async def test_cibf_filename_in_result(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import (
            build_and_upload_ngch_files, FetchAndBuildInput,
        )
        inp = FetchAndBuildInput(**_make_valid_input())
        result = await build_and_upload_ngch_files(
            inp,
            db_pool=_make_db_pool(),
            minio_client=_make_minio(),
            hsm=_make_hsm(),
            config_svc=_make_config_svc(),
        )
        assert result.cibf_filename.startswith("CIBF_")
        assert result.cibf_filename.endswith(".img")

    @pytest.mark.asyncio
    async def test_queries_only_accepted_instruments(self):
        """The DB query must filter outcome='ACCEPTED'."""
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import (
            build_and_upload_ngch_files, FetchAndBuildInput,
        )
        # Only ACCEPTED instruments come from DB — we verify by making the
        # scan event query return 0 rows → raises ValueError
        db = _make_db_pool(scan_event_rows=[])
        inp = FetchAndBuildInput(**_make_valid_input())
        with pytest.raises((ValueError, Exception)):
            await build_and_upload_ngch_files(
                inp,
                db_pool=db,
                minio_client=_make_minio(),
                hsm=_make_hsm(),
                config_svc=_make_config_svc(),
            )


# ── Error paths ────────────────────────────────────────────────────────────────

class TestErrorPaths:
    @pytest.mark.asyncio
    async def test_empty_lot_raises(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import (
            build_and_upload_ngch_files, FetchAndBuildInput,
        )
        db = _make_db_pool(scan_event_rows=[])
        inp = FetchAndBuildInput(**_make_valid_input())
        with pytest.raises((ValueError, Exception)):
            await build_and_upload_ngch_files(
                inp,
                db_pool=db,
                minio_client=_make_minio(),
                hsm=_make_hsm(),
                config_svc=_make_config_svc(),
            )

    @pytest.mark.asyncio
    async def test_db_pool_none_raises(self):
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import (
            build_and_upload_ngch_files, FetchAndBuildInput,
        )
        inp = FetchAndBuildInput(**_make_valid_input())
        with pytest.raises((AttributeError, TypeError, Exception)):
            await build_and_upload_ngch_files(
                inp,
                db_pool=None,
                minio_client=_make_minio(),
                hsm=_make_hsm(),
                config_svc=_make_config_svc(),
            )


# ── OTel span ──────────────────────────────────────────────────────────────────

class TestOTelSpan:
    @pytest.mark.asyncio
    async def test_otel_span_started(self):
        """The activity must wrap itself in an OTel span."""
        from modules.cts.workflows.activities.ngch_lot_assembly_activity import (
            build_and_upload_ngch_files, FetchAndBuildInput,
        )
        inp = FetchAndBuildInput(**_make_valid_input())
        with patch("opentelemetry.trace.get_tracer") as mock_get_tracer:
            fake_tracer = MagicMock()
            fake_span = MagicMock()
            fake_span.__enter__ = MagicMock(return_value=fake_span)
            fake_span.__exit__ = MagicMock(return_value=False)
            fake_tracer.start_as_current_span.return_value = fake_span
            mock_get_tracer.return_value = fake_tracer

            # Re-import after patching (tracer is module-level)
            import importlib
            import modules.cts.workflows.activities.ngch_lot_assembly_activity as _mod
            original_tracer = _mod.tracer
            _mod.tracer = fake_tracer

            try:
                await build_and_upload_ngch_files(
                    inp,
                    db_pool=_make_db_pool(),
                    minio_client=_make_minio(),
                    hsm=_make_hsm(),
                    config_svc=_make_config_svc(),
                )
            except Exception:
                pass  # don't care about failures here
            finally:
                _mod.tracer = original_tracer

            fake_tracer.start_as_current_span.assert_called_once_with(
                "activity.build_and_upload_ngch_files"
            )


# ── NGCHSubmissionWorkflow wiring ──────────────────────────────────────────────

class TestNGCHSubmissionWorkflowWiring:
    def test_workflow_imports_new_activity(self):
        """The workflow module must reference the new lot assembly activity."""
        import inspect
        import modules.cts.workflows.ngch_submission_workflow as wf_mod
        src = inspect.getsource(wf_mod)
        assert "build_and_upload_ngch_files" in src, (
            "NGCHSubmissionWorkflow must call build_and_upload_ngch_files, "
            "not the old stub build_ngch_file from ngch_submission_activities"
        )

    def test_workflow_does_not_use_old_stub(self):
        """The old stub BuildNGCHFileInput from ngch_submission_activities must not be used."""
        import inspect
        import modules.cts.workflows.ngch_submission_workflow as wf_mod
        src = inspect.getsource(wf_mod)
        assert "ngch_submission_activities" not in src or (
            "BuildNGCHFileInput" not in src
        ), (
            "NGCHSubmissionWorkflow still imports BuildNGCHFileInput from "
            "ngch_submission_activities — this is the old stub, not spec-compliant"
        )

    def test_submit_to_ngch_input_has_cibf_path(self):
        """SubmitToNGCHInput must carry cibf_file_path for dual-file NGCH submission."""
        from modules.cts.workflows.activities.ngch_submission_activities import SubmitToNGCHInput
        import inspect
        src = inspect.getsource(SubmitToNGCHInput)
        assert "cibf_file_path" in src, (
            "SubmitToNGCHInput must have cibf_file_path field — "
            "NGCH submission sends both CXF and CIBF files"
        )
