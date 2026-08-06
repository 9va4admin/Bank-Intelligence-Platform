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

# FORBIDDEN
vault_key = f"sig:{bank_id}:{account_number}"   # raw account number as key
```

---

## Rule 2 — Encryption at Rest (Reversible, for Storage)

**Object Store (MinIO):** All buckets must have SSE-KMS enabled, keys managed by Vault transit engine.

**Database (YugabyteDB):** PII columns use pgcrypto BYTEA — `pgp_sym_encrypt(payee_name, $key)`. Key fetched from Vault at startup. Decrypt only when `rbac.can_view_pii(current_user)` is true.

**Never store:**
- Exact cheque amounts — store range bucket: `"STANDARD"` / `"HIGH_VALUE"` / `"VERY_HIGH_VALUE"`
- Full account numbers — store only account hash + last 4 digits for display
- Full customer names in plaintext — always encrypted column or masked display

---

## Rule 3 — Masking (for Logs, API Responses, UI Display)

```python
# shared/utils/masking.py — import this, never write masking logic ad hoc

def mask_account_number(account_number: str) -> str:
    return f"****{account_number[-4:]}"

def mask_customer_name(name: str) -> str:
    return f"{name[0]}***" if name else "***"

def mask_amount(amount: float) -> str:
    if amount < 100_000:       return "₹[<1L]"
    elif amount < 500_000:     return "₹[1L-5L]"
    elif amount < 1_000_000:   return "₹[5L-10L]"
    elif amount < 10_000_000:  return "₹[10L-1Cr]"
    else:                      return "₹[>1Cr]"
```

API responses always return masked/bucketed values — never raw PII even for ops_manager.

---

## Rule 4 — Data Retention

Application code must NOT implement its own deletion logic. Deletion is handled by MinIO Object Lock expiry, YugabyteDB partition drops (monthly, after 10 years), and Redis TTL set at write time.

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
