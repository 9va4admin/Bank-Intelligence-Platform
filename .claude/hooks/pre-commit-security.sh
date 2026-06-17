#!/bin/bash
# Runs before Claude Code commits — enforces banking-grade security checks

set -e

echo "=== ASTRA Pre-Commit Security Check ==="

# 1. Gitleaks — scan for secrets
if command -v gitleaks &> /dev/null; then
    echo "Scanning for secrets with gitleaks..."
    gitleaks detect --staged --no-banner
    if [ $? -ne 0 ]; then
        echo "BLOCKED: Secret detected in staged files. Remove before committing."
        exit 1
    fi
else
    echo "WARNING: gitleaks not installed. Install: https://github.com/gitleaks/gitleaks"
fi

# 2. Check for common secret patterns (belt and suspenders)
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM)
for file in $STAGED_FILES; do
    if git show ":$file" | grep -qiE "(password|secret|api_key|private_key)\s*=\s*['\"][^'\"]{8,}"; then
        echo "BLOCKED: Potential hardcoded credential in $file"
        echo "Use config_service to fetch secrets from HashiCorp Vault."
        exit 1
    fi
done

# 3. Warn if modifying NGCH adapter or audit service (require PR)
for file in $STAGED_FILES; do
    if echo "$file" | grep -qE "(ngch_adapter|audit_service|ngch_filer)"; then
        echo "WARNING: Changes to $file require PR review before merge."
        echo "These are NGCH filing / audit trail components — critical path."
    fi
done

# 4. Check no SELECT * on known PII tables
for file in $STAGED_FILES; do
    if echo "$file" | grep -qE "\.py$"; then
        if git show ":$file" | grep -qiE "SELECT \* FROM (cheque_instruments|agent_decisions|users|ej_raw_logs)"; then
            echo "BLOCKED: SELECT * on PII table in $file"
            echo "Always specify explicit column list on PII tables."
            exit 1
        fi
    fi
done

echo "=== Security check passed ==="
exit 0
