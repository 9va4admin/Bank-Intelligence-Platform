# SB vs SMB Context Rule (UI · Data · Downloads · Config)

## The Fundamental Principle

**Everything a user can see or do is determined by their bank type at login.**

There are two bank types in ASTRA CTS:

| Type | Full Name | Example |
|---|---|---|
| SB | Sponsor Bank | Saraswat Co-operative Bank |
| SMB | Sub-Member Bank | A smaller UCB routed through Saraswat |

The authenticated user's bank type is resolved once at login (from the JWT / SAML claim).
From that point, every page, every data row, every filter, every download, every config screen
is automatically scoped. There is no manual toggle in production — the type is what it is.

> **Demo / development exception:** a toggle (SB ↔ SMB) may be shown in the UI for
> demonstration purposes only. It must be clearly labelled "Demo Mode" and must not
> exist in production builds.

---

## What SB Sees

- Their own instruments AND all SMB instruments they sponsor
- Consolidated totals across all sub-members they manage
- Ability to drill into any individual SMB's data
- PPS, Stop Cheque, Signature Vault for their own accounts + all SMB accounts they hold
- Settlement: own clearing position + SMB-wise breakdowns
- Presentment File: their own lots + all SMB lots routed through them
- SMB Registry, SMB Ledger, SMB Forwarding Log — full access
- All reports: cross-SMB aggregations available

## What SMB Sees

- ONLY their own instruments — zero visibility into other SMBs or the SB's own instruments
- PPS / Stop Cheque / Vault scoped strictly to their own accounts
- Settlement: only their own clearing position (no SB or peer-SMB data)
- Presentment File: only their own instruments
- SMB Registry / Ledger / Forwarding Log — their own record only (read-only)
- No cross-SMB aggregations — single-bank view throughout

---

## Implementation Rules

### Every page component MUST do this:
```jsx
// 1. Resolve bank context at the top of the component (or from a shared context/hook)
const { bankType, bankId, bankName } = useBankContext()
// bankType: 'SB' | 'SMB'

// 2. Scope all data fetches to bankType
// SB: fetch own + all sponsored SMBs (or filter by selected SMB)
// SMB: fetch only bankId-scoped records

// 3. Conditionally render SMB-specific panels / selectors
{bankType === 'SB' && <SMBSelector ... />}
```

### Data fetching:
- All API calls include `bank_type` and `bank_id` from context
- SB may pass an optional `smb_id` filter to drill into one SMB
- SMB calls never include cross-bank parameters — backend enforces this too
- Backend RBAC double-checks: an SMB JWT cannot fetch another bank's data regardless of params

### Downloads (CXF, images, settlement files):
- SB download: may contain consolidated file (all SMBs) OR per-SMB file (with SMB selector)
- SMB download: always single-bank file, filename contains their own IFSC only

### Navigation:
- SMB-only pages (e.g. SMB Ledger viewed as the SMB itself): shown to SMB users only
- SB management pages (e.g. SMB Registry — managing all sub-members): shown to SB users only
- Shared pages (Inward Queue, Presentment File, Settlement): adapt their data scope per bankType

### Config / Vault / PPS / Stop Cheque:
- SB admin: can configure thresholds for their own bank AND set per-SMB overrides
- SMB admin: can configure only their own bank's settings (within SB-permitted ranges)
- Signature Vault: SB holds vault entries for their own accounts + can look up SMB accounts
- PPS / Stop Cheque: same scoping as Vault above

---

## useBankContext Hook (shared)

```jsx
// apps/web/src/shared/context/BankContext.jsx
// Provides: { bankType, bankId, bankIfsc, bankName, sponsorBankId (SMB only) }
// Resolved from: decoded JWT claims on login
// Demo mode: exposes toggleBankType() ONLY when import.meta.env.VITE_DEMO_MODE === 'true'
```

Every page uses `useBankContext()` — never hardcode bank type or derive it from URL params.

---

## Forbidden Patterns

- Showing SMB-only aggregation controls to an SMB user (no cross-bank drill-down for SMBs)
- Showing SB management panels (SMB Registry, SMB Forwarding Log admin) to SMB users
- Fetching data without bank_type scoping — even in mock/demo data
- Hardcoding `isSB = true` anywhere outside demo toggle logic
- Demo toggle in any file not explicitly marked `// DEMO ONLY — remove in production`

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| Every new page uses `useBankContext()` | Code review: pages without `useBankContext` import flagged HIGH | PR merge |
| SB-only panels gated with `bankType === 'SB'` check | `security-auditor` agent: SMB management UI without gate = CRITICAL | PR merge blocked |
| API calls include bank_type from context, not hardcoded | Semgrep pattern: hardcoded `bank_type: 'SB'` or `bank_type: 'SMB'` in fetch calls | PR merge blocked |
| Demo toggle only in VITE_DEMO_MODE builds | Semgrep pattern: `toggleBankType` outside BankContext.jsx without env guard | PR merge blocked |
| Backend enforces bank_id isolation regardless of frontend | `security-auditor` agent + database.md rule: every query has `bank_id` in WHERE clause | PR merge blocked (CRITICAL) |
