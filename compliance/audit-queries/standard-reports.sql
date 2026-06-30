-- ASTRA Standard Audit Reports
-- Used by: compliance_officer, rbi_examiner (time-scoped read-only access)
-- All queries enforce bank_id isolation and RBAC-scoped date ranges.
-- PII fields masked at query level — full values never returned in reports.
-- Source: compliance/rbi-it-framework/control-mapping.yaml — AUD-01, AUD-02, AUD-03

-- ============================================================
-- REPORT 1: CTS Decision Summary (Daily / Weekly / Monthly)
-- RBI Control: AUD-01, CTS-01
-- ============================================================
-- Usage: replace :bank_id, :from_ts, :to_ts with parameterised values
SELECT
    DATE_TRUNC('day', ad.decided_at)                        AS decision_date,
    ad.decision_outcome,
    COUNT(*)                                                 AS count,
    AVG(EXTRACT(EPOCH FROM (ad.decided_at - ci.received_at)) * 1000)::INT AS avg_decision_ms,
    MAX(EXTRACT(EPOCH FROM (ad.decided_at - ci.received_at)) * 1000)::INT AS max_decision_ms,
    SUM(CASE WHEN ad.iet_breach THEN 1 ELSE 0 END)          AS iet_breach_count,
    SUM(CASE WHEN ad.degraded_mode THEN 1 ELSE 0 END)       AS degraded_mode_count
FROM cts.agent_decisions ad
JOIN cts.cheque_instruments ci ON ci.instrument_id = ad.instrument_id
WHERE ci.bank_id = :bank_id
  AND ad.decided_at BETWEEN :from_ts AND :to_ts
GROUP BY DATE_TRUNC('day', ad.decided_at), ad.decision_outcome
ORDER BY decision_date DESC, count DESC;

-- ============================================================
-- REPORT 2: IET Near-Breach Events (Safety Audit)
-- RBI Control: CTS-01 — 0.000% IET breach target
-- ============================================================
SELECT
    ci.instrument_id,
    ci.received_at,
    ci.iet_deadline,
    ad.decided_at,
    EXTRACT(EPOCH FROM (ci.iet_deadline - ad.decided_at))::INT AS seconds_before_iet,
    ad.decision_outcome,
    ad.iet_breach,
    ad.watchdog_fired
FROM cts.cheque_instruments ci
JOIN cts.agent_decisions ad ON ad.instrument_id = ci.instrument_id
WHERE ci.bank_id = :bank_id
  AND ci.received_at BETWEEN :from_ts AND :to_ts
  AND (
      ad.iet_breach = TRUE
      OR EXTRACT(EPOCH FROM (ci.iet_deadline - ad.decided_at)) < 30
  )
ORDER BY seconds_before_iet ASC;
-- NOTE: Any row with iet_breach = TRUE is a compliance incident.
-- Target: zero rows with iet_breach = TRUE in any audit period.

-- ============================================================
-- REPORT 3: Human Review Queue Audit
-- RBI Control: AUD-01, CTS-01
-- ============================================================
SELECT
    hri.instrument_id,
    hri.enqueued_at,
    hri.escalation_reason,
    hri.assigned_to_role,
    hri.review_completed_at,
    EXTRACT(EPOCH FROM (hri.review_completed_at - hri.enqueued_at)) / 60 AS review_minutes,
    hri.reviewer_decision,
    hri.reviewer_id_hash,                                   -- hashed, not raw user ID
    hri.overrode_agent_recommendation
FROM cts.human_review_items hri
WHERE hri.bank_id = :bank_id
  AND hri.enqueued_at BETWEEN :from_ts AND :to_ts
ORDER BY hri.enqueued_at DESC
LIMIT 500;

-- ============================================================
-- REPORT 4: NGCH Submission Integrity Report
-- RBI Control: CTS-03 — exactly-once NGCH filings
-- ============================================================
SELECT
    ns.submission_id,
    ns.instrument_id,
    ns.submitted_at,
    ns.ngch_ack_received_at,
    ns.submission_count,                                     -- must always be 1
    ns.decision_outcome,
    ns.ngch_response_code,
    ns.duplicate_detected
