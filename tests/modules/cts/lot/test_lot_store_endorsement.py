import io
import pytest
from modules.cts.lot.lot_store import LotStore


class Conn:
    def __init__(self, rows=None, one=None):
        self.rows, self.one, self.executed = rows or [], one, []
    async def fetch(self, sql, *a): return self.rows
    async def fetchrow(self, sql, *a): return self.one
    async def execute(self, sql, *a): self.executed.append((sql, a))


class Pool:
    def __init__(self, conn): self.conn = conn
    def acquire(self):
        c = self.conn
        class A:
            async def __aenter__(s): return c
            async def __aexit__(s, *e): return False
        return A()


class Minio:
    def __init__(self): self.objects, self.puts = {"k/front": b"FRONT", "k/rear": b"REAR"}, {}
    def get_object(self, bucket, key):
        data = self.objects[key]
        class R:
            def read(s): return data
            def close(s): pass
            def release_conn(s): pass
        return R()
    def put_object(self, bucket, key, stream, length, content_type=None):
        self.puts[key] = stream.read()


@pytest.mark.asyncio
async def test_fetch_instrument_images_returns_id_last4_front_rear():
    conn = Conn(rows=[{"instrument_id": "u-1", "account_last4": "3051", "image_front_bw_key": "k/front", "image_back_bw_key": "k/rear"}])
    store = LotStore(db_pool=Pool(conn), minio_client=Minio(), bucket="b")
    assert await store.fetch_instrument_images("LOT-1", "kbl") == [("u-1", "3051", b"FRONT", b"REAR")]


@pytest.mark.asyncio
async def test_store_endorsed_rear_uploads_and_records_key():
    conn, mc = Conn(), Minio()
    store = LotStore(db_pool=Pool(conn), minio_client=mc, bucket="b")
    key = await store.store_endorsed_rear("kbl", "u-1", b"IMG")
    assert mc.puts[key] == b"IMG" and key.startswith("kbl/outward/endorsed/u-1/")
    assert "image_back_endorsed_key" in conn.executed[0][0] and key in conn.executed[0][1]


@pytest.mark.asyncio
async def test_endorsement_context_reads_bank_and_branch_names():
    conn = Conn(one={"bank_name": "Karnatak Bank Ltd", "branch_name": "Main Branch"})
    store = LotStore(db_pool=Pool(conn), minio_client=Minio(), bucket="b")
    assert await store.endorsement_context("kbl", "LOT-1") == {"bank_name": "Karnatak Bank Ltd", "branch_name": "Main Branch"}


@pytest.mark.asyncio
async def test_worker_hands_lotstore_the_raw_minio_client_not_the_async_wrapper():
    from unittest.mock import MagicMock
    from modules.cts.worker_activities import _build_lot_store
    raw = MagicMock(name="raw_minio")
    wrapper = MagicMock(name="MinioObjectStore"); wrapper._client = raw
    cfg = MagicMock(); cfg.get_platform = MagicMock(return_value="astra-cts")
    store = await _build_lot_store(MagicMock(), wrapper, cfg)
    assert store._minio is raw


def test_fetch_image_honours_full_s3_reference_bucket():
    calls = []
    class M(Minio):
        def get_object(self, bucket, key):
            calls.append((bucket, key)); return super().get_object(bucket, "k/front")
    store = LotStore(db_pool=Pool(Conn()), minio_client=M(), bucket="astra-cts")
    store._fetch_image("s3://cts-images/kbl/outward/x/front.tiff")
    store._fetch_image("plain/key")
    assert calls == [("cts-images", "kbl/outward/x/front.tiff"), ("astra-cts", "plain/key")]
