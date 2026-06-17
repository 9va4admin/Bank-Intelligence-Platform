# PII Data Protection Rules (Encryption · Hashing · Masking)

## Three Different Controls — Know Which to Apply

| Situation | Control | Why |
|---|---|---|
| Storing account number in DB | Hash (SHA-256 + salt) | Never need to reverse it — only use for lookup |
| Storing cheque image | Encrypt at rest (AES-256, MinIO SSE) | Need to retrieve original for display |
| Storing customer name in DB | Encrypt at column level (pgcrypto) | Need to display in UI, but not searchable |
| Logging any PII field | Mask (show only safe fragment) | Logs are never encrypted — masking is the only option |
| Sending PII in API response | Mask fields per role (RBAC) | fraud_analyst must not see account numbers |

---

## Rule 1 — Hashing (One-Way, for Lookup Keys)

Use when: the value is used as a lookup key and never needs to be reversed.
```python
# CORRECT — account number as vault key (never stored raw)
import hashlib, hmac
from shared.config.config_service import config_service

def hash_account_number(account_number: str, bank_id: str) -> str:
    # HMAC-SHA256 with bank-specific pepper from Vault — not plain SHA256
    pepper = config_service.get(f"banks.{bank_id}.pii_hash_pepper")  # from Vault
    return hmac.new(
        pepper.encode(),
        f"{bank_id}:{account_number}".encode(),
        hashlib.sha256
    ).hexdigest()

# Redis vault key — hashed, never raw
vault_key = f"sig:{bank_id}:{hash_account_number(account_number, bank_id)}"

# YugabyteDB lookup — hashed, never raw
WHERE account_hash = $1  -- parameterised, hashed value only

# FORBIDDEN
vault_key = f"sig:{bank_id}:{account_number}"   # raw account number as key
WHERE account_number = $1                        # raw PII in query
```

---

## Rule 2 — Encryption at Rest (Reversible, for Storage)

**Object Store (MinIO — cheque images, EJ files, CCTV clips):**
```yaml
# All MinIO buckets must have SSE-KMS enabled
# Keys managed by bank's KMS (HashiCorp Vault transit engine)
# Set in Helm values — non-overridable default:
minio:
  sse:
    enabled: true
    type: SSE-KMS
    kms_key_id: "vault-transit://astra/{bank_id}/minio-key"
```

**Database column-level encryption (YugabyteDB — PII fields only):**
```sql
-- PII columns use pgcrypto symmetric encryption
-- Key fetched from Vault at application startup — never hardcoded

-- Schema definition
CREATE TABLE cts.cheque_instruments (
    instrument_id   UUID PRIMARY KEY,
    bank_id         TEXT NOT NULL,
    -- PII columns encrypted with pgcrypto:
    payee_name_enc  BYTEA,    -- pgp_sym_encrypt(payee_name, $key)
    drawer_enc      BYTEA,    -- pgp_sym_encrypt(drawer_name, $key)
    -- Non-PII stored plainly:
    amount_range    TEXT,     -- "HIGH_VALUE" | "STANDARD" — never exact amount
    received_at     TIMESTAMPTZ NOT NULL,
    status          TEXT NOT NULL
);
```

```python
# Application code — encrypt before write, decrypt after read
from shared.crypto.pii_cipher import PiiCipher

cipher = PiiCipher(bank_id=bank_id)  # fetches key from Vault internally

# Write
encrypted_payee = cipher.encrypt(payee_name)
await db.execute(
    "INSERT INTO cts.cheque_instruments (payee_name_enc, ...) VALUES ($1, ...)",
    encrypted_payee, ...
)

# Read — decrypt only when role permits
if rbac.can_view_pii(current_user):
    payee_name = cipher.decrypt(row["payee_name_enc"])
else:
    payee_name = "***REDACTED***"
```

**Never store:**
- Exact cheque amounts — store range bucket: `"STANDARD"` / `"HIGH_VALUE"` / `"VERY_HIGH_VALUE"`
- Full account numbers — store only account hash + last 4 digits for display
- Full customer names in plaintext — always encrypted column or masked display

---

## Rule 3 — Masking (for Logs, API Responses, UI Display)

```python
# shared/utils/masking.py — import this, never write masking logic ad hoc

def mask_account_number(account_number: str) -> str:
    """****4521 — last 4 digits only"""
    return f"****{account_number[-4:]}"

def mask_customer_name(name: str) -> str:
    """N*** — first initial only"""
    return f"{name[0]}***" if name else "***"

def mask_amount(amount: float) -> str:
    """₹[1L-5L] — range bucket, never exact"""
    if amount < 100_000:       return "₹[<1L]"
    elif amount < 500_000:     return "₹[1L-5L]"
    elif amount < 1_000_000:   return "₹[5L-10L]"
    elif amount < 10_000_000:  return "₹[10L-1Cr]"
    else:                      return "₹[>1Cr]"

def mask_phone(phone: str) -> str:
    """******7890 — last 4 digits only"""
    return f"******{phone[-4:]}"

# Usage in structured logging:
log.info("cheque.processed",
         account=mask_account_number(account_number),   # ****4521
         amount=mask_amount(amount),                     # ₹[1L-5L]
         payee=mask_customer_name(payee_name))           # N***

# Usage in API responses (role-based):
class ChequeDetailResponse(BaseModel):
    instrument_id: str
    account_display: str   # always masked: ****4521
    payee_display: str     # always masked: N***
    amount_range: str      # always bucketed: ₹[1L-5L]
    # Full values NEVER returned in API response — even to ops_manager
```

---

## Rule 4 — Data Retention and Deletion

```python
# PII fields follow MinIO ILM lifecycle — see storage tiers in CLAUDE.md
# Application code must NOT implement its own deletion logic
# Deletion is handled by:
#   - MinIO Object Lock expiry (Tier 3 WORM — cannot be deleted early)
#   - YugabyteDB partition drop (monthly partitions, drop after 10 years)
#   - Redis TTL (set at write time — never extend TTL in application code)
```

---

## Compliance Checklist (Run Before Any PR Touching PII Tables)
```
[ ] Account numbers stored as HMAC-SHA256 hash + last 4 only
[ ] Cheque images in MinIO with SSE-KMS enabled
[ ] PII columns in YugabyteDB use encrypted BYTEA (pgcrypto)
[ ] Logs use masking functions from shared/utils/masking.py
[ ] API responses return masked/bucketed values — never raw PII
[ ] No exact amounts stored — range buckets only
[ ] Column-level decryption gated by RBAC can_view_pii() check
```

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| Account numbers stored as HMAC hash only | Semgrep `astra-no-select-star-pii` + `security-auditor` agent PII checklist | PR merge blocked (CRITICAL) |
| MinIO buckets have SSE-KMS | checkov `CKV_*` on Helm MinIO config | PR merge blocked |
| PII columns use pgcrypto BYTEA | `security-auditor` agent: plaintext PII column = CRITICAL finding | PR merge blocked |
| Logs use masking functions from shared/utils/masking.py | Semgrep pattern: direct log of account_number/amount/payee without masking | PR merge blocked |
| API responses return masked values only | `security-auditor` agent: raw PII in response model = CRITICAL | PR merge blocked |
| No exact amounts stored — range buckets only | Semgrep custom rule: amount/cheque_amount as NUMERIC column | PR merge blocked |
| can_view_pii() gating decryption | `security-auditor` agent: decrypt call without RBAC check = CRITICAL | PR merge blocked |
