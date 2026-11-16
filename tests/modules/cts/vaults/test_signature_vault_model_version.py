"""Vectors from different embedders cannot be compared, so the vault must know which model produced what it holds.

- A vault given an embedder version keys Redis by it and only reads DB rows made by that model: a stale row is a MISS (so the verifier
  re-fetches the specimens from CBS and re-embeds them with the active model), never a comparison against the wrong kind of vector.
- A vault with no version behaves exactly as before (same keys, no filter), so nothing existing changes until a version is supplied.
- Specimens already in the table were made by the generic ImageNet embedder, so that is their default tag.
"""
import contextlib
import hashlib
import hmac
import struct
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.cts.vaults.signature_vault import LEGACY_EMBEDDER_VERSION, SignatureVault

_DIM = 512


def _emb(seed=1):
    return [float((i + seed) % 7 + 0.1) for i in range(_DIM)]


def _pack(e):
    return struct.pack(f"<{_DIM}f", *e)


class _Conn:
    def __init__(self, rows=None):
        self.rows, self.executed, self.fetched = rows or [], [], []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))

    async def fetch(self, sql, *args):
        self.fetched.append((sql, args))
        return self.rows

    @contextlib.asynccontextmanager
    async def transaction(self):
        yield


class _Pool:
    def __init__(self, rows=None):
        self.conn = _Conn(rows)

    @contextlib.asynccontextmanager
    async def acquire(self):
        yield self.conn


def _redis_miss():
    r = MagicMock()
    r.lrange = AsyncMock(return_value=[])
    r.pipeline = MagicMock(return_value=MagicMock(delete=MagicMock(), rpush=MagicMock(), execute=AsyncMock()))
    return r


def _vault(version=None, pool=None, redis=None):
    v = SignatureVault(bank_id="kbl", pepper="pep", db_pool=pool, embedder_version=version)
    v._redis = redis or _redis_miss()
    v._ready = True
    return v


def _hash(acct):
    return hmac.new(b"pep", f"kbl:{acct}".encode(), hashlib.sha256).hexdigest()


def test_the_generic_model_is_the_default_tag_of_existing_rows():
    assert LEGACY_EMBEDDER_VERSION == "resnet18-imagenet-generic"


def test_no_version_keeps_the_existing_key_format():
    assert _vault()._make_key("4242424242") == f"sig:kbl:{_hash('4242424242')}:PRIMARY"


def test_a_version_is_part_of_the_redis_key_so_old_model_vectors_are_never_read():
    old, new = _vault("modelA@1"), _vault("modelB@2")
    assert old._make_key("4242424242") != new._make_key("4242424242")
    assert new._make_key("4242424242").endswith(":PRIMARY:v:modelB@2")


@pytest.mark.asyncio
async def test_store_tags_each_row_with_the_active_version_and_updates_it_on_conflict():
    pool = _Pool()
    await _vault("modelB@2", pool).store_embeddings("4242424242", [_emb(1), _emb(2)], source="CBS_FALLBACK")
    sql, args = pool.conn.executed[0]
    assert "embedding_model" in sql and "embedding_model = EXCLUDED.embedding_model" in sql
    assert "modelB@2" in args


@pytest.mark.asyncio
async def test_store_without_a_version_tags_rows_as_the_generic_model():
    pool = _Pool()
    await _vault(None, pool).store_embeddings("4242424242", [_emb(1)])
    assert LEGACY_EMBEDDER_VERSION in pool.conn.executed[0][1]


@pytest.mark.asyncio
async def test_db_read_only_returns_rows_made_by_the_active_model():
    pool = _Pool(rows=[])                       # nothing matches the active version: what the database returns for stale rows
    vault = _vault("modelB@2", pool)
    out = await vault._load_signatory_from_db(vault._account_hash("4242424242"), "PRIMARY")
    sql, args = pool.conn.fetched[0]
    assert out == [] and "embedding_model = $4" in sql and args[-1] == "modelB@2"


@pytest.mark.asyncio
async def test_no_version_reads_without_a_model_filter():
    pool = _Pool(rows=[{"embedding": _pack(_emb(1))}])
    vault = _vault(None, pool)
    out = await vault._load_signatory_from_db(vault._account_hash("4242424242"), "PRIMARY")
    assert len(out) == 1 and "embedding_model" not in pool.conn.fetched[0][0]


@pytest.mark.asyncio
async def test_a_stale_row_is_a_vault_miss_for_the_verifier():
    """Stale-model rows exist, none for the active model: the per-signatory read returns nothing, so verify_signature falls through to
    the CBS re-fetch instead of comparing against vectors the active model never made."""
    vault = _vault("modelB@2", _Pool(rows=[]))
    assert await vault.get_specimens_by_signatory("4242424242", "kbl") == {}
