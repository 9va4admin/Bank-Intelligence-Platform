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
# Only files being ADDED (new, not modified) — for TDD pairing check
NEW_FILES=$(git diff --cached --name-only --diff-filter=A)
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

# 9. TDD pairing — every new implementation file must have a paired test file
for file in $NEW_FILES; do
    # Python: modules/, shared/, apps/api/, apps/ai-server/
    if echo "$file" | grep -qE "^(modules|shared|apps)/.*\.py$" && \
       ! echo "$file" | grep -qE "(__init__|test_|migrations/)"; then
        dir=$(dirname "$file")
        base=$(basename "$file" .py)
        test_path="tests/${dir}/test_${base}.py"
        if ! git ls-files --error-unmatch "$test_path" 2>/dev/null && \
           ! echo "$NEW_FILES" | grep -qF "$test_path"; then
            echo "BLOCKED: New Python file '$file' has no paired test file."
            echo "Expected: $test_path"
            echo "TDD rule: write the test first (RED), then the implementation (GREEN)."
            exit 1
        fi
    fi
    # JSX/JS: React components and pages
    if echo "$file" | grep -qE "^apps/web/src/(modules|shared)/.*\.(jsx|js)$" && \
       ! echo "$file" | grep -qE "(\.test\.|test-setup|main\.jsx)"; then
        dir=$(dirname "$file")
        base=$(basename "$file" | sed 's/\.\(jsx\|js\)$//')
        test_path="${dir}/${base}.test.jsx"
        if ! git ls-files --error-unmatch "$test_path" 2>/dev/null && \
           ! echo "$NEW_FILES" | grep -qF "$test_path"; then
            echo "BLOCKED: New JSX file '$file' has no paired test file."
            echo "Expected: $test_path"
            echo "TDD rule: write the test first (RED), then the implementation (GREEN)."
            exit 1
        fi
    fi
done

# 10. No @pytest.mark.skip in committed test files — skipped tests hide missing coverage
for file in $STAGED_FILES; do
    if echo "$file" | grep -qE "^tests/.*test_.*\.py$"; then
        if git show ":$file" | grep -qE "@pytest\.mark\.skip"; then
            echo "BLOCKED: @pytest.mark.skip found in $file"
            echo "Skipped tests do not count toward coverage. Fix or remove the skip."
            exit 1
        fi
    fi
done

# 8. Rules constitution — every .claude/rules/*.md must have an ## Enforcement section
for file in $STAGED_FILES; do
    if echo "$file" | grep -qE "^\.claude/rules/.*\.md$"; then
        if ! git show ":$file" | grep -q "^## Enforcement"; then
            echo "BLOCKED: Rules file $file has no ## Enforcement section."
            echo "Per RULES-CONSTITUTION.md: every rule must specify what enforces it."
            echo "Add an '## Enforcement' section before committing this rules file."
            exit 1
        fi
    fi
done

echo "=== Security and isolation checks passed ==="
exit 0
