"""
Alert routing API (docs/design/alerting-1b-plan.md, step 6): the routing policies, the "who would be told" simulator, and the channel status.

All routes under /v1/admin/alert-routing/. Read: ops_manager, bank_it_admin, compliance_officer. Propose: ops_manager, bank_it_admin. Approve or reject: bank_it_admin,
and never the person who proposed it (maker-checker). Policies can name external addresses; every address in a response is masked.
"""
import json
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from apps.api.dependencies import require_user_context
from shared.alerting.audience import deliverable_targets
from shared.alerting.audit import mask_recipient
from shared.alerting.factory import build_routing_service
from shared.alerting.policy_defaults import build_default_bank_policy
from shared.alerting.proofs import ProofStore
from shared.alerting.policy_store import PolicyInvalid, PolicyNotPending, PolicyRecord, PolicyStore, SameUserError
from shared.alerting.routing_policy import LEVELS, IncidentFacts, Policy
from shared.auth.rbac import UserContext
from shared.messages import get_message
from shared.utils.masking import mask_email, mask_phone

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/admin/alert-routing", tags=["Alert routing v1"])

_READ_ROLES = frozenset({"ops_manager", "bank_it_admin", "compliance_officer"})
_PROPOSE_ROLES = frozenset({"ops_manager", "bank_it_admin"})
_APPROVE_ROLES = frozenset({"bank_it_admin"})
Level = Literal["BANK", "PU", "SMB"]
HISTORY_LIMIT = 20


async def get_current_user(ctx: UserContext = Depends(require_user_context)) -> dict[str, Any]:
    return {"bank_id": ctx.bank_id, "user_id": ctx.user_id, "role": ctx.role.value}


def _require(roles: frozenset, message_key: str):
    def check(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=get_message(message_key))
        return user
    return check


require_read = _require(_READ_ROLES, "ALERT_API_ROLE_CANNOT_READ")
require_propose = _require(_PROPOSE_ROLES, "ALERT_API_ROLE_CANNOT_CHANGE_ROUTING")
require_approve = _require(_APPROVE_ROLES, "ALERT_API_ROLE_CANNOT_APPROVE_ROUTING")


# ── Models ───────────────────────────────────────────────────────────────────

class ProposeRequest(BaseModel):
    level: Level
    scope_id: Optional[str] = None
    policy: Policy
    note: Optional[str] = None


class DecisionRequest(BaseModel):
    note: Optional[str] = None


class ActivePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    policy: Policy
    record: PolicyRecord


class PolicyView(BaseModel):
    model_config = ConfigDict(frozen=True)
    active: Optional[ActivePolicy] = None
    pending: list[PolicyRecord] = []
    history: list[PolicyRecord] = []
    used_default: bool = False
    default_policy: Optional[Policy] = None      # what is in force when the bank has no policy of its own


class PendingResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    pending: list[PolicyRecord] = []


class ScopesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    scopes: list[PolicyRecord] = []


class SimulateRequest(BaseModel):
    severity: Literal["P0", "P1", "P2", "P3"]
    component: str = ""
    owning_team: str = ""
    pu_id: Optional[str] = None
    smb_id: Optional[str] = None
    at: Optional[datetime] = None


class SimTarget(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str
    ref: str                                     # an address or phone is masked
    channels: list[str]


class SimDelivery(BaseModel):
    model_config = ConfigDict(frozen=True)
    channel: str
    recipient_ref: str


class SimStep(BaseModel):
    model_config = ConfigDict(frozen=True)
    level: int
    after_minutes: int
    targets: list[SimTarget]
    deliveries: list[SimDelivery]


class SimMatched(BaseModel):
    model_config = ConfigDict(frozen=True)
    level: str
    rule_id: str


class SimulationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    matched: list[SimMatched] = []
    steps: list[SimStep] = []
    repeat_minutes: Optional[int] = None
    held: bool = False
    warnings: list[str] = []
    used_default: bool = False


class EmailStatus(BaseModel):
    model_config = ConfigDict(frozen=True)
    configured: bool
    host: Optional[str] = None
    port: Optional[int] = None
    security: Optional[str] = None
    from_address: Optional[str] = None
    public_provider: bool = False                # a public provider is a pilot-only arrangement


class SimpleStatus(BaseModel):
    model_config = ConfigDict(frozen=True)
    configured: bool


class ChannelsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    email: EmailStatus
    whatsapp: SimpleStatus
    bell: SimpleStatus
    email_recipients: int = 0
    whatsapp_recipients: int = 0


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pool(request: Request) -> Any:
    pool = getattr(request.app.state, "db_pool_cts", None)
    if pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=get_message("ALERT_API_DB_UNAVAILABLE"))
    return pool


