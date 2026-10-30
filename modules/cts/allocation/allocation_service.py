"""
AllocationService — applies the bank's configured allocation_mode to instrument claiming.

Three modes (Layer 3 config key: allocation_mode):
  SELF    — reviewer must manually claim via UI; auto_assign() is a no-op
  HYBRID  — reviewer can claim OR auto_assign() fires after an unclaimed timeout
  AUTO    — auto_assign() always picks from available reviewers; manual claim still allowed (human override)

Auto-assignment (when a bank_id is supplied):
  * picks the LEAST LOADED eligible reviewer (allocation_strategy=LEAST_LOADED, default) or a random one (RANDOM)
  * skips reviewers already at allocation_max_per_reviewer claims (0 = no cap)
  * an item inside allocation_urgent_margin_minutes of its IET deadline ignores the cap, because an item nobody
    picks up before its IET is deemed approved
  * only considers reviewers scoped to the item's clearing zone (an item with no zone can go to anyone;
    a reviewer scoped to "ALL" or to no zones can take any zone)
  * records the assignment as "unopened" so rebalance() may move it; a reviewer opening the item (re-claiming it)
    pins it, and an admin assignment is pinned from the start

rebalance() spreads unopened auto-assigned work across the reviewers who are logged in now, so people who join
later in the day receive a fair share without anyone's opened work being taken away.

Callers without a bank_id get the original behaviour (random pick, no zones/cap), which keeps older call sites working.
"""
from __future__ import annotations

import random
import time as _time
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger()

_ANY_ZONE = "ALL"


@dataclass
class AllocationResult:
    claimed: bool
    reviewer_id: Optional[str] = None  # set when claimed=True
    held_by: Optional[str] = None      # set when claimed=False and already held
    reason: Optional[str] = None       # why nothing was assigned: NO_ACTIVE_REVIEWERS | NO_ELIGIBLE_REVIEWER |
                                       # ALL_AT_CAPACITY | ZONE_RESTRICTED | ALREADY_CLAIMED | SELF_MODE


@dataclass
class RebalanceResult:
    moves: list[tuple[str, str, str]] = field(default_factory=list)   # (instrument_id, from_reviewer, to_reviewer)


def zone_allows(item_zone: Optional[str], reviewer_zones: Optional[list[str]]) -> bool:
    """True if a reviewer scoped to reviewer_zones may work an item in item_zone."""
    if not item_zone or not reviewer_zones:
        return True
    return _ANY_ZONE in reviewer_zones or item_zone in reviewer_zones


