# Message Taxonomy Rules (ASTRA Message Registry)

## The Single-Source Principle (Non-Negotiable)

All system messages — UI text, audit log entries, notifications — live in exactly one file:

```
shared/messages/locales/messages.yaml
```

No message string may exist anywhere else in the codebase.
`messages.yaml` is the single source of truth. The Redis cache, the browser JSON bundles,
and `docs/CTS_Msg_Taxonomy.html` are all derived outputs.

---

## Adding a New Message — Mandatory Steps

```
STEP 1 — Add the key to messages.yaml
  Location: shared/messages/locales/messages.yaml
  Format (required — all fields):

  MY_KEY_NAME:
    severity: INFO          # INFO | WARN | ERROR | CRITICAL
    surface: [UI, AUDIT]    # any combination of UI / AUDIT / NOTIFICATION
    variables: [var1, var2] # all {placeholders} that appear in the text
    en: "Message text with {var1} and {var2}."
    hi: ""                  # empty string = untranslated stub (required field)

  Key naming convention:
    {DOMAIN}_{SUBDOMAIN}_{DESCRIPTOR}
    e.g. CTS_WF_OCR_LOW_CONFIDENCE, VAULT_SIG_MISS, AUTH_ACCESS_DENIED, EJ_PARSE_FAILED

  Domain prefixes (required — pick the closest):
    CTS_WF    → CTS inward cheque processing workflow
    CTS_OUT   → CTS outward clearing (scanner, lot, endorsement, NGCH submission)
    CTS_COMP  → CTS-2010 compliance violations
    CTS_NGCH  → NGCH filing, IET, transport, settlement
    CTS_SMB   → Sub-member bank sponsor routing
    CBS       → Core Banking System connector events
    VAULT     → Signature vault and PPS vault events
    AUTH      → Authentication, session, RBAC, user management
    EJ        → ATM Electronic Journal processing and disputes
    PLATFORM  → Infrastructure: config, policy, audit, model, DC, Kafka

STEP 2 — Run the build
  python -m shared.messages.build

  This single command:
    → Validates the YAML (severity/surface/variable consistency)
    → Pushes all messages to Redis (if REDIS_MESSAGES_URL is set)
    → Writes browser JSON bundles to apps/web/src/shared/locales/
    → Regenerates docs/CTS_Msg_Taxonomy.html automatically

STEP 3 — Commit BOTH messages.yaml AND CTS_Msg_Taxonomy.html together
  git add shared/messages/locales/messages.yaml docs/CTS_Msg_Taxonomy.html
  git commit -m "feat(messages): add {KEY_NAME} — {short description}"

  Never commit messages.yaml without also committing the updated HTML doc.
  Pre-commit Check 11 enforces this pairing.
```

---

## Key Naming Convention

```
Format:  {DOMAIN}_{SUBDOMAIN?}_{DESCRIPTOR}
         All uppercase, underscores only, no spaces.

Good:    CTS_WF_VAULT_MISS         ✓
         VAULT_SIG_STALE           ✓
         AUTH_ACCOUNT_LOCKED       ✓
         EJ_ATM_HEALTH_CRITICAL    ✓

Bad:     chequeVaultMiss           ✗ (camelCase)
         cts-wf-miss               ✗ (hyphens)
         MSG_001                   ✗ (meaningless ID)
         CTS_SOMETHING             ✗ (too vague — descriptor required)
```

---

## Severity Rules

| Severity | When to use | Example |
|---|---|---|
| `INFO` | Normal lifecycle events, successful operations | STP confirm, login success, vault hit |
| `WARN` | Degraded path, threshold warnings, soft failures | Vault stale, OCR low confidence, CBS unreachable |
| `ERROR` | Hard failures requiring intervention | NGCH submit failed, signature mismatch, PPS amount mismatch |
| `CRITICAL` | Immediate action required, safety boundary breached | IET expired, vault stale halts processing, NGCH cert expired |

Rules:
- Vault miss → always WARN minimum (never INFO — it routes to human review)
- IET breach or risk → always CRITICAL
- Account frozen / closed / stop payment → always CRITICAL
- CBS unreachable (when cheques must still be processed) → always WARN with degraded-path note
- Audit integrity tamper → always CRITICAL

---

## Surface Rules

| Surface | Meaning | When to include |
|---|---|---|
| `UI` | Visible to bank operators in the workstation | Any event a human reviewer or ops_manager needs to see |
| `AUDIT` | Written to Immudb via AuditEvent | Any event that touches a financial instrument or access control |
| `NOTIFICATION` | Sent via email / WhatsApp | Events requiring proactive human attention (errors, escalations, time-sensitive) |

