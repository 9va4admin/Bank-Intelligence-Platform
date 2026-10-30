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

Buckets (when cts.bucket_routing_enabled): every item belongs to a bucket (HVC, CA, IP, LVC, FCC, SIP_SUCCESS,
SIP_REJECT, HR or MISC). A reviewer works only the buckets an admin connected them to; auto-assignment, claim, admin
assign and rebalancing all stay inside the item's bucket. MISC is self-claim only (never auto-assigned). Releasing a
claim, or no active subscriber for a bucket within bucket_overflow_after_minutes, moves the item to MISC and remembers
its origin_bucket. With routing off the bucket is informational and allocation is the flat pool described above.

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
MISC = "MISC"


def _routing(cts_config: dict) -> bool:
    return bool(cts_config.get("bucket_routing_enabled", False))


def bucket_allows(item_bucket: Optional[str], reviewer_buckets: Optional[list[str]]) -> bool:
    """True if a reviewer connected to reviewer_buckets may work an item in item_bucket (None = unrestricted)."""
    if reviewer_buckets is None or not item_bucket or item_bucket == MISC:
        return True
    return item_bucket in reviewer_buckets


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
    def __init__(self, lock_service, subscriptions=None) -> None:
        self._lock = lock_service
        self._subs = subscriptions

    # ------------------------------------------------------------------ claim / unclaim

    async def claim(
        self, instrument_id: str, reviewer_id: str, cts_config: dict,
        bank_id: Optional[str] = None, reviewer_zones: Optional[list[str]] = None,
        reviewer_buckets: Optional[list[str]] = None,
    ) -> AllocationResult:
        """Reviewer manually claims (or re-opens) an instrument.

        Works in all three modes (UI always shows the Claim button; backend enforces semantics). In AUTO mode the
        claim is still honoured: a human override of the auto-assignment is always permitted, and claiming an item
        you already hold counts as opening it, which pins it so the rebalancer never moves it.
        A reviewer scoped to a clearing zone cannot claim an item from another zone.
        """
        if bank_id and (reviewer_zones is not None or (reviewer_buckets is not None and _routing(cts_config))):
            meta = await self._lock.get_item_meta(bank_id, instrument_id)
            if reviewer_zones is not None and not zone_allows(meta.get("zone"), reviewer_zones):
                log.info("allocation.claim_refused_zone", instrument_id=instrument_id, reviewer_id=reviewer_id)
                return AllocationResult(claimed=False, reason="ZONE_RESTRICTED")
            if _routing(cts_config) and not bucket_allows(meta.get("bucket"), reviewer_buckets):
                log.info("allocation.claim_refused_bucket", instrument_id=instrument_id, reviewer_id=reviewer_id,
                         bucket=meta.get("bucket"))
                return AllocationResult(claimed=False, reason="NOT_SUBSCRIBED")

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
        if bank_id and _routing(cts_config):
            await self.move_to_misc(bank_id, instrument_id)       # a de-allocated item goes to MISC
        log.info(
            "allocation.unclaimed",
            instrument_id=instrument_id,
            reviewer_id=reviewer_id,
        )

    # ------------------------------------------------------------------ buckets

    async def move_to_misc(self, bank_id: str, instrument_id: str) -> None:
        """Put an item in MISC, remembering the bucket it came from (an item already in MISC keeps its origin)."""
        meta = await self._lock.get_item_meta(bank_id, instrument_id)
        current = meta.get("bucket")
        if current == MISC:
            return
        await self._lock.update_item_meta(bank_id, instrument_id, bucket=MISC, origin_bucket=current)
        await self._lock.unmark_auto(bank_id, instrument_id)
        log.info("allocation.moved_to_misc", instrument_id=instrument_id, origin_bucket=current)

    async def overflow_if_stale(self, bank_id: str, instrument_id: str, cts_config: dict) -> bool:
        """Move an unclaimed item to MISC when nobody connected to its bucket is logged in and it has waited
        bucket_overflow_after_minutes. Returns True if it moved."""
        if not _routing(cts_config) or self._subs is None:
            return False
        meta = await self._lock.get_item_meta(bank_id, instrument_id)
        bucket, queued_at = meta.get("bucket"), meta.get("queued_at")
        if not bucket or bucket == MISC or not queued_at:
            return False
        if await self._lock.get_lock_holder(instrument_id) is not None:
            return False
        waited = _time.time() - float(queued_at)
        if waited < float(cts_config.get("bucket_overflow_after_minutes", 10)) * 60:
            return False
        subscribers = set(await self._subs.get_subscribers(bank_id, bucket))
        if subscribers & set(await self._lock.get_active_reviewers(bank_id)):
            return False                      # someone who works this bucket is here: keep it where they will see it
        await self.move_to_misc(bank_id, instrument_id)
        return True

    async def can_take(self, bank_id: str, instrument_id: str, reviewer_id: str, cts_config: dict) -> bool:
        """May this reviewer be given this item (admin assign)? Inside the item's bucket, or MISC."""
        if not _routing(cts_config) or self._subs is None:
            return True
        meta = await self._lock.get_item_meta(bank_id, instrument_id)
        return bucket_allows(meta.get("bucket"), await self._subs.get_reviewer_buckets(bank_id, reviewer_id))

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

        if bank_id and _routing(cts_config):
            if (await self._lock.get_item_meta(bank_id, instrument_id)).get("bucket") == MISC:
                return AllocationResult(claimed=False, reason="MISC_SELF_CLAIM")   # people claim from MISC themselves

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
        if _routing(cts_config) and self._subs is not None and meta.get("bucket"):
            subscribers = set(await self._subs.get_subscribers(bank_id, meta["bucket"]))
            eligible = [r for r in eligible if r in subscribers]
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
        by_bucket = await self._subs.get_all(bank_id) if (_routing(cts_config) and self._subs is not None) else None
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
                # Try each receiver in load order: the least-loaded one may not be allowed to take any of this
                # donor's items (zone, or not connected to the bucket), so the next one gets a chance.
                for recv in (r for r in receivers if r != donor and loads[donor] - loads[r] >= 2):
                    for iid in list(movable[donor]):
                        meta = await self._lock.get_item_meta(bank_id, iid)
                        if not zone_allows(meta.get("zone"), zones.get(recv)):
                            continue
                        if by_bucket is not None and meta.get("bucket") not in (None, MISC)                                 and recv not in by_bucket.get(meta["bucket"], []):
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
                if moved:
                    break
            if not moved:
                break
        if result.moves:
            log.info("allocation.rebalanced", bank_id=bank_id, moves=len(result.moves))
        return result
