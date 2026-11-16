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


@pytest.mark.asyncio
async def test_generate_rrf_records_clearing_date_as_a_date_not_a_string():
    # Found by running it live: cts.rrf_sessions.clearing_date is a DATE column and asyncpg refuses a str, so on a real
    # database the file was uploaded and then recording it failed. A fake connection accepts anything.
    import datetime as dt
    db_pool = _FakeDbPool()
    await generate_rrf(GenerateRRFInput(
        session_id="s1", bank_id="kbl", bank_ifsc="KARB0000001",
        clearing_date="2026-09-22", exception_instruments=_EXCEPTION_INSTRUMENTS,
    ), db_pool=db_pool, minio_client=_FakeMinioClient())
    assert dt.date(2026, 9, 22) in db_pool.conn.executed[0]
    assert "2026-09-22" not in db_pool.conn.executed[0]


# Found on the first live run through reconciliation (2026-11-16): the workflow reported RECONCILED but nothing ever updated
# the clearing_sessions row, so every session stayed SUBMITTED with no settlement time and the ops dashboard could never show SETTLED.
class TestMarkSessionReconciled:
    @pytest.mark.asyncio
    async def test_marks_the_session_reconciled_with_a_settlement_time(self):
        from modules.cts.workflows.activities.session_reconciliation_activities import (
            mark_session_reconciled, MarkSessionReconciledInput,
        )
        pool = _FakeDbPool()
        res = await mark_session_reconciled(
            MarkSessionReconciledInput(session_id="06f0927b-dfde-56d6-920d-49c6b1a8ea49", bank_id="kbl"), db_pool=pool)
        assert res.updated is True
        sql_args = pool.conn.executed[0]
        assert "06f0927b-dfde-56d6-920d-49c6b1a8ea49" in sql_args and "kbl" in sql_args

    @pytest.mark.asyncio
    async def test_only_moves_a_submitted_session(self):
        """A session that is already SETTLED/FAILED, or never filed, must not be flipped back by a replayed workflow."""
        from modules.cts.workflows.activities import session_reconciliation_activities as m
        pool = _FakeDbPool()
        captured = []
        orig = pool.conn.execute
        async def spy(query, *args):
            captured.append(query)
            return await orig(query, *args)
        pool.conn.execute = spy
        await m.mark_session_reconciled(m.MarkSessionReconciledInput(session_id="s", bank_id="kbl"), db_pool=pool)
        assert "status = 'SUBMITTED'" in captured[0] and "settlement_at" in captured[0]


# Nothing in the code ever wrote an outward return row, so every return figure on the dashboards and the bankwise report was zero.
class TestRecordOutwardReturns:
    @pytest.mark.asyncio
    async def test_records_only_returned_rows_with_their_reason_codes(self):
        from modules.cts.workflows.activities.session_reconciliation_activities import (
            record_outward_returns, RecordOutwardReturnsInput,
        )
        pool = _FakeDbPool()
        res = await record_outward_returns(RecordOutwardReturnsInput(
            session_id="06f0927b-dfde-56d6-920d-49c6b1a8ea49", bank_id="kbl",
            exception_instruments=[
                {"instrument_id": "11111111-1111-1111-1111-111111111111", "status": "RETURNED", "reason_code": "39"},
                {"instrument_id": "22222222-2222-2222-2222-222222222222", "status": "MISSING_FROM_SETTLEMENT"},
                {"instrument_id": "33333333-3333-3333-3333-333333333333", "status": "RETURNED"},   # no reason code: cannot record
            ]), db_pool=pool)
        assert res.recorded == 1
        assert len(pool.conn.executed) == 1
        assert "11111111-1111-1111-1111-111111111111" in pool.conn.executed[0] and "39" in pool.conn.executed[0]

    @pytest.mark.asyncio
    async def test_is_idempotent_per_instrument_and_reason(self):
        from modules.cts.workflows.activities import session_reconciliation_activities as m
        pool = _FakeDbPool()
        sqls = []
        orig = pool.conn.execute
        async def spy(q, *a):
            sqls.append(q); return await orig(q, *a)
        pool.conn.execute = spy
        await m.record_outward_returns(m.RecordOutwardReturnsInput(
            session_id="s", bank_id="kbl", exception_instruments=[{"instrument_id": "i", "status": "RETURNED", "reason_code": "39"}]), db_pool=pool)
        assert "NOT EXISTS" in sqls[0] and "cts.cheque_instruments" in sqls[0] and "INWARD_RETURN" in sqls[0]
        # $3 is both inserted and compared: Postgres rejects it as ambiguous unless it is cast (found on the live database)
        assert sqls[0].count("$3::varchar") == 2

    @pytest.mark.asyncio
    async def test_no_database_degrades_without_raising(self):
        from modules.cts.workflows.activities.session_reconciliation_activities import (
            mark_session_reconciled, MarkSessionReconciledInput,
        )
        res = await mark_session_reconciled(MarkSessionReconciledInput(session_id="s", bank_id="kbl"), db_pool=None)
        assert res.updated is False

    @pytest.mark.asyncio
    async def test_returns_recording_without_database_degrades_without_raising(self):
        from modules.cts.workflows.activities.session_reconciliation_activities import (
            record_outward_returns, RecordOutwardReturnsInput,
        )
        res = await record_outward_returns(RecordOutwardReturnsInput(session_id="s", bank_id="kbl", exception_instruments=[]), db_pool=None)
        assert res.recorded == 0
