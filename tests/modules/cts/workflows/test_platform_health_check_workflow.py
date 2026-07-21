"""
Tests for modules/cts/workflows/platform_health_check_workflow.py
and modules/cts/workflows/activities/platform_health_activities.py

PlatformHealthCheckWorkflow — 60s cadence alert engine.
Checks IET near-breach count + human review queue depth + avg wait.
On threshold breach → dispatch_platform_alert → dispatcher.py → WhatsApp + email.

Activity rules:
  - All activities degrade gracefully (db_pool/dispatcher=None → no crash)
  - IET near-breach > 0 → always P0 alert (never debounced)
  - Human review queue / wait → WARN at configurable thresholds
  - dispatch_platform_alert degrades when dispatcher is None

Workflow rules:
  - @workflow.defn on class
  - @workflow.run on run() method
  - run_with_mocks() orchestrates the same logic testably
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


# ── Activity: check_iet_risk_for_alert ────────────────────────────────────────

class TestCheckIETRisk:

    def test_import(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            check_iet_risk_for_alert,
        )
        assert callable(check_iet_risk_for_alert)

    @pytest.mark.asyncio
    async def test_degraded_when_db_none(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            CheckIETInput, check_iet_risk_for_alert,
        )
        result = await check_iet_risk_for_alert(
            CheckIETInput(bank_id="test-bank"), db_pool=None
        )
        assert result.degraded is True
        assert result.needs_alert is False
        assert result.near_breach_count == 0

    @pytest.mark.asyncio
    async def test_no_breach_no_alert(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            CheckIETInput, check_iet_risk_for_alert,
        )
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            "near_breach": 0,
            "in_processing": 42,
        })
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))
        result = await check_iet_risk_for_alert(
            CheckIETInput(bank_id="test-bank"), db_pool=mock_pool
        )
        assert result.needs_alert is False
        assert result.near_breach_count == 0
        assert result.in_processing_count == 42
        assert result.degraded is False

    @pytest.mark.asyncio
    async def test_near_breach_triggers_alert(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            CheckIETInput, check_iet_risk_for_alert,
        )
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            "near_breach": 3,
            "in_processing": 150,
        })
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))
        result = await check_iet_risk_for_alert(
            CheckIETInput(bank_id="test-bank"), db_pool=mock_pool
        )
        assert result.needs_alert is True
        assert result.near_breach_count == 3
        assert result.alert_priority == "P0"

    @pytest.mark.asyncio
    async def test_db_error_degrades_gracefully(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            CheckIETInput, check_iet_risk_for_alert,
        )
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(side_effect=Exception("DB timeout")),
            __aexit__=AsyncMock(return_value=False),
        ))
        result = await check_iet_risk_for_alert(
            CheckIETInput(bank_id="test-bank"), db_pool=mock_pool
        )
        assert result.degraded is True
        assert result.needs_alert is False


# ── Activity: check_human_review_for_alert ────────────────────────────────────

class TestCheckHumanReview:

    def test_import(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            check_human_review_for_alert,
        )
        assert callable(check_human_review_for_alert)

    @pytest.mark.asyncio
    async def test_degraded_when_db_none(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            CheckHRInput, check_human_review_for_alert,
        )
        result = await check_human_review_for_alert(
            CheckHRInput(bank_id="test-bank", max_depth=50, max_wait_minutes=45.0),
            db_pool=None,
        )
        assert result.degraded is True
        assert result.needs_alert is False

    @pytest.mark.asyncio
    async def test_below_threshold_no_alert(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            CheckHRInput, check_human_review_for_alert,
        )
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            "queue_depth": 10,
            "avg_wait": 8.5,
        })
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))
        result = await check_human_review_for_alert(
            CheckHRInput(bank_id="test-bank", max_depth=50, max_wait_minutes=45.0),
            db_pool=mock_pool,
        )
        assert result.needs_alert is False
        assert result.queue_depth == 10

    @pytest.mark.asyncio
    async def test_depth_above_threshold_triggers_warn(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            CheckHRInput, check_human_review_for_alert,
        )
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            "queue_depth": 65,
            "avg_wait": 12.0,
        })
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))
        result = await check_human_review_for_alert(
            CheckHRInput(bank_id="test-bank", max_depth=50, max_wait_minutes=45.0),
            db_pool=mock_pool,
        )
        assert result.needs_alert is True
        assert result.alert_severity == "WARN"
        assert result.alert_reason == "QUEUE_DEPTH"

    @pytest.mark.asyncio
    async def test_wait_above_threshold_triggers_warn(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            CheckHRInput, check_human_review_for_alert,
        )
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={
            "queue_depth": 5,
            "avg_wait": 60.0,
        })
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))
        result = await check_human_review_for_alert(
            CheckHRInput(bank_id="test-bank", max_depth=50, max_wait_minutes=45.0),
            db_pool=mock_pool,
        )
        assert result.needs_alert is True
        assert result.alert_severity == "WARN"
        assert result.alert_reason == "WAIT_TIME"

    @pytest.mark.asyncio
    async def test_db_error_degrades_gracefully(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            CheckHRInput, check_human_review_for_alert,
        )
        mock_pool = AsyncMock()
        mock_pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(side_effect=Exception("connection refused")),
            __aexit__=AsyncMock(return_value=False),
        ))
        result = await check_human_review_for_alert(
            CheckHRInput(bank_id="test-bank", max_depth=50, max_wait_minutes=45.0),
            db_pool=mock_pool,
        )
        assert result.degraded is True
        assert result.needs_alert is False


# ── Activity: dispatch_platform_alert ─────────────────────────────────────────

class TestDispatchPlatformAlert:

    def test_import(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            dispatch_platform_alert,
        )
        assert callable(dispatch_platform_alert)

    @pytest.mark.asyncio
    async def test_no_dispatcher_degrades_gracefully(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            DispatchAlertInput, dispatch_platform_alert,
        )
        result = await dispatch_platform_alert(
            DispatchAlertInput(
                bank_id="test-bank",
                event_type="IET_BREACH_RISK",
                severity="CRITICAL",
                priority="P0",
                message="IET breach risk: 3 cheques",
            ),
            dispatcher=None,
        )
        assert result.sent is False
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_with_dispatcher_sends_notification(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            DispatchAlertInput, dispatch_platform_alert,
        )
        mock_dispatcher = AsyncMock()
        mock_dispatcher.send = AsyncMock(return_value={"status": "sent", "message_id": "msg-001"})
        result = await dispatch_platform_alert(
            DispatchAlertInput(
                bank_id="test-bank",
                event_type="IET_BREACH_RISK",
                severity="CRITICAL",
                priority="P0",
                message="IET breach risk: 3 cheques within 30s of deadline",
            ),
            dispatcher=mock_dispatcher,
        )
        assert result.sent is True
        assert mock_dispatcher.send.called

    @pytest.mark.asyncio
    async def test_p0_alert_uses_p0_priority(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            DispatchAlertInput, dispatch_platform_alert,
        )
        from shared.notifications.dispatcher import NotificationRequest
        mock_dispatcher = AsyncMock()
        sent_requests = []

        async def capture_send(req):
            sent_requests.append(req)
            return {"status": "sent"}

        mock_dispatcher.send = capture_send
        await dispatch_platform_alert(
            DispatchAlertInput(
                bank_id="test-bank",
                event_type="IET_BREACH_RISK",
                severity="CRITICAL",
                priority="P0",
                message="3 cheques near breach",
            ),
            dispatcher=mock_dispatcher,
        )
        # P0 must be set in the request so debouncer never suppresses it
        assert any(r.priority == "P0" for r in sent_requests)

    @pytest.mark.asyncio
    async def test_dispatcher_error_degrades_gracefully(self):
        from modules.cts.workflows.activities.platform_health_activities import (
            DispatchAlertInput, dispatch_platform_alert,
        )
        mock_dispatcher = AsyncMock()
        mock_dispatcher.send = AsyncMock(side_effect=Exception("whatsapp API down"))
        result = await dispatch_platform_alert(
            DispatchAlertInput(
                bank_id="test-bank",
                event_type="HUMAN_REVIEW_QUEUE_DEEP",
                severity="WARN",
                priority="P1",
                message="Queue depth 65",
            ),
            dispatcher=mock_dispatcher,
        )
        assert result.sent is False


# ── Workflow structure ─────────────────────────────────────────────────────────

class TestWorkflowDecorators:

    def test_workflow_defn_present(self):
        import inspect
        from modules.cts.workflows.platform_health_check_workflow import (
            PlatformHealthCheckWorkflow,
        )
        assert inspect.isclass(PlatformHealthCheckWorkflow)
        assert hasattr(PlatformHealthCheckWorkflow, "__temporal_workflow_definition")

    def test_run_method_has_workflow_run(self):
        from modules.cts.workflows.platform_health_check_workflow import (
            PlatformHealthCheckWorkflow,
        )
        run = getattr(PlatformHealthCheckWorkflow, "run", None)
        assert run is not None
        assert hasattr(run, "__temporal_workflow_run")


# ── run_with_mocks() orchestration ────────────────────────────────────────────

class TestRunWithMocks:

    @pytest.mark.asyncio
    async def test_no_breach_sends_no_alert(self):
        from modules.cts.workflows.platform_health_check_workflow import (
            PlatformHealthCheckWorkflow, PlatformHealthInput,
        )
        wf = PlatformHealthCheckWorkflow()
        dispatched = []
        result = await wf.run_with_mocks(
            PlatformHealthInput(bank_id="test-bank", max_hr_depth=50, max_hr_wait_minutes=45.0),
            mock_results={
                "iet_risk":    {"near_breach_count": 0, "in_processing_count": 10, "needs_alert": False, "degraded": False},
                "human_review": {"queue_depth": 8, "avg_wait_minutes": 5.0, "needs_alert": False, "degraded": False},
                "dispatched":  dispatched,
            },
        )
        assert len(dispatched) == 0
        assert result.checks_run == 2

    @pytest.mark.asyncio
    async def test_iet_breach_sends_p0_alert(self):
        from modules.cts.workflows.platform_health_check_workflow import (
            PlatformHealthCheckWorkflow, PlatformHealthInput,
        )
        wf = PlatformHealthCheckWorkflow()
        dispatched = []
        result = await wf.run_with_mocks(
            PlatformHealthInput(bank_id="test-bank", max_hr_depth=50, max_hr_wait_minutes=45.0),
            mock_results={
                "iet_risk":    {"near_breach_count": 3, "in_processing_count": 100, "needs_alert": True, "alert_priority": "P0", "degraded": False},
                "human_review": {"queue_depth": 8, "avg_wait_minutes": 5.0, "needs_alert": False, "degraded": False},
                "dispatched":  dispatched,
            },
        )
        assert any(d["priority"] == "P0" for d in dispatched)
        assert any(d["event_type"] == "IET_BREACH_RISK" for d in dispatched)

    @pytest.mark.asyncio
    async def test_human_review_queue_sends_warn_alert(self):
        from modules.cts.workflows.platform_health_check_workflow import (
            PlatformHealthCheckWorkflow, PlatformHealthInput,
        )
        wf = PlatformHealthCheckWorkflow()
        dispatched = []
        result = await wf.run_with_mocks(
            PlatformHealthInput(bank_id="test-bank", max_hr_depth=50, max_hr_wait_minutes=45.0),
            mock_results={
                "iet_risk":    {"near_breach_count": 0, "needs_alert": False, "degraded": False},
                "human_review": {"queue_depth": 65, "avg_wait_minutes": 12.0, "needs_alert": True, "alert_severity": "WARN", "alert_reason": "QUEUE_DEPTH", "degraded": False},
                "dispatched":  dispatched,
            },
        )
        assert any(d["severity"] == "WARN" for d in dispatched)

    @pytest.mark.asyncio
    async def test_both_degraded_sends_no_alert(self):
        from modules.cts.workflows.platform_health_check_workflow import (
            PlatformHealthCheckWorkflow, PlatformHealthInput,
        )
        wf = PlatformHealthCheckWorkflow()
        dispatched = []
        await wf.run_with_mocks(
            PlatformHealthInput(bank_id="test-bank", max_hr_depth=50, max_hr_wait_minutes=45.0),
            mock_results={
                "iet_risk":    {"needs_alert": False, "degraded": True},
                "human_review": {"needs_alert": False, "degraded": True},
                "dispatched":  dispatched,
            },
        )
        assert len(dispatched) == 0

    @pytest.mark.asyncio
    async def test_checks_run_count(self):
        from modules.cts.workflows.platform_health_check_workflow import (
            PlatformHealthCheckWorkflow, PlatformHealthInput,
        )
        wf = PlatformHealthCheckWorkflow()
        result = await wf.run_with_mocks(
            PlatformHealthInput(bank_id="test-bank", max_hr_depth=50, max_hr_wait_minutes=45.0),
            mock_results={
                "iet_risk":    {"needs_alert": False, "degraded": False},
                "human_review": {"needs_alert": False, "degraded": False},
                "dispatched":  [],
            },
        )
        assert result.checks_run == 2
