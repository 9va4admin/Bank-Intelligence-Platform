"""Who may make or check an outward decision.

Three models for the maker, chosen per bank (cts.outward_maker_scope):
  CENTRAL       only central staff (users with no branch assignment). The default, and what every reviewer was before
                branch assignments existed.
  BRANCH        only staff assigned to the item's branch.
  BRANCH_FIRST  the item's branch staff at once; central staff too once the item has waited
                cts.outward_branch_first_fallback_minutes, so work never sticks if a branch has nobody on.
The checker (cts.outward_checker_scope) is ANY reviewer other than the maker, or CENTRAL staff only.
A user's branch assignment lives on the user (branch_ids); an empty list means central staff.
"""
from __future__ import annotations

from typing import Optional

MAKER_SCOPES = ("CENTRAL", "BRANCH", "BRANCH_FIRST")
CHECKER_SCOPES = ("ANY", "CENTRAL")


def maker_scope(cfg: dict) -> str:
    value = str(cfg.get("outward_maker_scope") or "CENTRAL").upper()
    return value if value in MAKER_SCOPES else "CENTRAL"


def maker_allowed(cfg: dict, user_branch_ids: Optional[list], item_branch_id: Optional[str], item_age_seconds: float) -> bool:
    branches = list(user_branch_ids or [])
    central = not branches
    scope = maker_scope(cfg)
    if scope == "CENTRAL":
        return central
    at_branch = bool(item_branch_id) and item_branch_id in branches
    if scope == "BRANCH":
        return at_branch
    fallback = max(0, int(cfg.get("outward_branch_first_fallback_minutes", 10))) * 60      # BRANCH_FIRST
    return at_branch or (central and float(item_age_seconds or 0.0) >= fallback)


def checker_allowed(cfg: dict, user_branch_ids: Optional[list]) -> bool:
    value = str(cfg.get("outward_checker_scope") or "ANY").upper()
    if value == "CENTRAL":
        return not list(user_branch_ids or [])
    return True
