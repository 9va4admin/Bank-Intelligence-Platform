# ASTRA Bank Onboarding Runbook

> **Audience:** ASTRA implementation team + bank IT admin  
> **Classification:** Confidential — per-bank copy, do not share across banks  
> **Last updated:** June 2026

---

## 1. Prerequisites Checklist

Before onboarding begins, confirm all of the following with the bank:

```
[ ] Bank ID agreed and confirmed (e.g. saraswat-coop) — must be DNS-safe, lowercase, hyphenated
[ ] Modules purchased: CTS / EJ / both
[ ] CBS type confirmed: finacle | bancs | flexcube
[ ] Clearing zones confirmed: MUMBAI | DELHI | CHENNAI | KOLKATA
[ ] Data center count for pilot: 1 (single DC) or 2 (active-active)
[ ] GPU hardware provisioned per profile:
      Pilot:      4× RTX 4090 (minimum)
      Production: 4× A100 80GB (recommended)
[ ] Bank IdP metadata URL available (SAML 2.0)
[ ] Role mapping agreed (bank IdP groups → ASTRA roles — see §3)
[ ] NGCH SFTP credentials provisioned by NPCI for this bank
[ ] CBS API credentials available (REST or SOAP depending on CBS type)
[ ] Network: ASTRA cluster can reach CBS, bank IdP, NPCI SFTP
[ ] HSM provisioned and FIPS 140-2 Level 3 certified
[ ] Bank change management approval obtained for initial deployment
```

---

## 2. Helm Values Setup

Create the bank's values files in the ASTRA repo:

```
infra/helm/values/banks/{bank_id}/
  platform.yaml   ← always required
  cts.yaml        ← if CTS purchased
  ej.yaml         ← if EJ purchased
```

Use `infra/helm/values/banks/saraswat-coop/` as the reference.  
Layer 2 values only — thresholds (Layer 3) are set post-onboarding via Admin UI.

Submit as a PR to the ASTRA repo. Requires `bank_it_admin` approval before ArgoCD sync.

---

## 3. Identity Provider (IdP) Configuration

ASTRA integrates with the bank's existing IdP via SAML 2.0. ASTRA never stores passwords.

### Role Mapping (bank IdP group → ASTRA role)

| ASTRA Role | Capabilities | Typical bank group |
|---|---|---|
| `ops_reviewer` | Human review queue (own clearing zone only) | CTS ops staff |
| `ops_manager` | Full CTS + EJ ops, Layer 3 config (maker) | Ops manager / team lead |
| `fraud_analyst` | Fraud scores + AI explainability, no PII | Risk / fraud team |
| `bank_it_admin` | Admin console, Layer 2+3 config (checker), Temporal UI access | IT admin / infrastructure team |
| `compliance_officer` | Audit trail, reports, OPA policy authoring | Compliance / internal audit |
| `rbi_examiner` | Read-only audit, time-scoped per engagement | RBI examiner (provisioned per audit) |
| `ml_engineer` | AI server, model metrics, no customer data | Data science / ML team |

Configure the mapping in `platform.yaml` under the `idp.role_mapping` block.  
Confirm with the bank which AD/LDAP groups map to each role before go-live.

---

## 4. Secrets Provisioning (Vault)

All secrets are stored in HashiCorp Vault under `secret/astra/{bank_id}/`.  
The ASTRA implementation engineer provisions these at onboarding — they are never in Git.

### Secrets to provision before first deployment

```
secret/astra/{bank_id}/db/cts/password
secret/astra/{bank_id}/db/ej/password           (if EJ purchased)
secret/astra/{bank_id}/redis/cts/auth_token
secret/astra/{bank_id}/redis/ej/auth_token      (if EJ purchased)
secret/astra/{bank_id}/ngch/sftp_private_key
secret/astra/{bank_id}/cbs/{cbs_type}/password
secret/astra/{bank_id}/whatsapp/business_api_key
secret/astra/{bank_id}/hsm/operator_pin
secret/astra/{bank_id}/pii_hash_pepper
secret/astra/{bank_id}/minio/access_key
secret/astra/{bank_id}/minio/secret_key
secret/astra/{bank_id}/immudb/admin_password
secret/astra/{bank_id}/temporal/tls/client_cert
secret/astra/{bank_id}/temporal/tls/client_key
```

All secrets rotate automatically every 24 hours after provisioning.  
Application picks up fresh values within 30 seconds (Vault agent sidecar + config_service cache TTL).

---

## 5. First Deployment

ArgoCD handles the actual deployment. The bank's IT admin controls ArgoCD — ASTRA team has no kubectl/shell access to the bank's production cluster.

