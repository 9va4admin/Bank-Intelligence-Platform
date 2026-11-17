"""Bulk re-vectorization of the signature vault after the active embedder changes.

The vault stores vectors only, not images, and vectors from different embedders cannot be compared. So each account's specimens are
fetched again from the bank's CBS, embedded with the active embedder, and stored under its version. Accounts already on the active
embedder are skipped (unless forced). One failing account never stops the run.

This is the bulk form of what verify_signature already does lazily on a vault miss (it re-fetches from CBS and re-embeds); use it to avoid
sending every first cheque after a model change to human review.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import structlog

log = structlog.get_logger()


@dataclass
class RevectorizeReport:
    ok: int = 0
    skipped_current: int = 0
    no_specimens: int = 0
    failed: int = 0
    failed_accounts_last4: list[str] = field(default_factory=list)


async def _specimens_from_cbs(cbs_connector: Any, account: str, bank_id: str) -> dict[str, list[bytes]]:
    try:
        signatories = await cbs_connector.get_signatory_data(account, bank_id)
    except NotImplementedError:                               # older CBS adapter: flat specimen list is the PRIMARY signatory
        flat = await cbs_connector.get_signature_specimens(account, bank_id)
        return {"PRIMARY": list(flat or [])}
    return {s.signatory_id: list(s.specimen_images) for s in (signatories or [])}


async def revectorize_accounts(
    vault: Any, embedder: Any, cbs_connector: Any, accounts: Iterable[str], bank_id: str, force: bool = False,
) -> RevectorizeReport:
    report = RevectorizeReport()
    for account in accounts:
        try:
            if not force and await vault.get_specimens_by_signatory(account, bank_id):
                report.skipped_current += 1
                continue
            stored = False
            for signatory_id, images in (await _specimens_from_cbs(cbs_connector, account, bank_id)).items():
                embeddings = []
                for raw in images:
                    try:
                        embeddings.append(await embedder.embed(raw, bank_id=bank_id))
                    except Exception as exc:
                        log.warning("revectorize.specimen_embed_failed", account_last4=account[-4:], signatory_id=signatory_id, error=str(exc))
                if embeddings:
                    await vault.store_embeddings(account, embeddings, signatory_id=signatory_id, source="CBS")
                    stored = True
            if stored:
                report.ok += 1
            else:
                report.no_specimens += 1
        except Exception as exc:
            report.failed += 1
            report.failed_accounts_last4.append(account[-4:])
            log.warning("revectorize.account_failed", account_last4=account[-4:], bank_id=bank_id, error=str(exc))
    log.info("revectorize.done", bank_id=bank_id, ok=report.ok, skipped_current=report.skipped_current,
             no_specimens=report.no_specimens, failed=report.failed)
    return report
