# Runbook: platform component down

Raised by the infrastructure health monitor (HEALTH_COMPONENT_DOWN / HEALTH_COMPONENT_STILL_DOWN).

1. Open Ops > System Health: which component, since when, and the last error.
2. Confirm from the host (not only from ASTRA): is the container or pod running, and does its port answer?
3. Check what depends on it: Yugabyte or Redis down stops decisions and the review queue; Temporal down stops all workflows; Kafka down stops inward fan-out; MinIO down stops image reads; Immudb down stops audit writes; the model servers down send cheques to human review.
4. Restart per the bank's deployment procedure; do not clear data volumes.
5. Watch for the recovery email; if the component flaps, raise it with ASTRA support with the component name and the times from the alert emails.
