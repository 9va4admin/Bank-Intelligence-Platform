# CEREBRUM — Data Dictionary

> All entity schemas, field definitions, constraints, and relationships.
> These are the authoritative definitions. Pydantic models and YugabyteDB
> migrations MUST match these exactly.

---

## Entity Index

| # | Entity | Module | Storage | Description |
|---|---|---|---|---|
| 1 | [Bank](#1-bank) | Platform | YugabyteDB | Tenant — one row per bank |
| 2 | [ProcessingCenter](#2-processingcenter) | CTS | YugabyteDB | RPC per bank |
| 3 | [ChequeInstrument](#3-chequeinstrument) | CTS | YugabyteDB | Inward cheque lifecycle |
| 4 | [AgentDecision](#4-agentdecision) | CTS | YugabyteDB + Immudb | AI decision + rationale |
| 5 | [SignatureVaultEntry](#5-signaturevaultentry) | CTS | Redis | Per-account signature vector |
| 6 | [PPSVaultEntry](#6-ppsvaultentry) | CTS | Redis | Positive Pay record |
| 7 | [HumanReviewItem](#7-humanreviewitem) | CTS | YugabyteDB | Escalated cheque |
| 8 | [NGCHSubmission](#8-ngchsubmission) | CTS | YugabyteDB + Immudb | Filed to NGCH |
| 9 | [ATM](#9-atm) | EJ | YugabyteDB | ATM master record |
| 10 | [EJRawLog](#10-ejrawlog) | EJ | YugabyteDB + MinIO | Raw ingested log file |
| 11 | [EJCanonicalRecord](#11-ejcanonicalrecord) | EJ | YugabyteDB | Normalised per-transaction |
| 12 | [EJTransaction](#12-ejtransaction) | EJ | YugabyteDB | Individual ATM transaction |
| 13 | [DisputeCase](#13-disputecase) | EJ | YugabyteDB | NPCI claim + resolution |
| 14 | [CCTVEvidence](#14-cctvevidence) | EJ | YugabyteDB + MinIO | Video evidence clip |
| 15 | [AuditEvent](#15-auditevent) | Platform | Immudb | Immutable event (append-only) |
| 16 | [NotificationRecord](#16-notificationrecord) | Platform | YugabyteDB | Dispatched notification |
| 17 | [User](#17-user) | Platform | YugabyteDB | Bank staff member |
| 18 | [ModelVersion](#18-modelversion) | Platform | YugabyteDB | Deployed AI model |
| 19 | [ConfigHistory](#19-confighistory) | Platform | YugabyteDB + Immudb | Config change audit |

---

## 1. Bank

**Storage:** YugabyteDB — `platform.banks`
**Description:** One row per onboarded bank (tenant)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `bank_id` | UUID | PK, not null | Platform-internal bank identifier |
| `bank_code` | VARCHAR(10) | UNIQUE, not null | NPCI bank code |
| `bank_name` | VARCHAR(200) | not null | Official bank name |
| `bank_type` | ENUM | not null | `COMMERCIAL`, `COOPERATIVE`, `RRB`, `PSB`, `PRIVATE` |
| `ifsc_prefix` | VARCHAR(4) | not null | First 4 chars of IFSC (e.g., SBIN) |
| `cbs_type` | ENUM | not null | `FINACLE`, `BANCS`, `FLEXCUBE`, `TEMENOS`, `OTHER` |
| `clearing_zones` | VARCHAR[] | not null | Array of zone codes (e.g., ['NGCH_MUM', 'NGCH_DEL']) |
| `module_cts_enabled` | BOOLEAN | default false | CTS module active for this bank |
| `module_ej_enabled` | BOOLEAN | default false | EJ module active for this bank |
| `iet_minutes` | INTEGER | not null, default 180 | Item Expiry Time in minutes |
| `max_swarm_size` | INTEGER | not null, default 500 | Max concurrent agent pods |
| `fraud_threshold_review` | DECIMAL(4,3) | not null, default 0.650 | Fraud score → human review |
| `fraud_threshold_return` | DECIMAL(4,3) | not null, default 0.900 | Fraud score → auto return |
| `sig_confidence_min` | DECIMAL(4,3) | not null, default 0.750 | Min signature confidence for STP |
| `high_value_threshold` | BIGINT | not null, default 500000 | Amount in paise above which → review |
| `onboarded_at` | TIMESTAMPTZ | not null | Onboarding timestamp |
| `is_active` | BOOLEAN | not null, default true | Bank active on platform |
| `created_at` | TIMESTAMPTZ | not null, default now() | Record creation |
| `updated_at` | TIMESTAMPTZ | not null | Last update |

**Indexes:** `bank_code` (unique), `ifsc_prefix`

---

## 2. ProcessingCenter

**Storage:** YugabyteDB — `cts.processing_centers`
**Description:** Regional Processing Center (RPC) for a bank

| Field | Type | Constraints | Description |
|---|---|---|---|
| `center_id` | UUID | PK | RPC identifier |
| `bank_id` | UUID | FK → banks.bank_id | Parent bank |
| `center_code` | VARCHAR(20) | not null | Bank's internal RPC code |
| `center_name` | VARCHAR(100) | not null | e.g., "Delhi RPC" |
| `clearing_zone` | VARCHAR(20) | not null | e.g., "NGCH_DEL" |
| `ngch_member_code` | VARCHAR(20) | not null | NPCI-assigned member code |
| `ifsc_ranges` | VARCHAR[] | not null | IFSC prefixes handled by this RPC |
| `is_active` | BOOLEAN | default true | |
| `created_at` | TIMESTAMPTZ | not null | |

**Indexes:** `(bank_id, clearing_zone)`, `ngch_member_code`

---

## 3. ChequeInstrument

**Storage:** YugabyteDB — `cts.cheque_instruments`
**Description:** Every inward cheque received for processing

| Field | Type | Constraints | Description |
|---|---|---|---|
| `instrument_id` | UUID | PK | Platform UUID (UUIDv7 — time-sortable) |
| `bank_id` | UUID | FK → banks | Drawee bank |
| `center_id` | UUID | FK → processing_centers | Processing RPC |
| `ngch_instrument_ref` | VARCHAR(50) | UNIQUE, not null | NPCI/NGCH reference number |
| `presenting_bank_code` | VARCHAR(10) | not null | Presenting bank's NPCI code |
| `presenting_bank_ifsc` | VARCHAR(11) | not null | Presenting branch IFSC |
| `drawee_account_number` | VARCHAR(20) | ENCRYPTED, not null | Account to be debited (encrypted) |
| `drawee_ifsc` | VARCHAR(11) | not null | Drawee branch IFSC |
| `cheque_number` | VARCHAR(6) | not null | 6-digit cheque leaf number |
| `micr_code` | VARCHAR(9) | not null | MICR band code |
| `amount_figures` | BIGINT | not null | Amount in paise (OCR extracted) |
| `amount_words_text` | TEXT | | Amount in words (OCR extracted) |
| `amount_words_parsed` | BIGINT | | Parsed amount in paise from words |
| `amount_mismatch` | BOOLEAN | default false | Figures ≠ words |
| `cheque_date` | DATE | not null | Date on cheque |
| `payee_name` | VARCHAR(200) | ENCRYPTED | Payee name (OCR extracted) |
| `image_front_grey_path` | VARCHAR(500) | not null | MinIO path: front grayscale JPEG |
| `image_front_bw_path` | VARCHAR(500) | not null | MinIO path: front B&W TIFF |
| `image_reverse_bw_path` | VARCHAR(500) | not null | MinIO path: reverse B&W TIFF |
| `image_hash_front_grey` | VARCHAR(64) | not null | SHA-256 of front grey image |
| `image_hash_front_bw` | VARCHAR(64) | not null | SHA-256 of front B&W image |
| `image_hash_reverse_bw` | VARCHAR(64) | not null | SHA-256 of reverse image |
| `cts2010_compliant` | BOOLEAN | | CTS-2010 watermark check result |
| `alteration_detected` | BOOLEAN | | Pixel forensics result |
| `alteration_severity` | ENUM | | `NONE`, `LOW`, `MEDIUM`, `HIGH` |
| `pps_status` | ENUM | | `MATCHED`, `MISMATCHED`, `NOT_REGISTERED`, `NOT_CHECKED` |
| `pps_registered_amount` | BIGINT | | PPS vault registered amount in paise |
| `signature_confidence` | DECIMAL(5,4) | | 0.0000–1.0000 |
| `fraud_score` | DECIMAL(5,4) | | 0.0000–1.0000 |
| `workflow_id` | VARCHAR(100) | | Temporal workflow ID |
| `status` | ENUM | not null | `RECEIVED`, `PROCESSING`, `STP_CONFIRMED`, `STP_RETURNED`, `HUMAN_REVIEW`, `REVIEWER_CONFIRMED`, `REVIEWER_RETURNED`, `TIMEOUT_RETURNED`, `ERROR` |
| `iet_expires_at` | TIMESTAMPTZ | not null | Hard deadline |
| `received_at` | TIMESTAMPTZ | not null | Kafka event timestamp |
| `processing_started_at` | TIMESTAMPTZ | | Agent spawn time |
| `processing_completed_at` | TIMESTAMPTZ | | Decision filed time |
| `processing_duration_ms` | INTEGER | | Wall clock in ms |
| `created_at` | TIMESTAMPTZ | not null | |

**Indexes:** `ngch_instrument_ref` (unique), `(bank_id, status)`, `(bank_id, iet_expires_at)`, `drawee_account_number` (hashed), `received_at` (for time-range queries)

**Partitioning:** Range partition by `received_at` (monthly) — YugabyteDB range partitioning

---

## 4. AgentDecision

**Storage:** YugabyteDB — `cts.agent_decisions` + Immudb (append-only copy)
**Description:** Full AI decision record per cheque

| Field | Type | Constraints | Description |
|---|---|---|---|
| `decision_id` | UUID | PK (UUIDv7) | |
| `instrument_id` | UUID | FK → cheque_instruments | |
| `bank_id` | UUID | FK → banks | |
| `decision` | ENUM | not null | `STP_CONFIRM`, `STP_RETURN`, `HUMAN_REVIEW` |
| `return_reason_code` | VARCHAR(10) | | NPCI return reason code if returned |
| `return_reason_text` | TEXT | | Human-readable reason |
| `fraud_score` | DECIMAL(5,4) | not null | |
| `fraud_model_version` | VARCHAR(50) | not null | MLflow model version |
| `shap_values` | JSONB | not null | Feature impact scores |
| `rationale_text` | TEXT | not null | LLM-generated human-readable explanation |
| `ocr_confidence` | DECIMAL(5,4) | | |
| `alteration_confidence` | DECIMAL(5,4) | | |
| `signature_confidence` | DECIMAL(5,4) | | |
| `cbs_balance_checked` | BOOLEAN | not null | Was CBS available? |
| `cbs_balance_sufficient` | BOOLEAN | | null if not checked |
| `pps_checked` | BOOLEAN | not null | |
| `pps_matched` | BOOLEAN | | null if not registered |
| `iet_remaining_at_decision_ms` | INTEGER | not null | Safety margin |
| `decided_by` | ENUM | not null | `AI_AGENT`, `HUMAN_REVIEWER`, `IET_EMERGENCY` |
| `reviewer_user_id` | UUID | | FK → users, if human decided |
| `reviewer_comment` | TEXT | | Human reviewer's note |
| `llm_reasoning_trace` | JSONB | | Full LLM chain-of-thought |
| `temporal_workflow_id` | VARCHAR(100) | not null | |
| `temporal_run_id` | VARCHAR(100) | not null | |
| `immudb_tx_id` | BIGINT | | Immudb transaction ID for cross-ref |
| `decided_at` | TIMESTAMPTZ | not null | |

**Indexes:** `instrument_id` (unique — one decision per cheque), `(bank_id, decided_at)`, `fraud_score` (for analytics)

---

## 5. SignatureVaultEntry

**Storage:** Redis — `sig:{bank_id}:{account_number}` (keyspace per bank)
**Description:** Signature specimen vector per account (in-memory)

```
Redis Hash fields:
  account_number    : encrypted account number
  bank_id           : bank identifier
  sig_vector        : JSON array of float32 (512-dim embedding)
  sig_model_version : model version used for embedding
  enrolled_at       : ISO timestamp
  enrolled_by       : CBS event reference
  version           : integer (increments on re-enrolment)
  is_active         : "true"/"false"
  stop_payment      : "true"/"false"
  last_verified_at  : ISO timestamp (updated on each successful match)
  cbs_sync_ref      : CBS transaction reference for audit

TTL: 30 days (refreshed on every verification or CBS sync)
Key pattern: sig:{bank_id}:{sha256(account_number)}
             (account number hashed in key — never plaintext in Redis key)
```

---

## 6. PPSVaultEntry

**Storage:** Redis — `pps:{bank_id}:{account_number}:{cheque_series_start}`
**Description:** Positive Pay record per account+series

```
Redis Hash fields:
  account_number    : encrypted
  bank_id           : bank identifier
  cheque_series_start : starting cheque number
  cheque_series_end   : ending cheque number (or same as start for single)
  payee_name        : registered payee
  amount_paise      : registered amount in paise
  amount_tolerance_paise : allowed variance in paise (e.g., 0 for exact)
  valid_from        : ISO date
  valid_to          : ISO date (expiry)
  submitted_channel : MOBILE_BANKING, NET_BANKING, ATM, BRANCH
  submitted_at      : ISO timestamp
  submitted_by_ref  : customer session or teller reference

TTL: 90 days from valid_to
Key pattern: pps:{bank_id}:{sha256(account_number)}:{cheque_series_start}
```

---

## 7. HumanReviewItem

**Storage:** YugabyteDB — `cts.human_review_items`
**Description:** Cheque escalated for human decision

| Field | Type | Constraints | Description |
|---|---|---|---|
| `review_id` | UUID | PK | |
| `instrument_id` | UUID | FK → cheque_instruments | |
| `bank_id` | UUID | FK → banks | |
| `center_id` | UUID | FK → processing_centers | |
| `assigned_to_zone` | VARCHAR(20) | | Ops reviewer zone |
| `assigned_to_user_id` | UUID | | FK → users, if claimed |
| `escalation_reason` | TEXT | not null | Why AI escalated |
| `fraud_score` | DECIMAL(5,4) | not null | |
| `rationale_text` | TEXT | not null | AI's reasoning |
| `shap_summary` | JSONB | | Top 5 SHAP features |
| `iet_expires_at` | TIMESTAMPTZ | not null | Hard deadline |
| `auto_return_at` | TIMESTAMPTZ | not null | iet_expires_at - 5 minutes |
| `priority` | ENUM | not null | `CRITICAL`, `HIGH`, `NORMAL` |
| `status` | ENUM | not null | `PENDING`, `CLAIMED`, `DECIDED`, `TIMEOUT` |
| `decision` | ENUM | | `CONFIRMED`, `RETURNED` |
| `reviewer_comment` | TEXT | | |
| `decided_at` | TIMESTAMPTZ | | |
| `created_at` | TIMESTAMPTZ | not null | |

**Indexes:** `(bank_id, status, iet_expires_at)` — primary ops queue query

---

## 8. NGCHSubmission

**Storage:** YugabyteDB — `cts.ngch_submissions` + Immudb
**Description:** Every filing to NGCH (decision + NPCI acknowledgement)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `submission_id` | UUID | PK (UUIDv7) | |
| `instrument_id` | UUID | FK → cheque_instruments | |
| `bank_id` | UUID | FK → banks | |
| `submission_type` | ENUM | not null | `CONFIRM`, `RETURN` |
| `return_reason_code` | VARCHAR(10) | | If RETURN |
| `ngch_ack_ref` | VARCHAR(50) | UNIQUE | NPCI acknowledgement ref |
| `ngch_ack_timestamp` | TIMESTAMPTZ | | NPCI server timestamp |
| `payload_hash` | VARCHAR(64) | not null | SHA-256 of submitted payload |
| `hsm_signature` | TEXT | not null | PKI signature of payload |
| `submitted_at` | TIMESTAMPTZ | not null | |
| `iet_remaining_ms` | INTEGER | not null | Safety margin at submission |
| `submission_attempt` | INTEGER | not null, default 1 | Retry count |
| `status` | ENUM | not null | `PENDING`, `SUBMITTED`, `ACKNOWLEDGED`, `FAILED` |
| `immudb_tx_id` | BIGINT | | Cross-reference to immutable record |

**Constraint:** Only one ACKNOWLEDGED submission per instrument_id — enforced at DB level

---

## 9. ATM

**Storage:** YugabyteDB — `ej.atms`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `atm_id` | UUID | PK | |
| `bank_id` | UUID | FK → banks | |
| `atm_external_id` | VARCHAR(50) | UNIQUE per bank | Bank's ATM ID |
| `oem` | ENUM | not null | `DIEBOLD`, `NCR`, `WINCOR`, `HYOSUNG`, `GRG`, `OTHER` |
| `oem_model` | VARCHAR(100) | | Hardware model |
| `software_version` | VARCHAR(50) | | ATM software version (affects EJ format) |
| `location_type` | ENUM | not null | `ONSITE_BRANCH`, `OFFSITE`, `WHITE_LABEL` |
| `branch_id` | VARCHAR(20) | | Affiliated branch IFSC |
| `address` | TEXT | ENCRYPTED | Physical address |
| `city` | VARCHAR(100) | | |
| `state` | VARCHAR(50) | | |
| `ej_format_fingerprint` | VARCHAR(100) | | Detected OEM format version |
| `last_ej_received_at` | TIMESTAMPTZ | | Last successful log receipt |
| `connectivity_type` | ENUM | | `MPLS`, `BROADBAND`, `CELLULAR`, `TPSP` |
| `tpsp_name` | VARCHAR(100) | | If white-label |
| `is_active` | BOOLEAN | default true | |
| `onboarded_at` | TIMESTAMPTZ | not null | |

---

## 10. EJRawLog

**Storage:** YugabyteDB (metadata) — `ej.raw_logs` + MinIO (file)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `log_id` | UUID | PK (UUIDv7) | |
| `atm_id` | UUID | FK → atms | |
| `bank_id` | UUID | FK → banks | |
| `log_date` | DATE | not null | Date the EJ log covers |
| `minio_path` | VARCHAR(500) | not null | Object path in MinIO |
| `file_size_bytes` | BIGINT | not null | |
| `file_hash_sha256` | VARCHAR(64) | not null | Integrity check |
| `compressed_size_bytes` | BIGINT | | After gzip |
| `oem_fingerprint` | VARCHAR(100) | | Detected format |
| `received_at` | TIMESTAMPTZ | not null | When central received |
| `source` | ENUM | not null | `EDGE_MCP_PUSH`, `ATM_MGMT_SYSTEM_PULL`, `MANUAL_UPLOAD` |
| `edge_agent_version` | VARCHAR(20) | | Edge agent version |
| `normalisation_status` | ENUM | not null | `PENDING`, `PROCESSING`, `COMPLETE`, `FAILED` |
| `workflow_id` | VARCHAR(100) | | Temporal workflow ID |
| `transaction_count` | INTEGER | | After normalisation |
| `normalised_at` | TIMESTAMPTZ | | |

---

## 11. EJCanonicalRecord

**Storage:** YugabyteDB — `ej.canonical_records`
**Description:** Normalised, OEM-agnostic EJ record (one per ATM transaction)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `canonical_id` | UUID | PK (UUIDv7) | |
| `log_id` | UUID | FK → raw_logs | Source raw log |
| `atm_id` | UUID | FK → atms | |
| `bank_id` | UUID | FK → banks | |
| `transaction_ref` | VARCHAR(50) | | Bank's transaction reference |
| `stan` | VARCHAR(12) | | System Trace Audit Number |
| `rrn` | VARCHAR(12) | | Retrieval Reference Number |
| `transaction_datetime` | TIMESTAMPTZ | not null | ATM local time, normalised to UTC |
| `transaction_type` | ENUM | not null | `CASH_WITHDRAWAL`, `BALANCE_ENQUIRY`, `MINI_STATEMENT`, `PIN_CHANGE`, `FUND_TRANSFER`, `DEPOSIT`, `OTHER` |
| `card_number_masked` | VARCHAR(20) | | Last 4 digits only |
| `card_network` | ENUM | | `VISA`, `MASTERCARD`, `RUPAY`, `OTHER` |
| `requested_amount_paise` | BIGINT | | |
| `dispensed_amount_paise` | BIGINT | | Actual cash dispensed |
| `transaction_status` | ENUM | not null | `SUCCESS`, `FAILED`, `PARTIAL`, `TIMEOUT`, `REVERSED`, `CANCELLED` |
| `decline_code` | VARCHAR(10) | | If failed |
| `decline_reason` | TEXT | | Normalised decline reason |
| `cassette_states` | JSONB | | Cash cassette levels at time of txn |
| `card_retained` | BOOLEAN | default false | |
| `journal_text_raw` | TEXT | | Original journal entry (reference) |
| `llm_parse_confidence` | DECIMAL(5,4) | | LLM extraction confidence |
| `llm_model_version` | VARCHAR(50) | | |
| `created_at` | TIMESTAMPTZ | not null | |

**Partitioning:** Range by `transaction_datetime` (monthly)
**Indexes:** `(atm_id, transaction_datetime)`, `rrn`, `stan`, `(bank_id, transaction_datetime)`

---

## 12. DisputeCase

**Storage:** YugabyteDB — `ej.dispute_cases`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `dispute_id` | UUID | PK | |
| `bank_id` | UUID | FK → banks | |
| `npci_chargeback_ref` | VARCHAR(50) | UNIQUE | NPCI dispute reference |
| `atm_id` | UUID | FK → atms | |
| `customer_card_masked` | VARCHAR(20) | | |
| `disputed_amount_paise` | BIGINT | not null | |
| `dispute_date` | DATE | not null | Date of disputed transaction |
| `dispute_type` | ENUM | not null | `CASH_NOT_DISPENSED`, `PARTIAL_DISPENSE`, `CARD_CAPTURED`, `WRONG_AMOUNT`, `OTHER` |
| `canonical_record_id` | UUID | FK → canonical_records | Matched EJ record |
| `match_confidence` | DECIMAL(5,4) | | Embedding similarity score |
| `cctv_evidence_id` | UUID | FK → cctv_evidence | |
| `auto_resolved` | BOOLEAN | | |
| `resolution` | ENUM | | `BANK_CORRECT`, `CUSTOMER_CORRECT`, `PARTIAL`, `PENDING` |
| `resolution_basis` | TEXT | | Evidence summary |
| `filed_to_npci_at` | TIMESTAMPTZ | | If escalated |
| `resolved_at` | TIMESTAMPTZ | | |
| `status` | ENUM | not null | `OPEN`, `MATCHED`, `AUTO_RESOLVED`, `ESCALATED`, `CLOSED` |
| `created_at` | TIMESTAMPTZ | not null | |

---

## 13. CCTVEvidence

**Storage:** YugabyteDB (metadata) — `ej.cctv_evidence` + MinIO (clip)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `evidence_id` | UUID | PK | |
| `dispute_id` | UUID | FK → dispute_cases | |
| `atm_id` | UUID | FK → atms | |
| `bank_id` | UUID | FK → banks | |
| `clip_start_utc` | TIMESTAMPTZ | not null | |
| `clip_end_utc` | TIMESTAMPTZ | not null | |
| `clip_duration_sec` | INTEGER | | |
| `minio_path` | VARCHAR(500) | not null | |
| `file_hash_sha256` | VARCHAR(64) | not null | |
| `ai_analysis` | JSONB | | Person detected, cash count, timestamps |
| `cash_dispensed_detected` | BOOLEAN | | Vision model result |
| `dispense_amount_detected` | BIGINT | | Vision model estimated amount |
| `confidence` | DECIMAL(5,4) | | |
| `extracted_at` | TIMESTAMPTZ | not null | |
| `extracted_by_model` | VARCHAR(50) | | Model version |

---

## 14. AuditEvent

**Storage:** Immudb (primary, immutable) + MinIO WORM (backup)
**Description:** Every significant system event — tamper-proof

```
Schema (JSONB stored in Immudb):
{
  "event_id":        "UUIDv7 — time-sortable",
  "timestamp":       "RFC3339Nano",
  "event_type":      "CHEQUE_RECEIVED | AGENT_DECISION | HUMAN_REVIEW_ACTIONED
                       | NGCH_FILED | VAULT_ACCESSED | CONFIG_CHANGED
                       | USER_LOGIN | MODEL_DEPLOYED | EJ_NORMALISED
                       | DISPUTE_RESOLVED | ...",
  "bank_id":         "UUID",
  "actor": {
    "type":          "AI_AGENT | HUMAN_USER | SYSTEM_SERVICE",
    "id":            "workflow_id OR user_id OR service_name",
    "ip":            "internal IP (system actors only)"
  },
  "entity": {
    "type":          "CHEQUE | EJ_LOG | DISPUTE | CONFIG | USER | ...",
    "id":            "entity primary key"
  },
  "action": {
    "module":        "CTS | EJ | PLATFORM",
    "operation":     "verb describing what happened",
    "outcome":       "SUCCESS | FAILURE | PARTIAL"
  },
  "data": {
    "before_hash":   "SHA-256 of entity state before (if applicable)",
    "after_hash":    "SHA-256 of entity state after",
    "summary":       "human-readable one-line description"
  },
  "ai_context": {
    "model_id":      "if AI was involved",
    "model_version": "",
    "fraud_score":   null or float,
    "decision":      null or string
  },
  "temporal_ref": {
    "workflow_id":   "",
    "run_id":        "",
    "activity_id":   ""
  },
  "dc_id":           "DC1 | DC2",
  "hsm_signature":   "base64-encoded PKI signature of entire payload"
}

IMMUDB GUARANTEES:
  - Append-only: no update, no delete path exists
  - Merkle tree: every write updates the tree root
  - Tamper detection: any historical modification breaks the tree
  - Proof API: generate cryptographic proof for any record
  - SQL queryable: Immudb supports SQL on top of the ledger
```

---

## 15. NotificationRecord

**Storage:** YugabyteDB — `platform.notifications`

| Field | Type | Constraints | Description |
|---|---|---|---|
| `notification_id` | UUID | PK | |
| `bank_id` | UUID | FK → banks | |
| `trigger_event_id` | UUID | | Source audit event |
| `channel` | ENUM | not null | `EMAIL`, `WHATSAPP` |
| `recipient_role` | VARCHAR(50) | | Role that received |
| `recipient_address` | TEXT | ENCRYPTED | Email or phone |
| `template_id` | VARCHAR(50) | not null | WA template or email template ID |
| `subject` | VARCHAR(200) | | Email subject |
| `payload` | JSONB | | Template variables used |
| `priority` | ENUM | not null | `CRITICAL`, `HIGH`, `INFO` |
| `status` | ENUM | not null | `PENDING`, `SENT`, `DELIVERED`, `FAILED` |
| `sent_at` | TIMESTAMPTZ | | |
| `delivered_at` | TIMESTAMPTZ | | WA delivery receipt |
| `failure_reason` | TEXT | | |
| `retry_count` | INTEGER | default 0 | |
| `created_at` | TIMESTAMPTZ | not null | |

---

## 16. User

**Storage:** YugabyteDB — `platform.users`
**Note:** CEREBRUM never stores passwords. Identity via bank IdP (SAML 2.0).

| Field | Type | Constraints | Description |
|---|---|---|---|
| `user_id` | UUID | PK | |
| `bank_id` | UUID | FK → banks | |
| `saml_subject` | VARCHAR(200) | UNIQUE per bank | IdP-provided identifier |
| `employee_id` | VARCHAR(50) | | Bank HR system ID |
| `display_name` | VARCHAR(200) | ENCRYPTED | |
| `email` | VARCHAR(200) | ENCRYPTED | |
| `mobile` | VARCHAR(15) | ENCRYPTED | For WhatsApp notifications |
| `role` | ENUM | not null | See CLAUDE.md §6 for roles |
| `clearing_zone_scope` | VARCHAR[] | | Zones this user can access |
| `module_scope` | VARCHAR[] | | `['CTS']`, `['EJ']`, or `['CTS','EJ']` |
| `is_active` | BOOLEAN | default true | |
| `last_login_at` | TIMESTAMPTZ | | |
| `created_at` | TIMESTAMPTZ | not null | |
| `deprovisioned_at` | TIMESTAMPTZ | | When HR system removed user |

---

## 17. ModelVersion

**Storage:** YugabyteDB — `platform.model_versions` (mirror of MLflow)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `model_version_id` | UUID | PK | |
| `bank_id` | UUID | null = platform-wide model | |
| `model_name` | VARCHAR(100) | not null | e.g., `fraud_scorer`, `signature_verifier` |
| `version_tag` | VARCHAR(50) | not null | e.g., `v2.3.1` |
| `mlflow_run_id` | VARCHAR(100) | | MLflow reference |
| `base_model` | VARCHAR(100) | | Underlying LLM/model |
| `training_dataset_hash` | VARCHAR(64) | | SHA-256 of training data |
| `metrics` | JSONB | not null | All evaluation metrics |
| `threshold_config` | JSONB | | Thresholds used at deploy time |
| `status` | ENUM | not null | `SHADOW`, `ACTIVE`, `RETIRED` |
| `deployed_at` | TIMESTAMPTZ | | |
| `retired_at` | TIMESTAMPTZ | | |
| `deployed_by_user_id` | UUID | FK → users | |
| `approved_by_user_id` | UUID | FK → users | Two-person approval |
| `created_at` | TIMESTAMPTZ | not null | |

---

## 18. ConfigHistory

**Storage:** YugabyteDB — `platform.config_history` + Immudb
**Description:** Every configuration change (maker-checker audit)

| Field | Type | Constraints | Description |
|---|---|---|---|
| `config_change_id` | UUID | PK | |
| `bank_id` | UUID | FK → banks | |
| `config_level` | ENUM | not null | `BANK`, `MODULE`, `USER` |
| `config_key` | VARCHAR(200) | not null | e.g., `iet_minutes` |
| `old_value` | JSONB | | Previous value |
| `new_value` | JSONB | not null | New value |
| `change_reason` | TEXT | not null | Mandatory justification |
| `maker_user_id` | UUID | FK → users | Who proposed |
| `checker_user_id` | UUID | FK → users | Who approved |
| `maker_at` | TIMESTAMPTZ | not null | |
| `checker_at` | TIMESTAMPTZ | | |
| `effective_at` | TIMESTAMPTZ | | When applied |
| `status` | ENUM | not null | `PENDING_APPROVAL`, `APPROVED`, `REJECTED`, `APPLIED` |
| `immudb_tx_id` | BIGINT | | Immutable record cross-ref |

---

*Next: `/docs/microservices/` — detailed spec per service*
