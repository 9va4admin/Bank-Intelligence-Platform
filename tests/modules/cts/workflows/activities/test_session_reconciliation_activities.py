"""
generate_rrf real gap found reading the outward pipeline end to end: it built the RRF XML in
memory via RRFGenerator.to_xml() and then discarded it — only a DB metadata row was ever written,
pointing at a rrf_path that no file existed at. Fixed to actually upload the XML to MinIO before
recording the path.
"""
import pytest

from modules.cts.workflows.activities.session_reconciliation_activities import (
    generate_rrf, GenerateRRFInput,
)


class _FakeConn:
    def __init__(self):
        self.executed = []

    async def execute(self, query, *args):
        self.executed.append(args)


class _FakeAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakeDbPool:
    def __init__(self):
        self.conn = _FakeConn()

    def acquire(self):
        return _FakeAcquireCtx(self.conn)


class _FakeMinioClient:
    def __init__(self):
        self.uploads = []

    async def upload_bytes(self, bucket_name, object_key, data, content_type="application/octet-stream"):
        self.uploads.append((bucket_name, object_key, data, content_type))
        return object_key


_EXCEPTION_INSTRUMENTS = [
    {"instrument_id": "IW-1", "reason": "ACCOUNT_CLOSED", "micr_code": "400229001",
     "amount_range": "STANDARD"},
]


@pytest.mark.asyncio
async def test_generate_rrf_skips_when_no_exceptions():
    result = await generate_rrf(GenerateRRFInput(
        session_id="s1", bank_id="kbl", bank_ifsc="KARB0000001",
        clearing_date="2026-09-22", exception_instruments=[],
    ), db_pool=_FakeDbPool(), minio_client=_FakeMinioClient())
    assert result.generated is False


@pytest.mark.asyncio
async def test_generate_rrf_degrades_when_minio_unavailable():
    result = await generate_rrf(GenerateRRFInput(
        session_id="s1", bank_id="kbl", bank_ifsc="KARB0000001",
        clearing_date="2026-09-22", exception_instruments=_EXCEPTION_INSTRUMENTS,
    ), db_pool=_FakeDbPool(), minio_client=None)
    assert result.generated is False


@pytest.mark.asyncio
async def test_generate_rrf_degrades_when_db_unavailable():
    result = await generate_rrf(GenerateRRFInput(
        session_id="s1", bank_id="kbl", bank_ifsc="KARB0000001",
        clearing_date="2026-09-22", exception_instruments=_EXCEPTION_INSTRUMENTS,
    ), db_pool=None, minio_client=_FakeMinioClient())
    assert result.generated is False


@pytest.mark.asyncio
async def test_generate_rrf_uploads_xml_to_minio_before_recording_path():
    minio = _FakeMinioClient()
    db_pool = _FakeDbPool()
    result = await generate_rrf(GenerateRRFInput(
        session_id="s1", bank_id="kbl", bank_ifsc="KARB0000001",
        clearing_date="2026-09-22", exception_instruments=_EXCEPTION_INSTRUMENTS,
    ), db_pool=db_pool, minio_client=minio)

    assert result.generated is True
    assert result.rrf_path == "cts/kbl/2026-09-22/rrf/s1.xml"
    assert result.record_count == 1

    # The exact bytes generate_rrf claims to have written must actually be in MinIO.
    assert len(minio.uploads) == 1
    bucket, key, data, content_type = minio.uploads[0]
    assert bucket == "astra-cts"
    assert key == result.rrf_path
    assert content_type == "application/xml"
    assert b"<ReturnReasonFile" in data
    assert b"IW-1" in data

    # DB row recorded the same path the file actually lives at.
    assert len(db_pool.conn.executed) == 1
    assert result.rrf_path in db_pool.conn.executed[0]


@pytest.mark.asyncio
async def test_fetch_ngch_settlement_report_accepts_dict_input():
    """Real live bug found 2026-09-23: Temporal drops type hints on this hand-written
    bound-method activity (no generic bind_di_activity wrapper here), so inp can arrive
    as a plain dict -- accessing inp.bank_id then raised AttributeError in production."""
    from modules.cts.workflows.activities.session_reconciliation_activities import (
        fetch_ngch_settlement_report,
    )

    class _FakeNgchClient:
        async def fetch_settlement_report(self, session_id, clearing_date, bank_ifsc):
            return [{"instrument_id": "IW-1", "status": "SETTLED"}]

    inp_dict = {"session_id": "s1", "bank_id": "kbl", "clearing_date": "2026-09-22",
                "bank_ifsc": "KARB0000001"}
    result = await fetch_ngch_settlement_report(inp_dict, ngch_client=_FakeNgchClient())
    assert result.degraded is False
    assert result.rows == [{"instrument_id": "IW-1", "status": "SETTLED"}]
