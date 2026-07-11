"""
AccountEnroller — enrolls a single account via the MSV pipeline.

Fetch signatory data from CBS → embed each specimen → store in registry.
Image bytes are NEVER stored. They are passed to the embedding model and
immediately discarded — the embedding vector is what gets persisted.

Idempotent: if already enrolled (per progress_tracker.is_enrolled), returns SKIPPED.
"""
from typing import Optional

import structlog
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict

from modules.msv.ai.embedding_model import EmbeddingModelUnavailableError
from shared.cbs_connector.exceptions import CBSUnavailableError

log = structlog.get_logger()
tracer = trace.get_tracer("astra.msv.enrollment")


class EnrollmentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_hash: str               # HMAC-SHA256 — never the raw account number
    status: str                     # "ENROLLED" | "SKIPPED" | "FAILED"
    specimens_enrolled: int
    error_reason: Optional[str] = None


class AccountEnroller:
    """
    Enrolls a single account's signatories.

    Dependencies injected:
        cbs_connector:    fetches raw signatory data + specimen images
        embedding_model:  converts image bytes → 512-dim vector
        registry:         stores embeddings (Redis + PostgreSQL)
        progress_tracker: tracks enrolled/failed status
    """

    def __init__(
        self,
        cbs_connector,
        embedding_model,
        registry,
        progress_tracker,
    ) -> None:
        self._cbs = cbs_connector
        self._model = embedding_model
        self._registry = registry
        self._tracker = progress_tracker

    async def enroll(
        self,
        bank_id: str,
        account_number: str,
        operation_type: str,
        batch_id: str,
    ) -> EnrollmentResult:
        """
        Enroll all signatories for the account.

        Returns EnrollmentResult. Never raises — errors become FAILED status.
        Image bytes from CBS are embedded immediately and then discarded.
        Raw account_number is hashed before any storage or logging.
        """
        with tracer.start_as_current_span("msv.enroll.account") as span:
            span.set_attribute("bank_id", bank_id)
            span.set_attribute("operation_type", operation_type)
            span.set_attribute("batch_id", batch_id)

            # Hash account number — never log or store raw
            account_hash = await self._registry._hash_account(account_number, bank_id)
            span.set_attribute("account_hash_prefix", account_hash[:8])

            # Idempotency check
            if await self._tracker.is_enrolled(bank_id, account_hash):
                log.info(
                    "msv.enroll.skipped",
                    bank_id=bank_id,
                    batch_id=batch_id,
                    reason="already_enrolled",
                )
                return EnrollmentResult(
                    account_hash=account_hash,
                    status="SKIPPED",
                    specimens_enrolled=0,
                )

            try:
                # Fetch raw signatory data from CBS
                signatory_list = await self._cbs.get_signatory_data(account_number, bank_id)

                if not signatory_list:
                    error = "NO_SIGNATORY_DATA_FROM_CBS"
                    await self._tracker.mark_failed(bank_id, account_hash, error, batch_id)
                    return EnrollmentResult(
                        account_hash=account_hash,
                        status="FAILED",
                        specimens_enrolled=0,
                        error_reason=error,
                    )

                total_specimens = 0
                for sig_data in signatory_list:
                    for specimen_idx, image_bytes in enumerate(sig_data.specimen_images):
                        # Embed immediately — bytes must not be stored
                        embedding = await self._model.embed(image_bytes, bank_id)
                        # Discard image_bytes (goes out of scope here)

                        # Store embedding in registry
                        await self._registry.store(
                            bank_id=bank_id,
                            account_hash=account_hash,
                            signatory_id=sig_data.signatory_id,
                            specimen_idx=specimen_idx,
                            embedding=embedding,
                            operation_type=operation_type,
                        )
                        total_specimens += 1

                await self._tracker.mark_enrolled(bank_id, account_hash, batch_id)

                log.info(
                    "msv.enroll.complete",
                    bank_id=bank_id,
                    batch_id=batch_id,
                    specimens=total_specimens,
                )
                return EnrollmentResult(
                    account_hash=account_hash,
                    status="ENROLLED",
                    specimens_enrolled=total_specimens,
                )

            except EmbeddingModelUnavailableError as exc:
                error = f"EMBEDDING_MODEL_UNAVAILABLE: {exc}"
                log.error(
                    "msv.enroll.embedding_failed",
                    bank_id=bank_id,
                    batch_id=batch_id,
                    error=str(exc),
                )
                await self._tracker.mark_failed(bank_id, account_hash, error, batch_id)
                return EnrollmentResult(
                    account_hash=account_hash,
                    status="FAILED",
                    specimens_enrolled=0,
                    error_reason=error,
                )

            except CBSUnavailableError as exc:
                error = f"CBS_UNAVAILABLE: {exc}"
                log.error(
                    "msv.enroll.cbs_failed",
                    bank_id=bank_id,
                    batch_id=batch_id,
                    error=str(exc),
                )
                await self._tracker.mark_failed(bank_id, account_hash, error, batch_id)
                return EnrollmentResult(
                    account_hash=account_hash,
                    status="FAILED",
                    specimens_enrolled=0,
                    error_reason=error,
                )

            except Exception as exc:
                error = f"UNEXPECTED_ERROR: {exc}"
                log.error(
                    "msv.enroll.unexpected_error",
                    bank_id=bank_id,
                    batch_id=batch_id,
                    error=str(exc),
                )
                await self._tracker.mark_failed(bank_id, account_hash, error, batch_id)
                return EnrollmentResult(
                    account_hash=account_hash,
                    status="FAILED",
                    specimens_enrolled=0,
                    error_reason=error,
                )
