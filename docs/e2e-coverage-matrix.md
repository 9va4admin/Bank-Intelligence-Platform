# ASTRA — E2E coverage matrix (generated)

_Generated 2026-09-21 20:00 by `scripts/gen_e2e_coverage.py` from the evidence files in `docs/evidence/`._

**How to read this:** `RAN LIVE` = the name appears in a Temporal history captured from a real run. `NOT RUN LIVE` = registered on the worker but no captured real run executed it. Unit tests (which use fake activities) are not counted. Activities stubbed in the AI-stubbed load test are not counted as real for that file.

## Workflows
| Workflow | Status | Evidence |
|---|---|---|
| `AgencyCCWorkflow` | NOT RUN LIVE | — |
| `BatchEndorsementWorkflow` | NOT RUN LIVE | — |
| `ChequeProcessingWorkflow` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `ClearingSessionWorkflow` | NOT RUN LIVE | — |
| `DeltaVaultSyncWorkflow` | NOT RUN LIVE | — |
| `FeedbackAccumulatorWorkflow` | NOT RUN LIVE | — |
| `FeedbackEmitWorkflow` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `HoldEscalationWorkflow` | NOT RUN LIVE | — |
| `HumanReviewWorkflow` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `IETWatchdogWorkflow` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `InwardBatchIngestionWorkflow` | NOT RUN LIVE | — |
| `MSVValidationWorkflow` | NOT RUN LIVE | — |
| `MismatchResolutionWorkflow` | **RAN LIVE** | `outward_real_run_19_cheques.json` |
| `ModelRetrainWorkflow` | NOT RUN LIVE | — |
| `NGCHSubmissionWorkflow` | NOT RUN LIVE | — |
| `OutwardScanWorkflow` | **RAN LIVE** | `outward_real_run_19_cheques.json` |
| `PlatformHealthCheckWorkflow` | NOT RUN LIVE | — |
| `PostDatedHoldWorkflow` | **RAN LIVE** | `outward_real_run_19_cheques.json` |
| `SBInwardForwardingWorkflow` | NOT RUN LIVE | — |
| `SMBChequeProcessingWorkflow` | NOT RUN LIVE | — |
| `SMBForwardingWorkflow` | NOT RUN LIVE | — |
| `SMBVaultPushWorkflow` | NOT RUN LIVE | — |
| `SessionReconciliationWorkflow` | NOT RUN LIVE | — |
| `VaultFileDropWorkflow` | NOT RUN LIVE | — |
| `VaultSyncWorkflow` | NOT RUN LIVE | — |

## Activities — 24 ran live, 67 not run live (of 91 registered)

| Activity | Status | Evidence files |
|---|---|---|
| `accumulate_corpus_entry` | NOT RUN LIVE | — |
| `archive_drop_file` | NOT RUN LIVE | — |
| `build_and_upload_ngch_files` | NOT RUN LIVE | — |
| `build_lot_package` | NOT RUN LIVE | — |
| `build_ngch_file` | NOT RUN LIVE | — |
| `check_account_status` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `check_cbs_balance` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `check_cheque_dedup` | **RAN LIVE** | `outward_real_run_19_cheques.json` |
| `check_human_review_for_alert` | NOT RUN LIVE | — |
| `check_iet_risk_for_alert` | NOT RUN LIVE | — |
| `check_outward_payee` | NOT RUN LIVE | — |
| `check_retrain_threshold` | NOT RUN LIVE | — |
| `check_return_rate_shield` | NOT RUN LIVE | — |
| `check_security_features` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `check_stop_payment` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `check_vault_redis_coverage_for_alert` | NOT RUN LIVE | — |
| `confirm_acknowledgement` | NOT RUN LIVE | — |
| `create_lot_entry` | NOT RUN LIVE | — |
| `cross_check_ngch_metadata` | **RAN LIVE** | `outward_real_run_19_cheques.json` |
| `detect_alteration` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `detect_signatures` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `dispatch_platform_alert` | NOT RUN LIVE | — |
| `dispatch_retrain_job` | NOT RUN LIVE | — |
| `emit_batch_ledger_update` | NOT RUN LIVE | — |
| `emit_micr_feedback_signal` | NOT RUN LIVE | — |
| `emit_payee_feedback_signal` | NOT RUN LIVE | — |
| `extract_rear_payee_details` | **RAN LIVE** | `outward_real_run_19_cheques.json` |
| `fetch_delta_canceled_leaves` | NOT RUN LIVE | — |
| `fetch_delta_stop_payments` | NOT RUN LIVE | — |
| `fetch_drop_file` | NOT RUN LIVE | — |
| `fetch_ngch_settlement_report` | NOT RUN LIVE | — |
| `file_to_ngch` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `generate_rrf` | NOT RUN LIVE | — |
| `get_kill_switch_status` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `insert_inward_instrument` | NOT RUN LIVE | — |
| `load_pps_from_cbs` | NOT RUN LIVE | — |
| `load_signatures_from_cbs` | NOT RUN LIVE | — |
| `lookup_pps` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `mark_hold_cancelled` | NOT RUN LIVE | — |
| `mark_leaf_paid` | NOT RUN LIVE | — |
| `mark_leaf_presented` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `mark_leaf_returned` | NOT RUN LIVE | — |
| `match_submitted_vs_settled` | NOT RUN LIVE | — |
| `notify_sub_member_return` | NOT RUN LIVE | — |
| `ocr_extract` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `orchestrate_msv_validation` | NOT RUN LIVE | — |
| `parse_and_validate_smb_push` | NOT RUN LIVE | — |
| `parse_inward_batch` | NOT RUN LIVE | — |
| `persist_agent_decision` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `persist_mismatch_hold_db` | NOT RUN LIVE | — |
| `process_vault_csv` | NOT RUN LIVE | — |
| `promote_model` | NOT RUN LIVE | — |
| `publish_mismatch_hold` | NOT RUN LIVE | — |
| `publish_relay_event` | NOT RUN LIVE | — |
| `publish_to_pu_queues` | NOT RUN LIVE | — |
| `push_to_review_queue` | NOT RUN LIVE | — |
| `record_outward_scan_event` | **RAN LIVE** | `outward_real_run_19_cheques.json` |
| `resolve_crl_batch` | NOT RUN LIVE | — |
| `resolve_mismatch_db` | NOT RUN LIVE | — |
| `run_shadow_evaluation` | NOT RUN LIVE | — |
| `run_vision_presentment_check` | **RAN LIVE** | `outward_real_run_19_cheques.json` |
| `sb_submit_lot` | NOT RUN LIVE | — |
| `score_fraud` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `seal_all_lots` | NOT RUN LIVE | — |
| `send_hold_critical_alert` | NOT RUN LIVE | — |
| `send_hold_p0_alert` | NOT RUN LIVE | — |
| `send_hold_reminder` | NOT RUN LIVE | — |
| `stamp_endorsement` | NOT RUN LIVE | — |
| `store_postdated_hold` | NOT RUN LIVE | — |
| `submit_to_ngch` | NOT RUN LIVE | — |
| `sweep_stuck_workflows` | NOT RUN LIVE | — |
| `sync_signatories_from_cbs` | NOT RUN LIVE | — |
| `synthesise_decision` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `update_bloom_filter` | NOT RUN LIVE | — |
| `update_lot_status` | NOT RUN LIVE | — |
| `update_session_status` | NOT RUN LIVE | — |
| `update_smb_vault` | NOT RUN LIVE | — |
| `upload_instrument_images` | NOT RUN LIVE | — |
| `validate_cheque_series` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `validate_cts2010` | **RAN LIVE** | `outward_real_run_19_cheques.json` |
| `validate_ifsc` | NOT RUN LIVE | — |
| `validate_payee_account` | **RAN LIVE** | `outward_real_run_19_cheques.json` |
| `validate_smb_forwarding_window` | NOT RUN LIVE | — |
| `verify_signature` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `verify_vault_integrity` | NOT RUN LIVE | — |
| `vision_extract_and_check` | NOT RUN LIVE | — |
| `warm_redis_vault` | NOT RUN LIVE | — |
| `write_audit` | **RAN LIVE** | `inward_real_run_20_at_once.json`, `inward_real_run_4_at_a_time.json` |
| `write_forwarding_log_complete` | NOT RUN LIVE | — |
| `write_forwarding_log_start` | NOT RUN LIVE | — |
| `write_smb_forwarding_audit` | NOT RUN LIVE | — |

