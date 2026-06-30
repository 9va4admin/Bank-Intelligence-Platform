"""
Tests for modules/ej/workflows/atm_health_workflow.py

Scheduled hourly workflow: analyse ATM health signals, detect anomalies,
predict failures, send alert if threshold crossed.
Terminal states: HEALTHY | DEGRADED | CRITICAL
"""
import pytest

from modules.ej.workflows.atm_health_workflow import (
    ATMHealthInput,
    ATMHealthResult,
    ATMHealthWorkflow,
)


class TestATMHealthInput:
    def test_input_fields(self):
        inp = ATMHealthInput(bank_id="test-bank", atm_id="ATM001")
        assert inp.bank_id == "test-bank"
        assert inp.atm_id == "ATM001"

    def test_input_is_frozen(self):
        inp = ATMHealthInput(bank_id="test-bank", atm_id="ATM001")
        with pytest.raises(Exception):
            inp.bank_id = "other"


class TestATMHealthResult:
    def test_result_fields(self):
        r = ATMHealthResult(outcome="HEALTHY", bank_id="test-bank", atm_id="ATM001")
        assert r.outcome == "HEALTHY"
        assert r.bank_id == "test-bank"
        assert r.atm_id == "ATM001"

    def test_result_is_frozen(self):
        r = ATMHealthResult(outcome="HEALTHY", bank_id="test-bank", atm_id="ATM001")
        with pytest.raises(Exception):
            r.outcome = "DEGRADED"

    def test_result_has_anomaly_count(self):
        r = ATMHealthResult(outcome="HEALTHY", bank_id="test-bank", atm_id="ATM001", anomaly_count=0)
        assert r.anomaly_count == 0

    def test_result_anomaly_count_defaults_zero(self):
        r = ATMHealthResult(outcome="HEALTHY", bank_id="test-bank", atm_id="ATM001")
        assert r.anomaly_count == 0

    def test_result_has_alert_sent_flag(self):
        r = ATMHealthResult(outcome="CRITICAL", bank_id="test-bank", atm_id="ATM001", alert_sent=True)
        assert r.alert_sent is True

    def test_alert_sent_defaults_false(self):
        r = ATMHealthResult(outcome="HEALTHY", bank_id="test-bank", atm_id="ATM001")
        assert r.alert_sent is False


class TestATMHealthWorkflow:
    def test_workflow_id_format(self):
        wf = ATMHealthWorkflow()
        wid = wf.workflow_id("test-bank", "ATM001")
        assert wid == "ej-atm-health-test-bank-ATM001"

    @pytest.mark.asyncio
    async def test_healthy_when_no_anomalies(self):
        wf = ATMHealthWorkflow()
        result = await wf.run_with_mocks(
            inp=ATMHealthInput(bank_id="test-bank", atm_id="ATM001"),
            mock_results={
                "analyse_health": {"anomaly_count": 0, "anomaly_types": []},
                "predict_failure": {"risk_level": "LOW", "days_to_failure": None},
            },
        )
        assert result.outcome == "HEALTHY"
        assert result.anomaly_count == 0
        assert result.alert_sent is False

    @pytest.mark.asyncio
    async def test_degraded_when_anomalies_detected(self):
        wf = ATMHealthWorkflow()
        result = await wf.run_with_mocks(
            inp=ATMHealthInput(bank_id="test-bank", atm_id="ATM001"),
            mock_results={
                "analyse_health": {"anomaly_count": 2, "anomaly_types": ["DISPENSE_ERROR", "TIMEOUT"]},
                "predict_failure": {"risk_level": "MEDIUM", "days_to_failure": 14},
            },
        )
        assert result.outcome == "DEGRADED"
        assert result.anomaly_count == 2

    @pytest.mark.asyncio
    async def test_critical_when_high_risk(self):
        wf = ATMHealthWorkflow()
        result = await wf.run_with_mocks(
            inp=ATMHealthInput(bank_id="test-bank", atm_id="ATM001"),
            mock_results={
                "analyse_health": {"anomaly_count": 5, "anomaly_types": ["CASH_JAM", "DISPENSE_ERROR", "TIMEOUT"]},
                "predict_failure": {"risk_level": "HIGH", "days_to_failure": 2},
            },
        )
        assert result.outcome == "CRITICAL"

    @pytest.mark.asyncio
    async def test_alert_sent_on_critical(self):
        wf = ATMHealthWorkflow()
        result = await wf.run_with_mocks(
            inp=ATMHealthInput(bank_id="test-bank", atm_id="ATM001"),
            mock_results={
                "analyse_health": {"anomaly_count": 5, "anomaly_types": ["CASH_JAM"]},
                "predict_failure": {"risk_level": "HIGH", "days_to_failure": 1},
                "send_alert": {"sent": True, "channel": "whatsapp"},
            },
        )
        assert result.alert_sent is True

    @pytest.mark.asyncio
    async def test_alert_sent_on_degraded(self):
        wf = ATMHealthWorkflow()
        result = await wf.run_with_mocks(
            inp=ATMHealthInput(bank_id="test-bank", atm_id="ATM001"),
            mock_results={
                "analyse_health": {"anomaly_count": 2, "anomaly_types": ["DISPENSE_ERROR"]},
                "predict_failure": {"risk_level": "MEDIUM", "days_to_failure": 7},
                "send_alert": {"sent": True, "channel": "email"},
            },
        )
        assert result.alert_sent is True

    @pytest.mark.asyncio
    async def test_no_alert_on_healthy(self):
        wf = ATMHealthWorkflow()
        result = await wf.run_with_mocks(
            inp=ATMHealthInput(bank_id="test-bank", atm_id="ATM001"),
            mock_results={
                "analyse_health": {"anomaly_count": 0, "anomaly_types": []},
                "predict_failure": {"risk_level": "LOW", "days_to_failure": None},
            },
        )
        assert result.alert_sent is False

    @pytest.mark.asyncio
    async def test_bank_id_preserved_in_result(self):
        wf = ATMHealthWorkflow()
        result = await wf.run_with_mocks(
            inp=ATMHealthInput(bank_id="hdfc-bank", atm_id="ATM001"),
            mock_results={
                "analyse_health": {"anomaly_count": 0, "anomaly_types": []},
                "predict_failure": {"risk_level": "LOW", "days_to_failure": None},
            },
        )
        assert result.bank_id == "hdfc-bank"

    @pytest.mark.asyncio
    async def test_atm_id_preserved_in_result(self):
        wf = ATMHealthWorkflow()
        result = await wf.run_with_mocks(
            inp=ATMHealthInput(bank_id="test-bank", atm_id="ATM999"),
            mock_results={
                "analyse_health": {"anomaly_count": 0, "anomaly_types": []},
                "predict_failure": {"risk_level": "LOW", "days_to_failure": None},
            },
        )
        assert result.atm_id == "ATM999"
