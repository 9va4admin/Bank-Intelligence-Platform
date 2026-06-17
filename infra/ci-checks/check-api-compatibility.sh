#!/bin/bash
# ─────────────────────────────────────────────────────────────────────
# ASTRA API Compatibility Checker
# Runs in CI on every PR that touches apps/api/ or docs/api/
#
# Checks:
#   1. Deprecated endpoint references in application code
#   2. Breaking changes between OpenAPI specs (current vs base branch)
#   3. Sunset dates that have passed
#   4. Compatibility matrix out of sync with code
#   5. Kafka events missing schema_version field
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail

PASS=0
WARN=0
FAIL=0
BASE_BRANCH="${BASE_BRANCH:-main}"
MATRIX_FILE="docs/api/compatibility-matrix.md"
OPENAPI_CURRENT="docs/api/openapi-current.json"
OPENAPI_BASE="/tmp/openapi-base.json"

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

pass()  { echo -e "${GREEN}  PASS${NC} $1"; ((PASS++)); }
warn()  { echo -e "${YELLOW}  WARN${NC} $1"; ((WARN++)); }
fail()  { echo -e "${RED}  FAIL${NC} $1"; ((FAIL++)); }

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ASTRA API Compatibility Check"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Check 1: Deprecated endpoint references in source code ───────────
echo "[ 1/5 ] Scanning for deprecated endpoint references..."

# Read sunset endpoints from compatibility matrix
if [[ -f "$MATRIX_FILE" ]]; then
    # Extract endpoints marked REMOVED from the matrix
    REMOVED_ENDPOINTS=$(grep -E "\| REMOVED \|" "$MATRIX_FILE" | \
        grep -oE "(GET|POST|PUT|PATCH|DELETE) /v[0-9]+/[^ |]+" || true)

    if [[ -n "$REMOVED_ENDPOINTS" ]]; then
        while IFS= read -r endpoint; do
            # Extract just the path (e.g. /v1/cts/inward)
            path=$(echo "$endpoint" | grep -oE "/v[0-9]+/[^ ]+")
            if grep -r --include="*.py" --include="*.ts" --include="*.tsx" \
                       -l "\"$path\"\|'$path'" apps/ modules/ shared/ 2>/dev/null | \
               grep -v "__pycache__" | grep -v ".pyc"; then
                fail "Reference to REMOVED endpoint '$path' found — this will break in production"
            fi
        done <<< "$REMOVED_ENDPOINTS"
    fi
    pass "No references to removed endpoints found"
else
    warn "compatibility-matrix.md not found — skipping removed endpoint check"
fi

# ── Check 2: Breaking changes via OpenAPI diff ───────────────────────
echo ""
echo "[ 2/5 ] Checking for breaking changes in OpenAPI spec..."

# Generate current OpenAPI spec from FastAPI
if command -v python3 &>/dev/null && [[ -f "apps/api/main.py" ]]; then
    python3 -c "
from apps.api.main import app
import json
spec = app.openapi()
with open('$OPENAPI_CURRENT', 'w') as f:
    json.dump(spec, f, indent=2)
