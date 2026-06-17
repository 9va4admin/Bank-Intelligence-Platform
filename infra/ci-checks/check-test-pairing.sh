#!/bin/bash
# CI check: every implementation file in modules/, shared/, apps/ must have a paired test file.
# Runs on every PR. Fails if any implementation file has no corresponding test.

set -e

FAIL=0
MISSING=()

find_impl_files() {
    find modules/ shared/ apps/ \
        -name "*.py" \
        ! -name "__init__.py" \
        ! -path "*/migrations/*" \
        ! -path "*/__pycache__/*" \
        2>/dev/null
}

while IFS= read -r impl_file; do
    dir=$(dirname "$impl_file")
    base=$(basename "$impl_file" .py)
    test_file="tests/${dir}/test_${base}.py"

    if [ ! -f "$test_file" ]; then
        MISSING+=("$impl_file → expected $test_file")
        FAIL=1
    fi
done < <(find_impl_files)

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "=== TEST PAIRING FAILURES ==="
    for m in "${MISSING[@]}"; do
        echo "  MISSING: $m"
    done
    echo ""
    echo "Every implementation file must have a paired test file."
    echo "TDD rule: test first (RED), implementation second (GREEN)."
    exit 1
fi

echo "Test pairing check passed — all implementation files have test files."
exit 0
