"""
SB relay activities — used by SBInwardForwardingWorkflow and AgencyCCWorkflow.

resolve_crl_batch    : map drawee_ifsc → pu_id for inward instrument routing.
publish_to_pu_queues : Kafka fan-out: each instrument → cts.inward.{bank_id}.
build_lot_package    : assemble sealed lots into a single CTS package file.
sb_submit_lot        : deliver the package to the upstream Sponsor Bank.
publish_relay_event  : publish relay outcome to cts.sb.relay.outward.{...}.

All activities degrade gracefully when external deps are unavailable.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from shared.event_bus.topics import CTS_SB_RELAY_OUTWARD

log = structlog.get_logger()


# ── resolve_crl_batch ─────────────────────────────────────────────────────────

class CRLBatchInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    agency_id: str
    instruments: list[dict]     # each: {instrument_id, drawee_ifsc, ...}


class CRLBatchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    resolved: list[dict]        # [{instrument_id, pu_id?, success, error?}, ...]


@activity.defn
async def resolve_crl_batch(
    inp: CRLBatchInput,
    db_pool: Any = None,
) -> CRLBatchResult:
    """
    For each instrument, resolve drawee_ifsc to a Processing Unit ID via the
    Clearing Register Lookup (CRL) table in YugabyteDB.
    Degrades gracefully when db_pool is unavailable — marks all as failed.
    """
    if db_pool is None:
        log.warning(
            "resolve_crl_batch.db_unavailable",
            agency_id=inp.agency_id,
            instrument_count=len(inp.instruments),
        )
        return CRLBatchResult(
            resolved=[
                {
                    "instrument_id": ins["instrument_id"],
                    "success": False,
                    "error": "DB_UNAVAILABLE",
                }
                for ins in inp.instruments
            ]
        )

    resolved: list[dict] = []
    async with db_pool.acquire() as conn:
        for ins in inp.instruments:
            row = await conn.fetchrow(
                """
                SELECT pu_id
                  FROM cts.crl_routing
                 WHERE drawee_ifsc = $1
                   AND agency_id   = $2
                """,
                ins["drawee_ifsc"],
                inp.agency_id,
            )
            if row:
                resolved.append(
                    {
                        "instrument_id": ins["instrument_id"],
                        "pu_id": row["pu_id"],
                        "success": True,
                    }
                )
            else:
                resolved.append(
                    {
                        "instrument_id": ins["instrument_id"],
                        "success": False,
                        "error": f"NO_CRL_ENTRY:{ins['drawee_ifsc']}",
                    }
                )

    log.info(
        "resolve_crl_batch.complete",
        agency_id=inp.agency_id,
        total=len(inp.instruments),
        resolved_count=sum(1 for r in resolved if r["success"]),
    )
    return CRLBatchResult(resolved=resolved)


# ── publish_to_pu_queues ──────────────────────────────────────────────────────

class PublishToPUInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    agency_id: str
    resolved_instruments: list[dict]    # from resolve_crl_batch — success=True only


class PublishToPUResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    published_count: int
    degraded: bool = False


@activity.defn
async def publish_to_pu_queues(
    inp: PublishToPUInput,
    event_producer: Any = None,
) -> PublishToPUResult:
    """
    Publishes each successfully-resolved instrument to its target PU's
    cts.inward.{bank_id} Kafka topic.  Degrades gracefully when event_producer
    is unavailable — all instruments are skipped (logged as warning).
    """
    if event_producer is None:
        log.warning(
            "publish_to_pu_queues.producer_unavailable",
            agency_id=inp.agency_id,
        )
        return PublishToPUResult(published_count=0, degraded=True)

    routable = [r for r in inp.resolved_instruments if r.get("success")]
    for item in routable:
        topic = f"cts.inward.{item['pu_id']}"
        await event_producer.produce(topic, item)

    log.info(
        "publish_to_pu_queues.complete",
        agency_id=inp.agency_id,
        published_count=len(routable),
    )
    return PublishToPUResult(published_count=len(routable), degraded=False)


# ── build_lot_package ─────────────────────────────────────────────────────────

class BuildLotPackageInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    agency_id: str
    sb_bank_id: str
    session_id: str
    lot_numbers: list[str]
    instrument_count: int


class BuildLotPackageResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    package_path: Optional[str] = None
    error: Optional[str] = None


@activity.defn
async def build_lot_package(
    inp: BuildLotPackageInput,
    lot_store: Any = None,
) -> BuildLotPackageResult:
    """
    Assembles all lots into a single CTS package file for transmission to the
    Sponsor Bank.  lot_store is DI-injected at worker startup (reads from MinIO).
    Degrades gracefully when unavailable.
    """
    if lot_store is None:
        log.warning(
            "build_lot_package.lot_store_unavailable",
            agency_id=inp.agency_id,
            sb_bank_id=inp.sb_bank_id,
            session_id=inp.session_id,
        )
        return BuildLotPackageResult(error="LOT_STORE_UNAVAILABLE")

    package_path = await lot_store.assemble_package(
        lot_numbers=inp.lot_numbers,
        agency_id=inp.agency_id,
        sb_bank_id=inp.sb_bank_id,
        session_id=inp.session_id,
    )

    log.info(
        "build_lot_package.complete",
        agency_id=inp.agency_id,
        sb_bank_id=inp.sb_bank_id,
        session_id=inp.session_id,
        lot_count=len(inp.lot_numbers),
        package_path=package_path,
    )
    return BuildLotPackageResult(package_path=package_path)


# ── sb_submit_lot ─────────────────────────────────────────────────────────────

class SBSubmitInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    agency_id: str
    sb_bank_id: str
    session_id: str
    package_path: str
    instrument_count: int
    connector_type: str         # "SFTP_GENERIC" | "BANCS_API" | "NELITO_API"


class SBSubmitResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    success: bool
    reference_number: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


@activity.defn
async def sb_submit_lot(
    inp: SBSubmitInput,
    sb_connector: Any = None,
) -> SBSubmitResult:
    """
    Delivers the lot package to the upstream Sponsor Bank via the appropriate
    SBConnector adapter (SFTP / BaNCS API / Nelito API).
    Degrades gracefully when sb_connector is None.
    """
    if sb_connector is None:
        log.warning(
            "sb_submit_lot.connector_unavailable",
            agency_id=inp.agency_id,
            sb_bank_id=inp.sb_bank_id,
            connector_type=inp.connector_type,
        )
        return SBSubmitResult(success=False, error_code="CONNECTOR_UNAVAILABLE")

    raw = await sb_connector.submit_lot(
        package_path=inp.package_path,
        agency_id=inp.agency_id,
        instrument_count=inp.instrument_count,
    )

    if not raw.get("success"):
        error_code = raw.get("error_code", "SB_SUBMIT_FAILED")
        log.error(
            "sb_submit_lot.rejected",
            agency_id=inp.agency_id,
            sb_bank_id=inp.sb_bank_id,
            error_code=error_code,
        )
        return SBSubmitResult(
            success=False,
            error_code=error_code,
            error_message=raw.get("error_message"),
        )

    log.info(
        "sb_submit_lot.submitted",
        agency_id=inp.agency_id,
        sb_bank_id=inp.sb_bank_id,
        reference_number=raw.get("reference_number"),
        instrument_count=inp.instrument_count,
    )
    return SBSubmitResult(success=True, reference_number=raw.get("reference_number"))


# ── publish_relay_event ───────────────────────────────────────────────────────

class PublishRelayInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    agency_id: str
    sb_bank_id: str
    session_id: str
    sb_reference: str
    instrument_count: int


class PublishRelayResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    published: bool
    topic: Optional[str] = None


@activity.defn
async def publish_relay_event(
    inp: PublishRelayInput,
    event_producer: Any = None,
) -> PublishRelayResult:
    """
    Publishes the relay completion event to the cts.sb.relay.outward Kafka topic.
    Degrades gracefully when event_producer is unavailable (non-critical).
    """
    topic = CTS_SB_RELAY_OUTWARD.format(
        agency_id=inp.agency_id,
        sb_bank_id=inp.sb_bank_id,
    )

    if event_producer is None:
        log.warning(
            "publish_relay_event.producer_unavailable",
            agency_id=inp.agency_id,
            sb_bank_id=inp.sb_bank_id,
            topic=topic,
        )
        return PublishRelayResult(published=False, topic=topic)

    await event_producer.produce(
        topic,
        {
            "agency_id": inp.agency_id,
            "sb_bank_id": inp.sb_bank_id,
            "session_id": inp.session_id,
            "sb_reference": inp.sb_reference,
            "instrument_count": inp.instrument_count,
        },
    )

    log.info(
        "publish_relay_event.published",
        agency_id=inp.agency_id,
        sb_bank_id=inp.sb_bank_id,
        topic=topic,
        instrument_count=inp.instrument_count,
    )
    return PublishRelayResult(published=True, topic=topic)
