"""Bulk re-vectorization: when the active embedder changes, re-embed each account's specimens (fetched again from the bank's CBS, because the
vault stores only vectors) and store them under the new version. Accounts already current are skipped; an account CBS has nothing for, or an
error on one account, is counted and the run continues."""
import pytest

from modules.cts.vaults.revectorize import revectorize_accounts


class _Vault:
    def __init__(self, current=()):
        self.current, self.stored = set(current), []

    async def get_specimens_by_signatory(self, account, bank_id):
        return {"PRIMARY": [[1.0]]} if account in self.current else {}

    async def store_embeddings(self, account, embeddings, signatory_id="PRIMARY", source="CBS"):
        self.stored.append((account, signatory_id, len(embeddings), source))


class _Embedder:
    async def embed(self, image_bytes, bank_id=""):
        return [float(len(image_bytes))]


class _Sig:
    def __init__(self, sid, images):
        self.signatory_id, self.specimen_images = sid, images


class _Cbs:
    def __init__(self, data):
        self.data = data

    async def get_signatory_data(self, account, bank_id):
        v = self.data[account]
        if isinstance(v, Exception):
            raise v
        return v


@pytest.mark.asyncio
async def test_re_embeds_each_signatory_from_cbs_and_stores_it_with_a_source_the_table_allows():
    # cts.signature_embeddings.source is CHECK (source IN ('CBS', 'CBS_FALLBACK')); the specimens come from CBS (found on the live database)
    vault = _Vault()
    cbs = _Cbs({"A1": [_Sig("PRIMARY", [b"aa", b"bbb"]), _Sig("JOINT_1", [b"c"])]})
    rep = await revectorize_accounts(vault, _Embedder(), cbs, ["A1"], bank_id="kbl")
    assert (rep.ok, rep.skipped_current, rep.no_specimens, rep.failed) == (1, 0, 0, 0)
    assert vault.stored == [("A1", "PRIMARY", 2, "CBS"), ("A1", "JOINT_1", 1, "CBS")]


@pytest.mark.asyncio
async def test_accounts_already_on_the_active_model_are_skipped_unless_forced():
    vault = _Vault(current={"A1"})
    cbs = _Cbs({"A1": [_Sig("PRIMARY", [b"aa"])]})
    rep = await revectorize_accounts(vault, _Embedder(), cbs, ["A1"], bank_id="kbl")
    assert rep.skipped_current == 1 and rep.ok == 0 and vault.stored == []
    forced = await revectorize_accounts(vault, _Embedder(), cbs, ["A1"], bank_id="kbl", force=True)
    assert forced.ok == 1 and len(vault.stored) == 1


@pytest.mark.asyncio
async def test_missing_specimens_and_errors_are_counted_and_the_run_continues():
    vault = _Vault()
    cbs = _Cbs({"NONE": [], "BOOM": RuntimeError("cbs down"), "GOOD": [_Sig("PRIMARY", [b"x"])]})
    rep = await revectorize_accounts(vault, _Embedder(), cbs, ["NONE", "BOOM", "GOOD"], bank_id="kbl")
    assert (rep.ok, rep.no_specimens, rep.failed) == (1, 1, 1)
    assert rep.failed_accounts_last4 == ["BOOM"[-4:]] and [s[0] for s in vault.stored] == ["GOOD"]


@pytest.mark.asyncio
async def test_a_signatory_whose_specimens_cannot_be_embedded_is_not_stored_empty():
    class _Bad:
        async def embed(self, image_bytes, bank_id=""):
            raise ValueError("undecodable")
    vault = _Vault()
    rep = await revectorize_accounts(vault, _Bad(), _Cbs({"A1": [_Sig("PRIMARY", [b"x"])]}), ["A1"], bank_id="kbl")
    assert vault.stored == [] and rep.no_specimens == 1