async def _store(request: Request, bank_id: str) -> PolicyStore:
    config = request.app.state.config_service
    try:
        key = await config.get_secret(f"banks.{bank_id}.pii_enc_key")
    except Exception:
        key = None
    if not key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=get_message("ALERT_API_POLICY_STORE_UNAVAILABLE"))
    return PolicyStore(_pool(request), pii_key=key, auditor=getattr(request.app.state, "alert_auditor", None))


def _mask(ref: str) -> str:
    if "@" in ref:
        return mask_email(ref)
    digits = "".join(c for c in ref if c.isdigit())
    return mask_phone(ref) if ref.startswith("+") and len(digits) >= 8 else ref


def _int_list(raw: Any) -> list[str]:
    parsed = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("[") else raw
    items = parsed if isinstance(parsed, list) else (str(parsed).split(",") if parsed else [])
    return [str(x).strip() for x in items if str(x).strip()]


# ── Policies ─────────────────────────────────────────────────────────────────

@router_v1.get("/policies", response_model=PolicyView)
async def get_policies(request: Request, level: Level = "BANK", scope_id: Optional[str] = Query(None, max_length=80), user: dict = Depends(require_read)) -> PolicyView:
    bank_id = user["bank_id"]
    store = await _store(request, bank_id)
    scope = scope_id or None
    active_policy = await store.get_active(bank_id, level, scope)
    record = await store.active_record(bank_id, level, scope) if active_policy else None
    pending = [p for p in await store.list_pending(bank_id) if p.scope_level == level and p.scope_id == scope]
    history = await store.history(bank_id, level, scope, limit=HISTORY_LIMIT)
    used_default = level == "BANK" and active_policy is None
    default = await build_default_bank_policy(request.app.state.config_service) if used_default else None
    return PolicyView(active=ActivePolicy(policy=active_policy, record=record) if active_policy and record else None, pending=pending, history=history,
                      used_default=used_default, default_policy=default)


class PolicyDetail(BaseModel):
    model_config = ConfigDict(frozen=True)
    record: PolicyRecord
    policy: Policy


@router_v1.get("/policies/{policy_id}", response_model=PolicyDetail)
async def get_policy(request: Request, policy_id: str, user: dict = Depends(require_read)) -> PolicyDetail:
    found = await (await _store(request, user["bank_id"])).get_by_id(user["bank_id"], policy_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=get_message("ALERT_API_POLICY_NOT_FOUND"))
    return PolicyDetail(record=found[0], policy=found[1])


@router_v1.get("/pending", response_model=PendingResponse)
async def get_pending(request: Request, user: dict = Depends(require_read)) -> PendingResponse:
    return PendingResponse(pending=await (await _store(request, user["bank_id"])).list_pending(user["bank_id"]))


@router_v1.get("/scopes", response_model=ScopesResponse)
async def get_scopes(request: Request, user: dict = Depends(require_read)) -> ScopesResponse:
    return ScopesResponse(scopes=await (await _store(request, user["bank_id"])).list_active(user["bank_id"]))


@router_v1.post("/policies", response_model=PolicyRecord, status_code=status.HTTP_201_CREATED)
async def propose_policy(request: Request, body: ProposeRequest, user: dict = Depends(require_propose)) -> PolicyRecord:
    store = await _store(request, user["bank_id"])
    try:
        return await store.propose(user["bank_id"], body.level, body.scope_id or None, body.policy, proposed_by=user["user_id"], note=body.note)
    except PolicyInvalid as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"message": get_message("ALERT_API_POLICY_INVALID"), "codes": exc.codes})


async def _decide(request: Request, policy_id: str, user: dict, approve: bool, note: Optional[str] = None) -> PolicyRecord:
    store = await _store(request, user["bank_id"])
    try:
        if approve:
            return await store.approve(user["bank_id"], policy_id, approved_by=user["user_id"])
        return await store.reject(user["bank_id"], policy_id, rejected_by=user["user_id"], note=note)
    except SameUserError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=get_message("ALERT_API_SAME_USER"))
    except PolicyNotPending:
        if await store.get_record(user["bank_id"], policy_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=get_message("ALERT_API_POLICY_NOT_FOUND"))
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=get_message("ALERT_API_POLICY_NOT_PENDING"))


@router_v1.post("/policies/{policy_id}/approve", response_model=PolicyRecord)
async def approve_policy(request: Request, policy_id: str, user: dict = Depends(require_approve)) -> PolicyRecord:
    return await _decide(request, policy_id, user, True)