## Workflows/activities registered but never run live — summary

Workflows: `AgencyCCWorkflow`, `BatchEndorsementWorkflow`, `ClearingSessionWorkflow`, `DeltaVaultSyncWorkflow`, `FeedbackAccumulatorWorkflow`, `HoldEscalationWorkflow`, `InwardBatchIngestionWorkflow`, `MSVValidationWorkflow`, `ModelRetrainWorkflow`, `NGCHSubmissionWorkflow`, `PlatformHealthCheckWorkflow`, `SBInwardForwardingWorkflow`, `SMBChequeProcessingWorkflow`, `SMBForwardingWorkflow`, `SMBVaultPushWorkflow`, `SessionReconciliationWorkflow`, `VaultFileDropWorkflow`, `VaultSyncWorkflow`

Activities: `accumulate_corpus_entry`, `archive_drop_file`, `build_and_upload_ngch_files`, `build_lot_package`, `build_ngch_file`, `check_human_review_for_alert`, `check_iet_risk_for_alert`, `check_outward_payee`, `check_retrain_threshold`, `check_return_rate_shield`, `check_vault_redis_coverage_for_alert`, `confirm_acknowledgement`, `create_lot_entry`, `dispatch_platform_alert`, `dispatch_retrain_job`, `emit_batch_ledger_update`, `emit_micr_feedback_signal`, `emit_payee_feedback_signal`, `fetch_delta_canceled_leaves`, `fetch_delta_stop_payments`, `fetch_drop_file`, `fetch_ngch_settlement_report`, `generate_rrf`, `insert_inward_instrument`, `load_pps_from_cbs`, `load_signatures_from_cbs`, `mark_hold_cancelled`, `mark_leaf_paid`, `mark_leaf_returned`, `match_submitted_vs_settled`, `notify_sub_member_return`, `orchestrate_msv_validation`, `parse_and_validate_smb_push`, `parse_inward_batch`, `persist_mismatch_hold_db`, `process_vault_csv`, `promote_model`, `publish_mismatch_hold`, `publish_relay_event`, `publish_to_pu_queues`, `push_to_review_queue`, `resolve_crl_batch`, `resolve_mismatch_db`, `run_shadow_evaluation`, `sb_submit_lot`, `seal_all_lots`, `send_hold_critical_alert`, `send_hold_p0_alert`, `send_hold_reminder`, `stamp_endorsement`, `store_postdated_hold`, `submit_to_ngch`, `sweep_stuck_workflows`, `sync_signatories_from_cbs`, `update_bloom_filter`, `update_lot_status`, `update_session_status`, `update_smb_vault`, `upload_instrument_images`, `validate_ifsc`, `validate_smb_forwarding_window`, `verify_vault_integrity`, `vision_extract_and_check`, `warm_redis_vault`, `write_forwarding_log_complete`, `write_forwarding_log_start`, `write_smb_forwarding_audit`