class AllocationService:
    def __init__(self, lock_service) -> None:
        self._lock = lock_service

    # ------------------------------------------------------------------ claim / unclaim

    async def claim(
        self, instrument_id: str, reviewer_id: str, cts_config: dict,
        bank_id: Optional[str] = None, reviewer_zones: Optional[list[str]] = None,
    ) -> AllocationResult:
        """Reviewer manually claims (or re-opens) an instrument.

        Works in all three modes (UI always shows the Claim button; backend enforces semantics). In AUTO mode the
        claim is still honoured: a human override of the auto-assignment is always permitted, and claiming an item
        you already hold counts as opening it, which pins it so the rebalancer never moves it.
        A reviewer scoped to a clearing zone cannot claim an item from another zone.
        """
        if bank_id and reviewer_zones is not None:
            meta = await self._lock.get_item_meta(bank_id, instrument_id)
            if not zone_allows(meta.get("zone"), reviewer_zones):
                log.info("allocation.claim_refused_zone", instrument_id=instrument_id, reviewer_id=reviewer_id)
                return AllocationResult(claimed=False, reason="ZONE_RESTRICTED")

        acquired = await self._lock.acquire_lock(instrument_id, reviewer_id, cts_config)
        if acquired:
            if bank_id:
                await self._lock.unmark_auto(bank_id, instrument_id)
                await self._lock.remove_hybrid_pending(bank_id, instrument_id)
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
        return AllocationResult(claimed=False, held_by=holder, reason="ALREADY_CLAIMED")

    async def unclaim(
        self, instrument_id: str, reviewer_id: str, cts_config: dict, bank_id: Optional[str] = None,
    ) -> None:
        """Reviewer releases their claim on an instrument."""
        await self._lock.release_lock(instrument_id, reviewer_id, bank_id=bank_id) if bank_id else \
            await self._lock.release_lock(instrument_id, reviewer_id)
        log.info(
            "allocation.unclaimed",
            instrument_id=instrument_id,
            reviewer_id=reviewer_id,
        )

    # ------------------------------------------------------------------ admin assign

    async def assign(self, instrument_id: str, reviewer_id: str, cts_config: dict, bank_id: str) -> Optional[str]:
        """Admin: give the instrument to reviewer_id (reassigning it if someone holds it). Returns the previous
        holder. The caller enforces the admin role and writes the audit record."""
        return await self._lock.force_assign(instrument_id, reviewer_id, cts_config, bank_id=bank_id)

    # ------------------------------------------------------------------ auto assign

    async def auto_assign(
        self,
        instrument_id: str,
        available_reviewers: list[str],
        cts_config: dict,
        bank_id: Optional[str] = None,
    ) -> AllocationResult:
        """Attempt to auto-assign an unclaimed instrument to a reviewer.

        In SELF mode: always returns claimed=False (auto-assign is disabled).
        In HYBRID/AUTO mode: chooses a reviewer (least loaded by default) and takes the lock on their behalf.
        Fails gracefully, with a reason, when nobody is eligible or the instrument was claimed by another path.
        """
        mode = cts_config.get("allocation_mode", "SELF")

        if mode == "SELF":
            return AllocationResult(claimed=False, reason="SELF_MODE")

        existing_holder = await self._lock.get_lock_holder(instrument_id)
        if existing_holder is not None:
            log.info(
                "allocation.auto_assign_skipped_already_claimed",
                instrument_id=instrument_id,
                held_by=existing_holder,
            )
            return AllocationResult(claimed=False, held_by=existing_holder, reason="ALREADY_CLAIMED")

        if not available_reviewers:
            log.warning("allocation.auto_assign_no_reviewers_available", instrument_id=instrument_id)
            return AllocationResult(claimed=False, reason="NO_ACTIVE_REVIEWERS")

        if bank_id:
            candidates, reason = await self._choose_candidates(instrument_id, available_reviewers, cts_config, bank_id)
            if not candidates:
                log.info("allocation.auto_assign_none_eligible", instrument_id=instrument_id, reason=reason)
                return AllocationResult(claimed=False, reason=reason)
        else:
            candidates = list(available_reviewers)
            random.shuffle(candidates)

        for candidate in candidates:
            acquired = await self._lock.acquire_lock(instrument_id, candidate, cts_config)
            if acquired:
                if bank_id:
                    await self._lock.mark_auto(bank_id, instrument_id)
                log.info(
                    "allocation.auto_assigned",
                    instrument_id=instrument_id,
                    reviewer_id=candidate,
                    mode=mode,
                )
                return AllocationResult(claimed=True, reviewer_id=candidate)

        log.warning("allocation.auto_assign_all_candidates_failed", instrument_id=instrument_id)
        return AllocationResult(claimed=False, reason="ALREADY_CLAIMED")

    async def _choose_candidates(self, instrument_id, available, cts_config, bank_id):
        """Eligible reviewers in preference order, or ([], reason)."""
        meta = await self._lock.get_item_meta(bank_id, instrument_id)
        zones = await self._lock.get_reviewer_zones(bank_id)
        eligible = [r for r in available if zone_allows(meta.get("zone"), zones.get(r))]
        if not eligible:
            return [], "NO_ELIGIBLE_REVIEWER"

        loads = await self._lock.reviewer_loads(eligible)
        cap = int(cts_config.get("allocation_max_per_reviewer", 0) or 0)
        if cap > 0 and not self._urgent(meta, cts_config):
            eligible = [r for r in eligible if loads[r] < cap]
            if not eligible:
                return [], "ALL_AT_CAPACITY"

        if cts_config.get("allocation_strategy", "LEAST_LOADED") == "RANDOM":
            random.shuffle(eligible)
            return eligible, None
        # Least loaded first; a random tie-break spreads equal loads instead of favouring list order.
        tiebreak = {r: random.random() for r in eligible}
        return sorted(eligible, key=lambda r: (loads[r], tiebreak[r])), None

    @staticmethod
    def _urgent(meta: dict, cts_config: dict, now: Optional[float] = None) -> bool:
        deadline = meta.get("iet_deadline")
        if not deadline:
            return False
        margin = float(cts_config.get("allocation_urgent_margin_minutes", 0) or 0) * 60
        return float(deadline) - (now if now is not None else _time.time()) <= margin

    # ------------------------------------------------------------------ rebalance

    async def rebalance(self, bank_id: str, cts_config: dict) -> RebalanceResult:
        """Spread unopened auto-assigned work across the reviewers who are active now.

        Moves items from the most loaded reviewer to the least loaded one until their loads differ by at most one,
        never moving an item the reviewer has opened, never across a clearing-zone restriction, and never more than
        allocation_rebalance_max_moves in one pass. An item closest to its IET deadline is moved first so it lands
        on the reviewer with the most free capacity.
        """
        result = RebalanceResult()
        if not cts_config.get("allocation_rebalance_enabled", True):
            return result
        active = await self._lock.get_active_reviewers(bank_id)
        if len(active) < 2:
            return result

        zones = await self._lock.get_reviewer_zones(bank_id)
        loads = await self._lock.reviewer_loads(active)
        movable: dict[str, list[str]] = {r: [] for r in active}
        for iid, holder in await self._lock.list_auto(bank_id):
            if holder in movable:
                movable[holder].append(iid)
        # Most urgent first: those should land on the least-loaded reviewer.
        deadlines: dict[str, float] = {}
        for items in movable.values():
            for iid in items:
                deadlines[iid] = (await self._lock.get_item_meta(bank_id, iid)).get("iet_deadline") or float("inf")
        for items in movable.values():
            items.sort(key=lambda i: deadlines[i])

        max_moves = int(cts_config.get("allocation_rebalance_max_moves", 20) or 0)
        while len(result.moves) < max_moves:
            donors = sorted((r for r in active if movable[r]), key=lambda r: -loads[r])
            receivers = sorted(active, key=lambda r: loads[r])
            moved = False
            for donor in donors:
                recv = next((r for r in receivers if r != donor and loads[donor] - loads[r] >= 2), None)
                if recv is None:
                    continue
                for iid in list(movable[donor]):
                    meta = await self._lock.get_item_meta(bank_id, iid)
                    if not zone_allows(meta.get("zone"), zones.get(recv)):
                        continue
                    if await self._lock.transfer(iid, donor, recv, cts_config):
                        movable[donor].remove(iid)
                        loads[donor] -= 1
                        loads[recv] += 1
                        result.moves.append((iid, donor, recv))
                        moved = True
                        break
                if moved:
                    break
            if not moved:
                break
        if result.moves:
            log.info("allocation.rebalanced", bank_id=bank_id, moves=len(result.moves))
        return result
