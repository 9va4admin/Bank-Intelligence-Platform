# ASTRA Chaos Mesh DR Scenarios

Four scenarios validating RBI IT Framework control DR-02 (Business Continuity Testing).

| File | Scenario | Severity | Duration | Safe Window |
|---|---|---|---|---|
| `01-dc1-failure.yaml` | DC1 complete failure → DC2 takes 100% | CRITICAL | 10 min | Off-hours only |
| `02-redis-cts-node-failure.yaml` | Redis CTS primary killed → Sentinel failover | HIGH | 3 min | Off-hours |
| `03-vllm-gpu-failure.yaml` | vLLM GPU nodes killed → all cheques → HUMAN_REVIEW | HIGH | 5 min | Off-hours |
| `04-kafka-broker-failure.yaml` | Kafka broker(s) killed → MirrorMaker2 reroute | HIGH/CRITICAL | 2–5 min | Off-hours |

## Running a Scenario

```bash
# Apply a specific scenario manifest (bank_it_admin required)
kubectl apply -f infra/chaos-mesh/01-dc1-failure.yaml

# Monitor the chaos experiment
kubectl get networkchaos,podchaos -n astra-cts-saraswat-coop

# Watch key metrics during chaos (Grafana: cts-iet-vault.json dashboard)
# Critical: cts_iet_breach_total must stay at 0

# Clean up after experiment
kubectl delete -f infra/chaos-mesh/01-dc1-failure.yaml
```

## Pass / Fail — Universal Criteria

These must hold for **every** scenario:

1. `cts_iet_breach_total == 0` — non-negotiable; any breach = scenario FAILED
2. No `AUTO_RETURN` while vault or CBS is degraded — always `HUMAN_REVIEW`
3. No duplicate NGCH filings — Temporal idempotency must hold across restarts
4. Workflows reach terminal state (not FAILED/TIMED_OUT) within IET window

## Quarterly DR Drill Schedule

| Quarter | Date (tentative) | Scenarios | Signed off by |
|---|---|---|---|
| Q3 2026 | 2026-09-15 | 01, 02 (first drill — conservative) | bank_it_admin + ASTRA support |
| Q4 2026 | 2026-12-01 | 03, 04 | bank_it_admin + ASTRA support |
| Q1 2027 | 2027-03-01 | All 4 simultaneously | bank_it_admin |

## Runbooks

Detailed step-by-step runbooks for each scenario (created during first drill):
- `runbooks/dc1-failure-runbook.md` — created Q3 2026 drill
- `runbooks/redis-failure-runbook.md` — created Q3 2026 drill
- `runbooks/vllm-failure-runbook.md` — created Q4 2026 drill
- `runbooks/kafka-failure-runbook.md` — created Q4 2026 drill

Runbooks are living documents — updated after each drill with actual observations.