Rules:
- **AUDIT is mandatory** on any key that involves a cheque decision, vault operation, or auth event
- NOTIFICATION alone (without UI or AUDIT) is forbidden — if it's worth notifying, it's worth auditing
- CRITICAL messages must include NOTIFICATION
- INFO + NOTIFICATION is allowed (e.g. successful CBS vault sync notification to ops)

---

## Variable Rules

```yaml
# Every {placeholder} in en: text must be declared in variables:
# Every name in variables: must appear as {placeholder} in en: text
# Undeclared or unused variables fail validation (validate() returns errors)

GOOD:
  variables: [instrument_id, score]
  en: "Fraud score {score} for cheque {instrument_id} — STP eligible."

BAD (undeclared variable):
  variables: [instrument_id]
  en: "Fraud score {score} for cheque {instrument_id}."    # ← {score} undeclared → ERROR

BAD (unused declared variable):
  variables: [instrument_id, score, bank]
  en: "Fraud score {score} for cheque {instrument_id}."   # ← bank unused → ERROR
```

Variable naming:
- `account_display` — always masked account (****4521), never raw account number
- `amount_range` — always a range bucket (₹[1L-5L]), never exact amount
- `instrument_id` — the cheque/instrument reference number
- `bank_id` — the bank tenant identifier
- Use descriptive names: `return_reason` not `rr`, `confidence_pct` not `c`

---

## Using Messages in Code

```python
# WRONG — hardcoded string, untranslatable, unauditable
log.info(f"Vault miss for {account}: routing {instrument_id} to human review")

# CORRECT — registry fetch
from shared.messages import get_message
text = get_message(
    "VAULT_SIG_MISS",
    account_display=mask_account_number(account),
    instrument_id=instrument_id,
)
log.info("vault.sig_miss", message=text, bank_id=bank_id)

# For AuditEvent writes, use get_entry() to access severity + surface:
from shared.messages import get_entry
entry = get_entry("VAULT_SIG_MISS")
# entry.severity → "WARN"
# entry.surface  → ["UI", "AUDIT", "NOTIFICATION"]
```

---

## CTS_Msg_Taxonomy.html — Auto-Generated Doc

`docs/CTS_Msg_Taxonomy.html` is generated from `messages.yaml` on every build.
It is NOT maintained by hand — running the build keeps it in sync automatically.

```
Generated by: python -m shared.messages.build
              OR: python -m shared.messages.build_docs
Committed to: docs/CTS_Msg_Taxonomy.html (must be committed with messages.yaml)
Contains:
  - Summary table (counts by domain and severity)
  - Full searchable table with text, severity badges, surface chips, variables
  - Live search and severity filter (pure JS, no external dependencies)
  - Printable (filter UI hidden in print mode)
```

---

## What Is Forbidden

- Hardcoded message strings in any Python, Go, or React file — use the registry
- Adding a message key without adding the `hi:` stub field (even as empty string)
- Adding a new locale without adding the locale field for every existing key
- Editing `docs/CTS_Msg_Taxonomy.html` directly — it will be overwritten on next build
- Using `MSG_001` style numeric IDs — descriptive domain-prefixed names only
- Message keys in the `en/` or `hi/` subdirectories — those directories are deleted
- Any `print()` instead of `structlog` when emitting message content

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| All messages in messages.yaml only — no free-form strings in Python/React | Semgrep `astra-no-hardcoded-message-strings` (pattern: log.info with f-string message arg) | PR merge blocked |
| Key naming matches domain prefix convention | `validate()` on every build + CI `build --validate-only` stage | CI build blocked |
| All variables declared and used (none extra, none missing) | `registry.validate()` in CI `validate-only` run — non-empty errors list = exit 1 | CI build blocked |
| Severity must be one of INFO/WARN/ERROR/CRITICAL | `registry.validate()` — invalid severity = listed error | CI build blocked |
| Surface must be subset of UI/AUDIT/NOTIFICATION | `registry.validate()` — invalid surface value = listed error | CI build blocked |
| hi: stub field required on every key | `registry.validate()` — missing locale in cache = listed error | CI build blocked |
| CTS_Msg_Taxonomy.html committed alongside messages.yaml | pre-commit Check 11: if messages.yaml staged but CTS_Msg_Taxonomy.html not staged = blocked | Commit blocked |
| CTS_Msg_Taxonomy.html never edited directly | pre-commit Check 12: if CTS_Msg_Taxonomy.html staged but messages.yaml not staged = WARNING | Commit warned |
| build_docs auto-runs on every build | Wired into `shared/messages/build.py` main() — not a separate step | Runtime (build script) |
| No message keys in deleted en/ or hi/ subdirectories | Glob check: `shared/messages/locales/en/` and `hi/` must not exist | CI lint check |