@router_v1.post("/policies/{policy_id}/reject", response_model=PolicyRecord)
async def reject_policy(request: Request, policy_id: str, body: Optional[DecisionRequest] = None, user: dict = Depends(require_approve)) -> PolicyRecord:
    return await _decide(request, policy_id, user, False, body.note if body else None)


# ── Simulator ────────────────────────────────────────────────────────────────

@router_v1.post("/simulate", response_model=SimulationResponse)
async def simulate(request: Request, body: SimulateRequest, user: dict = Depends(require_read)) -> SimulationResponse:
    """Who would be told for an incident like this, and when it would escalate. Sends nothing."""
    bank_id, pool, config = user["bank_id"], _pool(request), request.app.state.config_service
    routing = build_routing_service(config, bank_id, pool)
    at = (body.at or datetime.now(timezone.utc))
    routed = await routing.route_facts(IncidentFacts(severity=body.severity, component=body.component, owning_team=body.owning_team, pu_id=body.pu_id, smb_id=body.smb_id), at)
    steps: list[SimStep] = []
    for step in routed.routing.steps:
        deliveries, _warnings = await deliverable_targets(step.targets, pool=pool, config_service=config, bank_id=bank_id)
        steps.append(SimStep(level=step.level, after_minutes=step.after_minutes,
                             targets=[SimTarget(kind=t.kind, ref=_mask(t.ref), channels=t.channels) for t in step.targets],
                             deliveries=[SimDelivery(channel=d.channel, recipient_ref=mask_recipient(d.recipient, d.channel)) for d in deliveries]))
    response = SimulationResponse(matched=[SimMatched(level=m.level, rule_id=m.rule_id) for m in routed.routing.matched], steps=steps, repeat_minutes=routed.routing.repeat_minutes,
                                  held=routed.routing.held, warnings=routed.routing.warnings, used_default=routed.used_default)
    await _record_simulation(pool, bank_id, user, body, response)
    return response


async def _record_simulation(pool: Any, bank_id: str, user: dict, body: SimulateRequest, response: SimulationResponse) -> None:
    """Keep a record of the run for the Go-Live check: what was asked, which rules matched, how many people would be told at once. No address or phone is stored.
    A problem recording it never stops the answer."""
    if body.severity not in ("P0", "P1", "P2"):
        return
    first_step = len(response.steps[0].deliveries) if response.steps else 0
    try:
        await ProofStore(pool).record(bank_id, f"simulation_{body.severity}", first_step > 0 or response.held,
                                      {"severity": body.severity, "component": body.component, "pu_id": body.pu_id, "smb_id": body.smb_id,
                                       "matched": [m.rule_id for m in response.matched], "recipients": first_step, "held": response.held, "used_default": response.used_default},
                                      str(user.get("user_id", "")))
    except Exception as exc:  # noqa: BLE001
        log.warning("alert_routing.simulation_not_recorded", bank_id=bank_id, error_type=type(exc).__name__)


# ── Channel status ───────────────────────────────────────────────────────────

@router_v1.get("/channels", response_model=ChannelsResponse)
async def channels(request: Request, user: dict = Depends(require_read)) -> ChannelsResponse:
    """What can carry an alert on this deployment. Never returns a password or token."""
    config = request.app.state.config_service

    def platform(key: str) -> Optional[str]:
        try:
            value = config.get_platform(key)
            return value.strip() if isinstance(value, str) and value.strip() else None
        except Exception:
            return None

    async def setting(key: str, default: Any = None) -> Any:
        try:
            return await config.get(key)
        except Exception:
            return default
    host = platform("smtp.host")
    public_hosts = [h.lower() for h in _int_list(await setting("alerting.public_mail_hosts", []))] or ["smtp.gmail.com", "smtp.office365.com", "smtp-mail.outlook.com"]
    port = platform("smtp.port")
    email = EmailStatus(configured=host is not None, host=host, port=int(port) if port and port.isdigit() else None, security=platform("smtp.security") if host else None,
                        from_address=(platform("smtp.from_address") or platform("smtp.username")) if host else None,
                        public_provider=bool(host and host.lower() in public_hosts))
    whatsapp = bool(platform("whatsapp.api_url") and platform("whatsapp.phone_number_id"))
    return ChannelsResponse(email=email, whatsapp=SimpleStatus(configured=whatsapp), bell=SimpleStatus(configured=getattr(request.app.state, "db_pool_cts", None) is not None),
                            email_recipients=len(_int_list(await setting("alerts.email_recipients", ""))),
                            whatsapp_recipients=len(_int_list(await setting("alerts.whatsapp_recipients", ""))))
