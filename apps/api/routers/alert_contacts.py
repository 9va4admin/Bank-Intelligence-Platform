"""
Alert contacts API: the outside addresses and phone numbers alerts may be sent to, each verified by a code sent to it. All routes under /v1/admin/alert-contacts/.
Read: ops_manager, bank_it_admin, compliance_officer. Add, send a code, verify, remove: ops_manager, bank_it_admin.
An address is never returned (lists show it masked) and a code is never returned: it goes only to the address it verifies.
"""
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.dependencies import require_user_context
from shared.alerting.contacts import Contact, ContactInvalid, ContactStore
from shared.audit.audit_event import AuditEventType
from shared.auth.rbac import UserContext
from shared.messages import get_message
from shared.notifications.dispatcher import NotificationRequest

log = structlog.get_logger()
router_v1 = APIRouter(prefix="/v1/admin/alert-contacts", tags=["Alert contacts v1"])

_READ_ROLES = frozenset({"ops_manager", "bank_it_admin", "compliance_officer"})
_WRITE_ROLES = frozenset({"ops_manager", "bank_it_admin"})
_REFUSAL_KEYS = {"invalid_email": "ALERT_API_CONTACT_INVALID_EMAIL", "invalid_phone": "ALERT_API_CONTACT_INVALID_PHONE", "invalid_kind": "ALERT_API_CONTACT_INVALID_KIND",
                 "duplicate": "ALERT_API_CONTACT_DUPLICATE"}


async def get_current_user(ctx: UserContext = Depends(require_user_context)) -> dict[str, Any]:
    return {"bank_id": ctx.bank_id, "user_id": ctx.user_id, "role": ctx.role.value}


def _require(roles: frozenset, message_key: str):
    def check(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=get_message(message_key))
        return user
    return check


require_read = _require(_READ_ROLES, "ALERT_API_ROLE_CANNOT_READ")
require_write = _require(_WRITE_ROLES, "ALERT_API_ROLE_CANNOT_CHANGE_CONTACTS")


class AddRequest(BaseModel):
    kind: Literal["email", "phone"] = Field(...)
    address: str = Field(..., max_length=200)
    label: str = Field("", max_length=80)


class CodeRequest(BaseModel):
    code: str = Field(..., max_length=20)


class ContactsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    contacts: list[Contact]


class AddedResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    contact: Contact
    sent: bool


class SentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    sent: bool


class VerifyResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    ok: bool
    reason: str


async def _store(request: Request, bank_id: str) -> ContactStore:
    pool = getattr(request.app.state, "db_pool_cts", None)
    config = request.app.state.config_service
    if pool is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=get_message("ALERT_API_DB_UNAVAILABLE"))
    try:
        key = await config.get_secret(f"banks.{bank_id}.pii_enc_key")
        pepper = await config.get_secret(f"banks.{bank_id}.pii_hash_pepper")
    except Exception:  # noqa: BLE001
        key = pepper = None
    if not key or not pepper:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=get_message("ALERT_API_POLICY_STORE_UNAVAILABLE"))

    async def number(name: str, default: int) -> int:
        try:
            return int(await config.get(name))
        except Exception:  # noqa: BLE001
            return default
    return ContactStore(pool, pii_key=key, pepper=pepper, code_ttl_minutes=await number("alerting.contact_code_ttl_minutes", 15),
                        max_attempts=await number("alerting.contact_code_max_attempts", 5))


async def _audit(request: Request, bank_id: str, contact_id: str, actor: str, action: str, kind: str) -> None:
    """An audit event for the change; it names the contact by its id and the kind, never the address."""
    auditor = getattr(request.app.state, "alert_auditor", None)
    if auditor is not None:
        await auditor.lifecycle(AuditEventType.ALERT_CONTACT_CHANGED, bank_id=bank_id, incident_id=f"contact:{contact_id}", actor=actor, detail={"action": action, "kind": kind})