FROM cts.ngch_submissions ns
WHERE ns.bank_id = :bank_id
  AND ns.submitted_at BETWEEN :from_ts AND :to_ts
  AND (ns.submission_count > 1 OR ns.duplicate_detected = TRUE)
ORDER BY ns.submitted_at DESC;
-- NOTE: Zero rows is the expected result. Any row = exactly-once violation.

-- ============================================================
-- REPORT 5: Vault Miss Routing Audit
-- RBI Control: CTS-01, IS-02
-- Vault misses MUST route to human review — never auto-return
-- ============================================================
SELECT
    vm.instrument_id,
    vm.vault_type,                                           -- SIGNATURE or PPS
    vm.miss_at,
    vm.routed_to,                                            -- must always be HUMAN_REVIEW
    vm.auto_returned_incorrectly                             -- must always be FALSE
FROM cts.vault_miss_events vm
WHERE vm.bank_id = :bank_id
  AND vm.miss_at BETWEEN :from_ts AND :to_ts
ORDER BY vm.miss_at DESC;
-- NOTE: auto_returned_incorrectly = TRUE is a critical compliance violation.

-- ============================================================
-- REPORT 6: AI Decision Explainability Completeness
-- RBI Control: AI-01 — all decisions must have SHAP values
-- ============================================================
SELECT
    ad.instrument_id,
    ad.decided_at,
    ad.fraud_score,
    CASE WHEN ad.shap_values IS NOT NULL THEN 'PRESENT' ELSE 'MISSING' END AS shap_status,
    CASE WHEN ad.ocr_confidence IS NOT NULL THEN 'PRESENT' ELSE 'MISSING' END AS ocr_evidence,
    CASE WHEN ad.signature_score IS NOT NULL THEN 'PRESENT' ELSE 'MISSING' END AS sig_evidence
FROM cts.agent_decisions ad
JOIN cts.cheque_instruments ci ON ci.instrument_id = ad.instrument_id
WHERE ci.bank_id = :bank_id
  AND ad.decided_at BETWEEN :from_ts AND :to_ts
  AND (
      ad.shap_values IS NULL
      OR ad.ocr_confidence IS NULL
  )
ORDER BY ad.decided_at DESC
LIMIT 200;
-- NOTE: Any row = AI governance gap. Target: zero rows.

-- ============================================================
-- REPORT 7: Access Control Audit — Privileged Actions
-- RBI Control: IS-02, AUD-01
-- ============================================================
SELECT
    ae.event_id,
    ae.event_type,
    ae.occurred_at,
    ae.actor_role,
    ae.actor_id_hash,                                        -- HMAC-SHA256 of user ID, not raw
    ae.action,
    ae.resource_type,
    ae.outcome,
    ae.ip_class                                              -- INTERNAL / EXTERNAL — not raw IP
FROM audit.events ae
WHERE ae.bank_id = :bank_id
  AND ae.occurred_at BETWEEN :from_ts AND :to_ts
  AND ae.event_type IN (
      'CONFIG_CHANGE',
      'POLICY_CHANGE',
      'USER_ROLE_GRANT',
      'USER_ROLE_REVOKE',
      'VAULT_SECRET_ACCESS',
      'RBI_EXAMINER_ACCESS',
      'DIAGNOSTIC_ACCESS'
  )
ORDER BY ae.occurred_at DESC
LIMIT 1000;

-- ============================================================
-- REPORT 8: Configuration Change History (Maker-Checker)
-- RBI Control: ITG-03 — change management audit trail
-- ============================================================
SELECT
    cc.change_id,
    cc.changed_at,
    cc.config_key,
    cc.previous_value_masked,                               -- values masked per PII rules
    cc.new_value_masked,
    cc.maker_role,
    cc.maker_id_hash,
    cc.checker_role,
    cc.checker_id_hash,
    cc.approved,
    cc.rejection_reason
FROM audit.config_changes cc
WHERE cc.bank_id = :bank_id
  AND cc.changed_at BETWEEN :from_ts AND :to_ts
ORDER BY cc.changed_at DESC
LIMIT 500;