```
Step 1 — ASTRA team publishes chart to OCI registry
  astra-platform:{version}, astra-cts:{version}, astra-ej:{version}

Step 2 — bank_it_admin raises change request in bank's ITSM
  Attach: ASTRA release notes, chart version, values diff

Step 3 — Bank CAB approves change request

Step 4 — bank_it_admin sets targetRevision in ArgoCD to the new chart version
  ArgoCD syncs → Helm pre-upgrade hook runs Alembic migrations first
  Rolling update follows — zero downtime for stateless services

Step 5 — Post-upgrade smoke test runs automatically (Helm post-upgrade hook)
  Assertions: Vault reachable · mTLS between pods · Immudb write verified
  If any assertion fails → Helm rolls back automatically

Step 6 — bank_it_admin confirms deployment in ITSM ticket
```

---

## 6. Post-Deployment Configuration (Layer 3 — Admin UI)

These are set via the Admin UI maker-checker flow after the first deployment.  
`ops_manager` submits → `bank_it_admin` approves → takes effect within 30 seconds, no restart.

### Minimum required before go-live

| Parameter | Description | Typical default |
|---|---|---|
| `iet_minutes` | IET window the bank operates under | 180 |
| `stp_auto_confirm_threshold` | AI confidence above which cheque auto-confirms | 0.92 |
| `human_review_fraud_threshold` | Fraud score above which human review is triggered | 0.72 |
| `high_value_amount_threshold` | Amount above which OPA high-value rules apply | 500000 |
| `ocr_min_confidence` | OCR confidence below which cheque goes to human review | 0.90 |
| `signature_min_match_score` | Signature match below which cheque goes to human review | 0.85 |

### WhatsApp alert recipients

Phone numbers for senior ops staff who receive WhatsApp alerts are seeded via Vault at onboarding, not via Admin UI. Confirm the list with the bank's ops manager before go-live.

---

## 7. Vault Sync (Signature + PPS)

The first vault sync pulls signature specimens and Positive Pay records from CBS into the in-memory vault.

**Schedule:** Daily at 6AM (before SESSION_1 opens). First sync runs on deployment day.

**To trigger manually** (e.g. after a CBS data load):
```
# bank_it_admin only — via Admin UI → Operations → Vault → Trigger Sync
# Or via kubectl (bank's own cluster access):
kubectl create job --from=cronjob/vault-sync-cronjob manual-vault-sync-$(date +%s) \
  -n astra-cts-{bank_id}
```

**Verify sync completed:**
- Admin UI → Operations → Vault → Last Sync Status should show `SYNC_COMPLETE`
- Check signature count matches CBS export count

---

## 8. Temporal Workflow UI — Access Guide

Temporal's built-in web UI is the authoritative tool for inspecting running and historical workflows — activity-by-activity execution state, retry counts, failure reasons, signal history, and child workflow links (e.g. IET watchdog linked to its parent cheque workflow).

### Who should access it

| Role | Access | How |
|---|---|---|
| `bank_it_admin` | **Authorised** — for debugging and incident investigation | See §8.1 below |
| `ops_manager` | Not required — use ASTRA ops workstation for operational view | ASTRA UI |
| `ops_reviewer` | Not required — human review queue is in ASTRA ops workstation | ASTRA UI |
| ASTRA support engineer | Via Diagnostic MCP session (bank-consented, time-limited) | See §8.2 below |

**Do not expose Temporal UI to `ops_reviewer` or `fraud_analyst` roles.** Workflow payloads may contain partial cheque fields before PII masking is applied at the ASTRA API layer.

### 8.1 bank_it_admin Access (kubectl port-forward)

Temporal UI is not exposed via external ingress by default. Access it via port-forward from the bank's internal network:

```bash
# Run from a machine with kubectl access to the bank's cluster
kubectl port-forward svc/temporal-ui 8080:8080 -n astra-cts-{bank_id}

# Then open in browser (internal network only):
http://localhost:8080
```

**Namespace to select in the UI:** `cts` (CTS workflows) or `ej` (EJ workflows)

**Useful searches:**

```
# Find a specific cheque by instrument ID:
Workflow ID = cts-{bank_id}-{instrument_id}

# Find the IET watchdog for that cheque:
Workflow ID = cts-iet-{bank_id}-{instrument_id}

# Find all workflows currently in human review:
Status = Running  AND  WorkflowType = HumanReviewWorkflow

# Find all failed workflows in last 1 hour:
Status = Failed  AND  StartTime > now()-1h

# Find workflows that hit the IET emergency filer:
WorkflowType = IETWatchdogWorkflow  AND  Status = Completed
```

**What each status means:**

