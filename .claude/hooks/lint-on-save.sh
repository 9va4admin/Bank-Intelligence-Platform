#!/bin/bash
# Runs after Claude Code saves a Python file — checks for common ASTRA violations

FILE="$1"

if [[ "$FILE" != *.py ]]; then
    exit 0
fi

WARNINGS=0

# Check for direct os.environ usage
if grep -n "os\.environ\.get\|os\.environ\[" "$FILE" 2>/dev/null; then
    echo "WARNING: Direct os.environ usage in $FILE — use config_service instead"
    WARNINGS=$((WARNINGS + 1))
fi

# Check for print() statements
if grep -n "^\s*print(" "$FILE" 2>/dev/null; then
    echo "WARNING: print() found in $FILE — use structlog logger instead"
    WARNINGS=$((WARNINGS + 1))
fi

# Check for verify=False
if grep -n "verify=False" "$FILE" 2>/dev/null; then
    echo "ERROR: verify=False in $FILE — never disable TLS verification"
    exit 1
fi

# Check for SELECT * on PII tables
if grep -niE "SELECT \* FROM (cheque_instruments|agent_decisions|users|ej_raw_logs)" "$FILE" 2>/dev/null; then
    echo "ERROR: SELECT * on PII table in $FILE — specify column list explicitly"
    exit 1
fi

if [ $WARNINGS -gt 0 ]; then
    echo "$WARNINGS warning(s) found in $FILE"
fi

exit 0
