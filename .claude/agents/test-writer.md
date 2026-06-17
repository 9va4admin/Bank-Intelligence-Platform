# Test Writer Agent

## Purpose
Write pytest tests for ASTRA components following banking-grade coverage requirements.

## Coverage Requirements
- Overall: > 80%
- CTS workflow activities: > 95%
- Vault operations: > 95%
- NGCH adapter: 100% (use dedicated test environment, no mocks)
- Audit trail writes: no mocks — use Immudb test instance

## Test Patterns

### CTS Activity Tests
```python
# Always test the IET boundary condition
async def test_activity_completes_before_iet():
    # Verify activity completes in < 550ms (50ms budget for overhead)
    
# Always test vault miss path
async def test_vault_miss_routes_to_human_review():
    # Mock vault to return None, assert workflow routes to HUMAN_REVIEW

# Always test graceful degradation
async def test_cbs_unreachable_continues_with_image_only():
    # CBS timeout should not cause IET breach
```

### Workflow Tests (Temporal test framework)
- Use `temporalio.testing.WorkflowEnvironment`
- Test all terminal states: STP_CONFIRM, STP_RETURN, HUMAN_REVIEW
- Test IETWatchdogWorkflow emergency filing at T-30 seconds
- Test idempotency: same workflow ID run twice = same result

### Vault Tests
- Test Redis pipeline bulk operations
- Test key format: assert `sha256` of account number used, not raw
- Test TTL behaviour for PPS vault entries

### Performance Tests
- CTS agent end-to-end: must complete < 600ms under test harness
- Vault lookup: must complete < 5ms
- Use pytest-benchmark for timing assertions

## What NOT to Mock
- Immudb writes (use test Immudb instance)
- NGCH submissions (use dedicated NGCH test environment)
- HSM signatures (use software HSM in test mode)
