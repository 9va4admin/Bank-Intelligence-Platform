#!/bin/bash
# Runs before Claude Code commits — enforces banking-grade security checks

set -e

echo "=== ASTRA Pre-Commit Security + API Compatibility Check ==="

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

# 5. API compatibility — check for references to REMOVED endpoints
if [[ -f "docs/api/compatibility-matrix.md" ]]; then
    REMOVED=$(grep -E "\| REMOVED \|" docs/api/compatibility-matrix.md | \
        grep -oE "/v[0-9]+/[a-z/{}._-]+" || true)
    for path in $REMOVED; do
        if grep -r --include="*.py" --include="*.ts" --include="*.tsx" \
                   -l "\"${path}\"\|'${path}'" apps/ modules/ shared/ 2>/dev/null | \
           grep -v "__pycache__"; then
            echo "BLOCKED: Reference to REMOVED API endpoint '${path}' in staged files."
            echo "This endpoint was sunset. Update callers to use the current version."
            exit 1
        fi
    done
fi

# 6. Module blast isolation — cross-module Python imports forbidden
for file in $STAGED_FILES; do
    if echo "$file" | grep -qE "^modules/cts/"; then
        if git show ":$file" | grep -qE "from modules\.ej|import modules\.ej"; then
            echo "BLOCKED: Cross-module import in $file"
            echo "modules/cts/ must never import from modules/ej/ — isolation violation."
            exit 1
        fi
    fi
    if echo "$file" | grep -qE "^modules/ej/"; then
        if git show ":$file" | grep -qE "from modules\.cts|import modules\.cts"; then
            echo "BLOCKED: Cross-module import in $file"
            echo "modules/ej/ must never import from modules/cts/ — isolation violation."
            exit 1
        fi
    fi
done

# 6. Detect shared Redis URL used by wrong module
for file in $STAGED_FILES; do
    if echo "$file" | grep -qE "^modules/cts/"; then
        if git show ":$file" | grep -qE "redis\.ej\.|redis-ej"; then
            echo "BLOCKED: CTS code referencing EJ Redis cluster in $file"
            echo "CTS must use redis-cts only."
            exit 1
        fi
    fi
    if echo "$file" | grep -qE "^modules/ej/"; then
        if git show ":$file" | grep -qE "redis\.cts\.|redis-cts"; then
            echo "BLOCKED: EJ code referencing CTS Redis cluster in $file"
            echo "EJ must use redis-ej only."
            exit 1
        fi
    fi
done

echo "=== Security and isolation checks passed ==="
exit 0