async def _send_code(request: Request, bank_id: str, kind: str, address: str, code: str, minutes: int) -> bool:
    """Send the code to the address it verifies. False when there is no way to send or the send failed (the contact is kept)."""
    dispatcher = getattr(request.app.state, "alert_dispatcher", None)
    if dispatcher is None:
        return False
    text = get_message("ALERT_CONTACT_CODE_MESSAGE", code=code, minutes=minutes)
    try:
        await dispatcher.send(NotificationRequest(
            channel="email" if kind == "email" else "whatsapp", recipient=address, template_id="PLATFORM_HEALTH_ALERT", priority="P0",
            context={"bank_id": bank_id, "event_type": "CONTACT_VERIFICATION", "severity": "INFO", "component": "contact-verification", "message": text, "priority": "P0"}))
    except Exception as exc:  # noqa: BLE001
        log.warning("alert_contacts.code_not_sent", bank_id=bank_id, kind=kind, error_type=type(exc).__name__)
        return False
    return True


def _ttl(store: ContactStore) -> int:
    return store._ttl  # noqa: SLF001  - the same value the code was issued with


@router_v1.get("", response_model=ContactsResponse)
async def list_contacts(request: Request, user: dict = Depends(require_read)) -> ContactsResponse:
    return ContactsResponse(contacts=await (await _store(request, user["bank_id"])).list(user["bank_id"]))


@router_v1.post("", response_model=AddedResponse, status_code=status.HTTP_201_CREATED)
async def add_contact(request: Request, body: AddRequest, user: dict = Depends(require_write)) -> AddedResponse:
    bank_id = user["bank_id"]
    store = await _store(request, bank_id)
    try:
        contact, code = await store.add(bank_id, body.kind, body.address, body.label, user["user_id"])
    except ContactInvalid as exc:
        code_status = status.HTTP_409_CONFLICT if exc.code == "duplicate" else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=code_status, detail=get_message(_REFUSAL_KEYS.get(exc.code, "ALERT_API_CONTACT_INVALID_KIND")))
    await _audit(request, bank_id, contact.contact_id, user["user_id"], "added", body.kind)
    sent = await _send_code(request, bank_id, body.kind, body.address.strip().lower() if body.kind == "email" else body.address.strip(), code, _ttl(store))
    return AddedResponse(contact=contact, sent=sent)


@router_v1.post("/{contact_id}/send-code", response_model=SentResponse)
async def send_code(contact_id: str, request: Request, user: dict = Depends(require_write)) -> SentResponse:
    bank_id = user["bank_id"]
    store = await _store(request, bank_id)
    code = await store.issue_code(bank_id, contact_id)
    address = await store.address(bank_id, contact_id) if code else None
    if code is None or address is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=get_message("ALERT_API_CONTACT_NOT_FOUND"))
    kind = "email" if "@" in address else "phone"
    await _audit(request, bank_id, contact_id, user["user_id"], "code_sent", kind)
    return SentResponse(sent=await _send_code(request, bank_id, kind, address, code, _ttl(store)))


@router_v1.post("/{contact_id}/verify", response_model=VerifyResponse)
async def verify(contact_id: str, body: CodeRequest, request: Request, user: dict = Depends(require_write)) -> VerifyResponse:
    bank_id = user["bank_id"]
    result = await (await _store(request, bank_id)).verify(bank_id, contact_id, body.code, user["user_id"])
    if result.reason == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=get_message("ALERT_API_CONTACT_NOT_FOUND"))
    if result.ok:
        await _audit(request, bank_id, contact_id, user["user_id"], "verified", "")
    return VerifyResponse(ok=result.ok, reason=result.reason)


@router_v1.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove(contact_id: str, request: Request, user: dict = Depends(require_write)) -> Response:
    bank_id = user["bank_id"]
    if not await (await _store(request, bank_id)).remove(bank_id, contact_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=get_message("ALERT_API_CONTACT_NOT_FOUND"))
    await _audit(request, bank_id, contact_id, user["user_id"], "removed", "")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
