# API Rules (FastAPI Backend)

## Structure
- All routers in `apps/api/routers/` — one file per module (cts.py, ej.py, disputes.py, audit.py, admin.py)
- All Pydantic v2 models — use `model_config = ConfigDict(...)` not class Config
- Async throughout — all route handlers must be `async def`
- No business logic in routers — delegate to service layer or Temporal workflow trigger

## Request / Response Patterns
- Every response model must be a typed Pydantic model — no `dict` returns
- Pagination: `limit` (max 100) + `cursor` (UUIDv7-based, not offset)
- Error responses: `{"error_code": "CTS_VAULT_MISS", "message": "...", "request_id": "..."}`
- All responses include `X-Request-Id` header (OTel trace ID)

## Authentication
- All routes require JWT from bank's IdP (SAML-issued) — no exceptions
- RBAC check via `shared/auth/rbac.py` dependency injection
- Route `/health` and `/metrics` exempt from auth (Kubernetes probes)

## Rate Limiting
- CTS submission endpoints: 600 req/min per bank_id
- EJ ingestion: 100 req/min per branch
- Admin endpoints: 30 req/min per user

## OpenTelemetry
- Every route handler gets automatic OTel span via middleware
- Add custom attributes: `bank_id`, `module`, `operation` to every span
- Never use `print()` — structured logging via `structlog` with OTel context injection
