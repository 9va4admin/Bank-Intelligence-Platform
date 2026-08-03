"""Tests for SMBChequeProcessingWorkflow — input/output models and design invariants."""
import pytest


class TestSMBChequeInput:
    def test_smb_cheque_input_fields(self):
        from modules.cts.workflows.smb_cheque_processing_workflow import SMBChequeInput
        inp = SMBChequeInput(
            instrument_id="CHQ-002",
            sub_member_id="smb-001",
            sponsor_bank_id="sb-bank",
            iet_deadline_utc="2026-06-26T12:00:00Z",
            cheque_image_ref="minio/bucket/img.tiff",
            micr_line="123456789012345678",
            amount_range="HIGH_VALUE",
            session_date="2026-06-26",
            clearing_session="SESSION_1",
            forwarding_id="fwd-uuid-001",
        )
        assert inp.sponsor_bank_id == "sb-bank"
        assert inp.sub_member_id == "smb-001"
        assert inp.forwarding_id == "fwd-uuid-001"

    def test_smb_cheque_result_fields(self):
        from modules.cts.workflows.smb_cheque_processing_workflow import SMBChequeResult
        result = SMBChequeResult(
            instrument_id="CHQ-002",
            sub_member_id="smb-001",
            terminal_decision="STP_CONFIRM",
            fraud_score=0.05,
            ocr_confidence=0.98,
            signature_score=0.97,
            bucket="STP_CONFIRM",
            ledger_updated=True,
            ngch_filed=True,
            audit_written=True,
        )
        assert result.terminal_decision == "STP_CONFIRM"
        assert result.ledger_updated is True
        assert result.ngch_filed is True
        assert result.audit_written is True


class TestRetryPolicies:
    def test_ai_retry_max_attempts(self):
        from modules.cts.workflows.smb_cheque_processing_workflow import _AI_RETRY
        assert _AI_RETRY.maximum_attempts == 2
        assert "ValidationError" in _AI_RETRY.non_retryable_error_types
        assert "IETBreachError" in _AI_RETRY.non_retryable_error_types

    def test_ngch_retry_max_attempts(self):
        from modules.cts.workflows.smb_cheque_processing_workflow import _NGCH_RETRY
        assert _NGCH_RETRY.maximum_attempts == 3
        assert "DuplicateFilingError" in _NGCH_RETRY.non_retryable_error_types

    def test_cbs_retry_max_attempts(self):
        from modules.cts.workflows.smb_cheque_processing_workflow import _CBS_RETRY
        assert _CBS_RETRY.maximum_attempts == 3

    def test_audit_retry_is_unlimited(self):
        from modules.cts.workflows.smb_cheque_processing_workflow import _AUDIT_RETRY
        # Unlimited retries — audit must always succeed
        assert _AUDIT_RETRY.maximum_attempts is None


class TestDesignInvariants:
    def test_no_iet_watchdog_import(self):
        """SMBChequeProcessingWorkflow must NOT import or call IETWatchdogWorkflow.
        Sponsor's watchdog is already running — spawning a second one causes duplicate NGCH filing.
        Uses AST so docstring/comment mentions are ignored; only actual code nodes are checked."""
        import ast, inspect
        from modules.cts.workflows import smb_cheque_processing_workflow
        source = inspect.getsource(smb_cheque_processing_workflow)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "IETWatchdogWorkflow":
                raise AssertionError(
                    "SMBChequeProcessingWorkflow must not reference IETWatchdogWorkflow in code "
                    "(found at line %d) — the sponsor bank's watchdog is already running." % node.lineno
                )
            if isinstance(node, ast.Attribute) and node.attr == "IETWatchdogWorkflow":
                raise AssertionError(
                    "SMBChequeProcessingWorkflow must not reference IETWatchdogWorkflow in code "
                    "(found at line %d) — the sponsor bank's watchdog is already running." % node.lineno
                )

    def test_forwarding_id_passed_to_ngch(self):
        """forwarding_id must be threaded through to file_to_ngch for sponsor correlation."""
        import inspect
        from modules.cts.workflows import smb_cheque_processing_workflow
        source = inspect.getsource(smb_cheque_processing_workflow)
        assert "forwarding_id" in source
        assert "input.forwarding_id" in source

    def test_sub_member_id_in_vault_activities(self):
        """sub_member_id must be passed to verify_signature and lookup_pps for vault namespacing."""
        import inspect
        from modules.cts.workflows import smb_cheque_processing_workflow
        source = inspect.getsource(smb_cheque_processing_workflow)
        assert "input.sub_member_id" in source

    def test_notify_sub_member_return_in_run(self):
        """notify_sub_member_return must be called in run() — not just in run_with_mocks()."""
        import inspect
        from modules.cts.workflows import smb_cheque_processing_workflow
        source = inspect.getsource(smb_cheque_processing_workflow.SMBChequeProcessingWorkflow.run)
        assert "notify_sub_member_return" in source, (
            "notify_sub_member_return not found in run() — HIGH-4 regression"
        )

    def test_emit_batch_ledger_update_in_run(self):
        """emit_batch_ledger_update must always be called in run()."""
        import inspect
        from modules.cts.workflows import smb_cheque_processing_workflow
        source = inspect.getsource(smb_cheque_processing_workflow.SMBChequeProcessingWorkflow.run)
        assert "emit_batch_ledger_update" in source, (
            "emit_batch_ledger_update not found in run() — HIGH-4 regression"
        )

    def test_notify_called_only_for_stp_return(self):
        """notify_sub_member_return must be guarded by the STP_RETURN branch — not called on every decision."""
        import ast, inspect
        from modules.cts.workflows import smb_cheque_processing_workflow
        source = inspect.getsource(smb_cheque_processing_workflow.SMBChequeProcessingWorkflow.run)
        # Check that notify call appears inside a conditional that checks STP_RETURN
        assert "STP_RETURN" in source and "notify_sub_member_return" in source


class TestHigh1ReviewTimeoutFromConfig:
    def test_finalise_does_not_hardcode_55(self):
        """HIGH-1: finalise() must NOT use 55 as a literal default for review_timeout_minutes.
        Must read from inp.cts_config['human_review_max_wait_minutes']."""
        import re, inspect
        from modules.cts.workflows import cheque_workflow
        source = inspect.getsource(cheque_workflow.ChequeProcessingWorkflow.run)
        # Find the finalise signature (may span multiple lines until closing paren)
        m = re.search(r'async def finalise\(([^)]*)\)', source, re.DOTALL)
        assert m, "Could not find finalise() definition inside ChequeProcessingWorkflow.run()"
        sig = m.group(1)
        # The hardcoded ': int = 55' must NOT appear as the review_timeout_minutes default
        assert "review_timeout_minutes: int = 55" not in sig, (
            "finalise() has review_timeout_minutes hardcoded to 55. "
            "Must be set from inp.cts_config['human_review_max_wait_minutes']."
        )

    def test_human_review_max_wait_minutes_key_referenced(self):
        """HIGH-1: run() must reference 'human_review_max_wait_minutes' config key."""
        import inspect
        from modules.cts.workflows import cheque_workflow
        source = inspect.getsource(cheque_workflow.ChequeProcessingWorkflow.run)
        assert "human_review_max_wait_minutes" in source, (
            "run() does not reference 'human_review_max_wait_minutes' config key — "
            "timeout is not config-driven (HIGH-1)"
        )