| Temporal Status | ASTRA meaning |
|---|---|
| Running | Cheque is actively being processed or awaiting human review |
| Completed | Decision filed to NGCH — check workflow result for STP_CONFIRM / STP_RETURN |
| Failed | Activity exhausted retries — requires investigation; IET watchdog will have filed if IET was at risk |
| Terminated | Manually cancelled (rare — only by `bank_it_admin` in exceptional cases) |
| TimedOut | HumanReviewWorkflow 55-min timeout expired — auto-returned to presenting bank |

**Viewing activity details:**

Click any workflow → History tab → expand any activity event to see:
- Input payload (cheque metadata — no full account numbers, PII is masked at activity level)
- Output payload (AI scores, decision rationale)
- Retry attempts and failure messages
- Duration per activity

**Child workflow link:**

Every `ChequeProcessingWorkflow` has a linked `IETWatchdogWorkflow` child. Click the child workflow ID in the parent's history to open it. If the watchdog fired the emergency filer (T-30s path), it will show as a completed `file_to_ngch` activity in the watchdog — not in the parent.

### 8.2 ASTRA Support Engineer Access

ASTRA support engineers do **not** get direct Temporal UI access. Instead:

1. Support raises a request with the bank specifying: scope (which services), duration (max 4 hours), ticket ID
2. `bank_it_admin` approves in Admin UI → issues a time-limited diagnostic session token
3. Bank opens a temporary mTLS tunnel for the session
4. Support connects via the Diagnostic MCP server (`astra-diagnostic-mcp`) — exposes aggregated signals only, no raw workflow payloads
5. Every tool call is logged to the immutable audit trail — bank IT admin can see the full access log in real time

For workflow-level failures, the Diagnostic MCP `get_workflow_failures` tool returns failure counts and reason codes (e.g. `ACTIVITY_TIMEOUT:ocr_extract: 2`) without exposing workflow IDs or instrument IDs.

---

## 9. Sub-Member Bank (SMB) Setup

Applies only if the bank is acting as a Sponsor Bank for smaller UCBs routing CTS through them.

Enable in `cts.yaml`:
```yaml
smb:
  enabled: true
  smb_forwarding_worker:
    min_replicas: 1
    max_replicas: 10
```

Each sub-member bank is then configured via Admin UI (not Helm):
- SMB name, MICR prefix range, IFSC prefix
- Per-SMB vault namespace (signature specimens kept isolated per SMB)
- Forwarding rules (which instruments route to which SMB)

Limit on sub-members is set in `platform.yaml` (`smb_sponsor_max_sub_members`).

---

## 10. Go-Live Readiness Checklist

```
[ ] All Vault secrets provisioned and verified
[ ] IdP SAML metadata URL reachable from ASTRA cluster
[ ] Role mapping tested — each role can log in and sees correct screens
[ ] Vault sync completed — signature + PPS counts match CBS
[ ] Layer 3 thresholds set via Admin UI (§6 minimum set)
[ ] NGCH SFTP connectivity verified (test submission to NPCI staging)
[ ] CBS connectivity verified (test balance query)
[ ] WhatsApp alert test message sent and received
[ ] Temporal UI port-forward verified for bank_it_admin (§8.1)
[ ] Chaos drill: DC1 network partition — DC2 takes over in < 30s
[ ] Performance: 100-cheque batch processed in < 600ms wall clock
[ ] bank_it_admin walkthrough of Admin UI maker-checker flow complete
[ ] ops_reviewer walkthrough of human review queue complete
[ ] compliance_officer walkthrough of audit trail export complete
[ ] First clearing session (live, low volume) — monitored by ASTRA team
[ ] Hypercare period: ASTRA team on standby for 5 business days post go-live
```

---

## 11. Rollback Procedure

If any issue is found after go-live:

```
Step 1 — bank_it_admin reverts targetRevision in ArgoCD to previous chart version
Step 2 — ArgoCD syncs → Alembic downgrade runs automatically (Helm pre-upgrade hook)
Step 3 — Pods restart on previous image version
Step 4 — Verify: smoke test suite passes on previous version
Step 5 — bank_it_admin logs rollback in ITSM ticket with reason

SLA: rollback complete in < 10 minutes.
```

Schema migrations are always backwards-compatible for one version (additive only),  
so rollback never requires manual data migration.

---

## 12. Support Contacts

| What | Who | How |
|---|---|---|
| ASTRA platform issues | ASTRA support | Raise ticket → Diagnostic MCP session (§8.2) |
| CBS connectivity | Bank IT + CBS vendor | Bank's existing CBS support channel |
| NGCH / NPCI | NPCI helpdesk | Bank's designated NPCI contact |
| HSM issues | HSM vendor | Bank's hardware support contract |
| Clearing disputes | Bank ops manager | ASTRA dispute console or direct to NPCI |
