#!/bin/bash
# Runs after Claude Code edits a Python file — quick lint check

FILE="$1"

if [ -z "$FILE" ]; then
    exit 0
fi

# Only lint Python files
if [[ "$FILE" != *.py ]]; then
    exit 0
fi

echo "Linting $FILE..."

# Ruff — fast Python linter
if command -v ruff &> /dev/null; then
    ruff check "$FILE" --select E,F,W,I --fix
fi

# Check for print() statements (forbidden — use structlog)
if grep -n "^[^#]*print(" "$FILE" 2>/dev/null; then
    echo "WARNING: print() found in $FILE — use structlog for structured logging"
fi

# Check for hardcoded localhost/IP that should be in config
if grep -nE "http://localhost|http://127\.|http://10\.|http://192\." "$FILE" 2>/dev/null; then
    echo "WARNING: Hardcoded URL found in $FILE — use config_service instead"
fi

exit 0
