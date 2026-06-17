# /security-check

Run a banking-grade security review on staged or specified files.

## Usage
/security-check                    # reviews all staged git changes
/security-check [file_or_dir]      # reviews specific path

## What This Does
1. Scans for hardcoded secrets (patterns: password, secret, key, token)
2. Checks SQL query safety (parameterised vs f-string)
3. Verifies RBAC dependencies on all API routes
4. Confirms audit trail completeness
5. Checks PII masking in log statements
6. Verifies mTLS on all HTTP clients

## Invokes
Uses `security-auditor` agent.

## Output
Findings grouped by severity: CRITICAL → HIGH → MEDIUM → INFO
CRITICAL findings must be fixed before any commit.
