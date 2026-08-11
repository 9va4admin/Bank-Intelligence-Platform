"""
AllocationService — applies the bank's configured allocation_mode to instrument claiming.

Three modes (Layer 3 config key: allocation_mode):
  SELF    — reviewer must manually claim via UI; auto_assign() is a no-op
  HYBRID  — reviewer can claim OR auto_assign() fires after an unclaimed timeout
  AUTO    — auto_assign() always picks from available reviewers; manual claim ignored

Auto-assignment is round-robin across the available pool for simplicity.
The caller (API router / Temporal activity) is responsible for maintaining
the active reviewer pool and invoking auto_assign() at the right time.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger()


@dataclass
class AllocationResult:
    claimed: bool
    reviewer_id: Optional[str] = None  # set when claimed=True
    held_by: Optional[str] = None      # set when claimed=False and already held


class AllocationService:
    def __init__(self, lock_service) -> None:
        self._lock = lock_service

    async def claim(
        self, instrument_id: str, reviewer_id: str, cts_config: dict
    ) -> AllocationResult:
        """Reviewer manually claims an instrument.

        Works in all three modes (UI always shows the Claim button; backend
        enforces semantics). In AUTO mode the claim is still honoured — a
        human override of the auto-assignment is always permitted.
        """
        acquired = await self._lock.acquire_lock(instrument_id, reviewer_id, cts_config)
        if acquired:
            log.info(
                "allocation.claimed",
                instrument_id=instrument_id,
                reviewer_id=reviewer_id,
                mode=cts_config.get("allocation_mode", "SELF"),
            )
            return AllocationResult(claimed=True, reviewer_id=reviewer_id)

        holder = await self._lock.get_lock_holder(instrument_id)
        log.info(
            "allocation.claim_rejected",
            instrument_id=instrument_id,
            requesting=reviewer_id,
            held_by=holder,
        )
        return AllocationResult(claimed=False, held_by=holder)

    async def unclaim(
        self, instrument_id: str, reviewer_id: str, cts_config: dict
    ) -> None:
        """Reviewer releases their claim on an instrument."""
        await self._lock.release_lock(instrument_id, reviewer_id)
        log.info(
            "allocation.unclaimed",
            instrument_id=instrument_id,
            reviewer_id=reviewer_id,
        )

    async def auto_assign(
        self,
        instrument_id: str,
        available_reviewers: list[str],
        cts_config: dict,
    ) -> AllocationResult:
        """Attempt to auto-assign an unclaimed instrument to a reviewer.

        In SELF mode: always returns claimed=False (auto-assign is disabled).
        In HYBRID/AUTO mode: picks a random reviewer from the available pool
          and tries to acquire the lock on their behalf. Fails gracefully if
          the instrument was already claimed by another path.

        Args:
            instrument_id: the instrument to assign
            available_reviewers: active reviewers who can accept work
            cts_config: Layer 3 config dict

        Returns:
            AllocationResult with claimed=True if assigned, False otherwise
        """
        mode = cts_config.get("allocation_mode", "SELF")

        if mode == "SELF":
            return AllocationResult(claimed=False)

        # Check if already claimed before attempting assignment
        existing_holder = await self._lock.get_lock_holder(instrument_id)
        if existing_holder is not None:
            log.info(
                "allocation.auto_assign_skipped_already_claimed",
                instrument_id=instrument_id,
                held_by=existing_holder,
            )
            return AllocationResult(claimed=False, held_by=existing_holder)

        if not available_reviewers:
            log.warning(
                "allocation.auto_assign_no_reviewers_available",
                instrument_id=instrument_id,
            )
            return AllocationResult(claimed=False)

        # Round-robin pick — shuffle to distribute across workers
        candidates = list(available_reviewers)
        random.shuffle(candidates)

        for candidate in candidates:
            acquired = await self._lock.acquire_lock(instrument_id, candidate, cts_config)
            if acquired:
                log.info(
                    "allocation.auto_assigned",
                    instrument_id=instrument_id,
                    reviewer_id=candidate,
                    mode=mode,
                )
                return AllocationResult(claimed=True, reviewer_id=candidate)

        # All candidates lost the race (should be very rare)
        log.warning(
            "allocation.auto_assign_all_candidates_failed",
            instrument_id=instrument_id,
        )
        return AllocationResult(claimed=False)
