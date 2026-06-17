---
name: onboard-bank
description: End-to-end skill for onboarding a new bank onto ASTRA. Covers Helm values generation, ArgoCD wiring, initial vault seeding checklist, and smoke test verification.
---

# Skill: Onboard a New Bank

## When to Use
User says: "onboard [bank name]", "add new bank", "set up [bank] on ASTRA", or uses `/new-bank` command.

## Step-by-Step Procedure

### Step 1 — Gather Required Information
Ask (or read from user input):
- `bank_id`: lowercase hyphenated (e.g. `kotak-mah`)
- `bank_name`: full legal name
- `ifsc_prefix`: 4-char (e.g. `KKBK`)
- `cbs_connector_type`: finacle | bancs | flexcube
- `modules`: which of cts, ej to enable
- `ngch_zone`: required if CTS enabled (MUMBAI | DELHI | CHENNAI | KOLKATA | HYDERABAD | BENGALURU)
- `sizing.profile`: pilot | standard | large
- `dc_count`: 2 (minimum) or 3

### Step 2 — Generate Bank Values File
Create `infra/helm/values/banks/{bank_id}.yaml` by copying `bank-template.yaml` and filling all REQUIRED fields.
Do NOT set any Layer 3 thresholds here — those go via Admin UI after deployment.

### Step 3 — Add ArgoCD Application
The `app-of-apps.yaml` uses ApplicationSet with git file generator — it auto-discovers the new bank yaml.
Verify: the new file will be picked up on next ArgoCD refresh (no manual edit needed).

### Step 4 — Generate Namespace Checklist
Print this checklist for the bank's IT team:

```
PRE-DEPLOYMENT CHECKLIST — {bank_name}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Infrastructure
[ ] Kubernetes cluster ready (min version 1.28)
[ ] Istio installed and STRICT mode enabled
[ ] ArgoCD installed, connected to ASTRA OCI registry
[ ] 2 DCs confirmed (DC1 active, DC2 active, DC3 backup)
[ ] GPU nodes provisioned per sizing.profile

Vault & Security
[ ] HashiCorp Vault initialized and unsealed
[ ] Vault path seeded: secret/astra/{bank_id}/cbs (CBS credentials)
[ ] Vault path seeded: secret/astra/{bank_id}/ngch (NGCH credentials)
[ ] Vault path seeded: secret/astra/{bank_id}/whatsapp (if enabled)
[ ] HSM initialized, FIPS 140-2 Level 3 confirmed
[ ] Internal CA cert issued, cert-manager configured

Identity
[ ] Bank IdP SAML metadata URL confirmed and accessible
[ ] Role mappings configured in bank IdP:
    ops_reviewer, fraud_analyst, ops_manager, bank_it_admin,
    compliance_officer, rbi_examiner, ml_engineer

CBS Connector
[ ] CBS host reachable from ASTRA namespace
[ ] CBS read-only service account created
[ ] Connector type confirmed: {cbs_connector_type}
[ ] Test query: get_account_status on a known test account

NGCH / NPCI (if CTS enabled)
[ ] NGCH SFTP credentials received and stored in Vault
[ ] NGCH zone confirmed: {ngch_zone}
[ ] SFTP connectivity test passed
[ ] PKI certificate for NGCH signing obtained from NPCI

Post-Deploy
[ ] VaultSyncWorkflow triggered manually → signature vault warm
[ ] Smoke test suite run: all green
[ ] First test cheque processed end-to-end in staging
[ ] Bank IT Admin logs in via SAML, all roles verified
```

### Step 5 — Commit and Notify
- Commit the new bank values file with message: `feat: onboard {bank_id} ({bank_name})`
- Push to `claude/` branch → raise PR for review
- Tag the bank_it_admin contact in PR description

### Important Rules
- Never put CBS/NGCH/WhatsApp credentials in the values file — always Vault
- Never enable both modules on pilot sizing — pilot GPU is insufficient for concurrent CTS + EJ
- Always set `astra.chart_version` to the current stable release
