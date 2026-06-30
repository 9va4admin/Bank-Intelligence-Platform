"""
Tests for modules/ej/worker.py

Verifies the worker registers all required workflows and activities.
"""
import pytest

from modules.ej.worker import ALL_WORKFLOWS, ALL_ACTIVITIES


class TestEJWorkerRegistrations:
    def test_all_workflows_registered(self):
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow
        from modules.ej.workflows.dispute_workflow import DisputeResolutionWorkflow
        from modules.ej.workflows.atm_health_workflow import ATMHealthWorkflow
        assert EJNormalisationWorkflow in ALL_WORKFLOWS
        assert DisputeResolutionWorkflow in ALL_WORKFLOWS
        assert ATMHealthWorkflow in ALL_WORKFLOWS

    def test_all_8_normalisation_activities_registered(self):
        from modules.ej.workflows.activities.ingest import ingest_ej_log
        from modules.ej.workflows.activities.fingerprint import validate_oem_fingerprint
        from modules.ej.workflows.activities.llm_parse import llm_parse_ej
        from modules.ej.workflows.activities.validate import validate_ej_canonical
        from modules.ej.workflows.activities.store_canonical import store_canonical
        from modules.ej.workflows.activities.trigger_dispute_check import trigger_dispute_check
        from modules.ej.workflows.activities.update_atm_health import update_atm_health
        from modules.ej.workflows.activities.write_audit import write_audit

        for fn in [
            ingest_ej_log, validate_oem_fingerprint, llm_parse_ej, validate_ej_canonical,
            store_canonical, trigger_dispute_check, update_atm_health, write_audit,
        ]:
            assert fn in ALL_ACTIVITIES, f"{fn.__name__} not in ALL_ACTIVITIES"

    def test_dispute_activities_registered(self):
        from modules.ej.workflows.activities.dispute_match import match_dispute_to_ej
        from modules.ej.workflows.activities.cctv_extract import extract_cctv_evidence
        assert match_dispute_to_ej in ALL_ACTIVITIES
        assert extract_cctv_evidence in ALL_ACTIVITIES

    def test_task_queue_prefix(self):
        from modules.ej.worker import TASK_QUEUE_PREFIX
        assert TASK_QUEUE_PREFIX == "ej-normalisation"
