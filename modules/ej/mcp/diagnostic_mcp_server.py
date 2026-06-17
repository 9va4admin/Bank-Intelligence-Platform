"""
ASTRA Diagnostic MCP Server
Exposes non-PII operational signals to ASTRA support — with bank consent only.
Deployed inside bank's cluster. OPA policy gates every tool call.
"""
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import Tool, TextContent
from pydantic import BaseModel
from datetime import datetime, timedelta
import structlog

from shared.config.config_service import config_service
from shared.audit.immudb_client import immudb_client
from shared.audit.audit_event import AuditEvent

log = structlog.get_logger()
server = Server("astra-diagnostic-mcp")


class DiagnosticSession(BaseModel):
    session_id: str
    bank_id: str
    support_ticket: str
    allowed_tools: list[str]
    allowed_services: list[str]
    approved_by: str
    expires_at: datetime


async def validate_session(token: str, tool_name: str) -> DiagnosticSession:
    """Validate session token via OPA. Raises if invalid, expired, or revoked."""
    opa_url = config_service.get("opa.url")
    # OPA evaluates: valid token + tool in scope + not expired + not revoked
    response = await opa_client.evaluate(
        policy="astra/diagnostic/allow_tool",
        input={"session_token": token, "tool_name": tool_name},
    )
    if not response.get("allow_tool"):
        raise PermissionError(f"Diagnostic session denied for tool: {tool_name}")
    return DiagnosticSession.model_validate(response["session_scope"])


async def log_diagnostic_access(session: DiagnosticSession, tool: str, params: dict, row_count: int):
    """Every tool call logged to Immudb — bank can audit what ASTRA pulled."""
    event = AuditEvent(
        event_type="DIAGNOSTIC_ACCESS",
        bank_id=session.bank_id,
        actor=f"astra-support:{session.support_ticket}",
        payload={
            "session_id": session.session_id,
            "tool_called": tool,
            "tool_params": params,        # params are safe — never contain PII
            "response_row_count": row_count,
            "approved_by": session.approved_by,
            "session_expires_at": session.expires_at.isoformat(),
        }
    )
    await immudb_client.write(event)   # fire-and-forget


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_error_summary",
            description="Non-PII error counts and codes per service per time window",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_token": {"type": "string"},
                    "service": {"type": "string"},
                    "window_minutes": {"type": "integer", "maximum": 1440},
                },
                "required": ["session_token", "service", "window_minutes"],
            },
        ),
        Tool(
            name="get_service_health",
            description="Pod counts, CPU/memory, Kafka lag, Redis hit rate — no PII",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_token": {"type": "string"},
                    "services": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["session_token", "services"],
            },
        ),
        Tool(
            name="get_workflow_failures",
            description="Temporal workflow failure counts by type — no workflow content or IDs",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_token": {"type": "string"},
                    "workflow_type": {"type": "string"},
                    "window_minutes": {"type": "integer", "maximum": 1440},
                },
                "required": ["session_token", "workflow_type", "window_minutes"],
            },
        ),
        Tool(
            name="get_queue_depths",
            description="Kafka consumer lag and Temporal queue depths",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_token": {"type": "string"},
                },
                "required": ["session_token"],
            },
        ),
        Tool(
            name="get_model_drift_signals",
            description="AI model performance drift over time window — histograms only, no per-cheque data",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_token": {"type": "string"},
                    "model": {"type": "string"},
                    "window_days": {"type": "integer", "maximum": 30},
                },
                "required": ["session_token", "model", "window_days"],
            },
        ),
        Tool(
            name="get_iet_risk_events",
            description="Count of IET near-breach events — no instrument IDs or account data",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_token": {"type": "string"},
                    "window_hours": {"type": "integer", "maximum": 24},
                },
                "required": ["session_token", "window_hours"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    token = arguments.pop("session_token")

    # Validate session and OPA policy for every call
    session = await validate_session(token, name)

    result = {}

    if name == "get_error_summary":
        service = arguments["service"]
        if service not in session.allowed_services:
            raise PermissionError(f"Service {service} not in session scope")

        # Query Loki for error counts only — never return raw log lines
        error_counts = await loki_client.query_error_counts(
            service=service,
            window_minutes=arguments["window_minutes"],
            bank_id=session.bank_id,
        )
        result = {
            "service": service,
            "window_minutes": arguments["window_minutes"],
            "error_counts": error_counts,         # {"CTS_VAULT_MISS": 12, ...}
            # Raw log lines NEVER included — only aggregated counts
        }

    elif name == "get_workflow_failures":
        failure_counts = await temporal_client.get_failure_summary(
            workflow_type=arguments["workflow_type"],
            window_minutes=arguments["window_minutes"],
            bank_id=session.bank_id,
        )
        result = {
            "workflow_type": arguments["workflow_type"],
            "failure_breakdown": failure_counts,  # {"ACTIVITY_TIMEOUT:ocr_extract": 2}
            # No workflow IDs, no instrument IDs, no payload content
        }

    elif name == "get_iet_risk_events":
        count = await prometheus_client.query_iet_near_breach_count(
            window_hours=arguments["window_hours"],
            bank_id=session.bank_id,
        )
        result = {
            "iet_near_breach_count": count,
            "window_hours": arguments["window_hours"],
            # Count only — no instrument IDs, no account numbers
        }

    # Audit every call — bank sees everything ASTRA pulled
    await log_diagnostic_access(session, name, arguments, row_count=len(result))

    import json
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