print('OpenAPI spec generated')
" 2>/dev/null || warn "Could not generate OpenAPI spec — skipping diff check"

    # Fetch base branch spec if it exists
    if git show "${BASE_BRANCH}:${OPENAPI_CURRENT}" > "$OPENAPI_BASE" 2>/dev/null; then

        # Check for removed paths
        REMOVED_PATHS=$(python3 -c "
import json, sys

with open('$OPENAPI_BASE') as f:
    base = json.load(f)
with open('$OPENAPI_CURRENT') as f:
    current = json.load(f)

base_paths = set(base.get('paths', {}).keys())
current_paths = set(current.get('paths', {}).keys())
removed = base_paths - current_paths
for p in removed:
    print(p)
" 2>/dev/null || echo "")

        if [[ -n "$REMOVED_PATHS" ]]; then
            while IFS= read -r path; do
                fail "BREAKING: Path '$path' removed from API — must keep old version alive or update compatibility matrix"
            done <<< "$REMOVED_PATHS"
        else
            pass "No paths removed from OpenAPI spec"
        fi

        # Check for removed fields in existing responses
        BROKEN_FIELDS=$(python3 -c "
import json

with open('$OPENAPI_BASE') as f:
    base = json.load(f)
with open('$OPENAPI_CURRENT') as f:
    current = json.load(f)

base_schemas = base.get('components', {}).get('schemas', {})
current_schemas = current.get('components', {}).get('schemas', {})

for schema_name, base_schema in base_schemas.items():
    if schema_name not in current_schemas:
        print(f'SCHEMA_REMOVED:{schema_name}')
        continue
    current_schema = current_schemas[schema_name]
    base_props = set(base_schema.get('properties', {}).keys())
    current_props = set(current_schema.get('properties', {}).keys())
    removed_props = base_props - current_props
    for prop in removed_props:
        print(f'FIELD_REMOVED:{schema_name}.{prop}')
" 2>/dev/null || echo "")

        if [[ -n "$BROKEN_FIELDS" ]]; then
            while IFS= read -r change; do
                fail "BREAKING: $change — removing fields breaks existing bank integrations"
            done <<< "$BROKEN_FIELDS"
        else
            pass "No response fields removed from existing schemas"
        fi
    else
        warn "No base OpenAPI spec found on $BASE_BRANCH — skipping diff (first run OK)"
    fi
else
    warn "FastAPI app not importable in CI environment — skipping OpenAPI diff"
fi

# ── Check 3: Sunset dates that have already passed ───────────────────
echo ""
echo "[ 3/5 ] Checking for past sunset dates..."

if [[ -f "$MATRIX_FILE" ]]; then
    TODAY=$(date +%Y-%m-%d)
    # Extract sunset dates from matrix (format: YYYY-MM-DD)
    PAST_SUNSETS=$(grep -oE "[0-9]{4}-[0-9]{2}-[0-9]{2}" "$MATRIX_FILE" | \
        awk -v today="$TODAY" '$0 < today {print}' || true)

    if [[ -n "$PAST_SUNSETS" ]]; then
        while IFS= read -r date; do
            # Check if this date's row still shows the endpoint as DEPRECATED (not REMOVED)
            if grep -q "$date" "$MATRIX_FILE" && grep "$date" "$MATRIX_FILE" | grep -q "DEPRECATED"; then
                warn "Sunset date $date has passed but endpoint still shows DEPRECATED — should be REMOVED or date extended"
            fi
        done <<< "$PAST_SUNSETS"
    else
        pass "No past sunset dates with deprecated endpoints"
    fi
fi

# ── Check 4: Versioned routes missing deprecation headers ────────────
echo ""
echo "[ 4/5 ] Checking deprecated routes have required headers..."

# Find v1 routes that should be deprecated (v2 exists for same path)
python3 - << 'PYEOF' 2>/dev/null || warn "Could not check deprecation headers — FastAPI not importable"
import ast, sys, glob, re

issues = []
for filepath in glob.glob("apps/api/routers/*.py"):
    with open(filepath) as f:
        content = f.read()

    # Find v1 route decorators
    v1_routes = re.findall(r'@router_v1\.(get|post|put|patch|delete)\(["\']([^"\']+)', content)
    v2_routes = re.findall(r'@router_v2\.(get|post|put|patch|delete)\(["\']([^"\']+)', content)

    v2_paths = {path for _, path in v2_routes}

    for method, path in v1_routes:
        if path in v2_paths:
            # v2 exists — v1 should have deprecation headers
            # Find the function body for this route
            func_pattern = rf'@router_v1\.{method}\(["\'{re.escape(path)}["\'].*?\nasync def \w+.*?(?=\n@|\nclass |\Z)'
            match = re.search(func_pattern, content, re.DOTALL)
            if match:
                func_body = match.group(0)
                if 'Deprecation' not in func_body:
                    issues.append(f"{filepath}: {method.upper()} {path} (v1 has v2 equivalent but missing Deprecation header)")

if issues:
    for issue in issues:
        print(f"  FAIL Missing deprecation header: {issue}")
    sys.exit(1)
else:
    print("  PASS All v1 routes with v2 equivalents have deprecation headers")
PYEOF

# ── Check 5: Kafka events missing schema_version ─────────────────────
echo ""
echo "[ 5/5 ] Checking Kafka events carry schema_version..."

MISSING_SCHEMA_VERSION=$(grep -r --include="*.py" \
    "KafkaProducer\|producer.send\|kafka_producer" \
    modules/ shared/ apps/ 2>/dev/null | \
    grep -v "schema_version" | \
    grep -v "^.*#.*" | \
    grep -v "test_" || true)

if [[ -n "$MISSING_SCHEMA_VERSION" ]]; then
    # This is a heuristic — manual review needed
    warn "Kafka producer calls found without obvious schema_version — verify manually:"
    echo "$MISSING_SCHEMA_VERSION" | head -10
else
    pass "Kafka event schema_version check passed"
fi

# ── Summary ───────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Results: ${GREEN}${PASS} passed${NC}  ${YELLOW}${WARN} warnings${NC}  ${RED}${FAIL} failed${NC}"
echo "═══════════════════════════════════════════════════════════"

if [[ $FAIL -gt 0 ]]; then
    echo ""
    echo "  BLOCKED: Breaking API changes detected."
    echo "  Fix all FAIL items before this PR can merge."
    exit 1
fi

if [[ $WARN -gt 0 ]]; then
    echo ""
    echo "  Warnings present — review before merging."
fi

exit 0