-- ============================================================
-- REPORT 9: EJ Dispute Resolution Summary
-- RBI Control: AUD-01 — EJ dispute audit trail
-- ============================================================
SELECT
    dc.dispute_id,
    dc.npci_claim_id,
    dc.atm_id,
    dc.created_at,
    dc.resolved_at,
    dc.resolution_outcome,                                   -- AUTO_RESOLVED, ESCALATED, FILED_TO_NPCI
    dc.ej_match_found,
    dc.cctv_evidence_available,
    EXTRACT(EPOCH FROM (dc.resolved_at - dc.created_at)) / 3600 AS resolution_hours,
    dc.auto_resolved_reason
FROM ej.dispute_cases dc
WHERE dc.bank_id = :bank_id
  AND dc.created_at BETWEEN :from_ts AND :to_ts
ORDER BY dc.created_at DESC
LIMIT 500;

-- ============================================================
-- REPORT 10: ATM Fleet Health Summary (EJ Observability)
-- RBI Control: AUD-01 — operational audit trail
-- ============================================================
SELECT
    ah.atm_id,
    ah.oem,
    ah.branch_id,
    ah.health_status,
    ah.last_ej_received_at,
    ah.pending_ej_count,
    ah.last_dispense_success_at,
    ah.consecutive_failure_count,
    EXTRACT(EPOCH FROM (NOW() - ah.last_ej_received_at)) / 3600 AS hours_since_last_ej
FROM ej.atm_health_snapshots ah
WHERE ah.bank_id = :bank_id
  AND ah.snapshot_at = (
      SELECT MAX(snapshot_at) FROM ej.atm_health_snapshots
      WHERE bank_id = :bank_id
  )
ORDER BY ah.health_status DESC, ah.consecutive_failure_count DESC;

-- ============================================================
-- REPORT 11: Audit Trail Integrity Verification
-- RBI Control: AUD-03 — non-repudiation, Merkle tree verification
-- ============================================================
-- This query surfaces events where the Immudb Merkle proof could not be verified.
-- Expected result: zero rows. Any row = audit trail integrity breach.
SELECT
    av.event_id,
    av.event_type,
    av.occurred_at,
    av.immudb_tx_id,
    av.merkle_verification_status,
    av.verification_attempted_at,
    av.verification_error
FROM audit.integrity_verification_log av
WHERE av.bank_id = :bank_id
  AND av.occurred_at BETWEEN :from_ts AND :to_ts
  AND av.merkle_verification_status != 'VERIFIED'
ORDER BY av.occurred_at DESC
LIMIT 100;

-- ============================================================
-- REPORT 12: RBI Examiner Session Access Log
-- RBI Control: AUD-02 — examiner access is time-scoped and audited
-- ============================================================
SELECT
    re.session_id,
    re.examiner_designation,
    re.access_granted_at,
    re.access_expires_at,
    re.reports_accessed,
    re.date_range_from,
    re.date_range_to,
    re.granted_by_role,
    re.revoked_early,
    re.revoked_at
FROM audit.rbi_examiner_sessions re
WHERE re.bank_id = :bank_id
ORDER BY re.access_granted_at DESC
LIMIT 100;

-- ============================================================
-- REPORT 13: Model Drift and Performance Metrics
-- RBI Control: AI-02 — model risk management
-- ============================================================
SELECT
    mm.model_name,
    mm.model_version,
    mm.metric_date,
    mm.ocr_accuracy,
    mm.sig_verification_precision,
    mm.fraud_f1_score,
    mm.fraud_false_positive_rate,
    mm.fraud_false_negative_rate,
    mm.ej_field_extraction_accuracy,
    mm.drift_alert_status,                                   -- SAFE, WARN, CRITICAL
    mm.auto_threshold_tightened,
    mm.pulled_from_production
FROM audit.model_metrics_daily mm
WHERE mm.bank_id = :bank_id
  AND mm.metric_date BETWEEN :from_date AND :to_date
ORDER BY mm.metric_date DESC, mm.model_name;

-- ============================================================
-- END OF STANDARD AUDIT REPORTS
-- For custom queries, contact ASTRA support with DiagnosticAccess session.
-- All queries are parameterised — never interpolate values directly.
-- ============================================================
