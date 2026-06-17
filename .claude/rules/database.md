# Database Rules (YugabyteDB YSQL + Redis)

## YugabyteDB
- Driver: `asyncpg` with `sqlalchemy[asyncio]` — never synchronous psycopg2 in async code
- Connection pool: pgbouncer in transaction mode — max 10 connections per pod
- All schema migrations via Alembic — never raw DDL in application code
- Table partitioning: `cheque_instruments` and `ej_raw_logs` partition by `received_at` (monthly range)
- Always include `bank_id` in WHERE clause — row-level multi-tenancy filter

## Query Rules
- Never `SELECT *` on PII tables — always explicit column list
- Always add `LIMIT` clause on list queries — default 50, max 100
- Indexes: every `bank_id + created_at` combo on hot tables must be indexed
- JSONB columns (ai_output, shap_values, raw_json): use `->` operator, never cast to text for search

## Redis Vault
- Key format: `sig:{bank_id}:{sha256(account_number)}` — never store raw account number as key
- TTL: signature vault entries have no TTL (refreshed by VaultSyncWorkflow daily at 6AM)
- PPS vault: `pps:{bank_id}:{sha256(account_number)}:{cheque_series_start}` — TTL = cheque validity
- Redis pipeline for bulk vault warm operations — never individual SET in a loop

## Migrations
- Every migration file: `{timestamp}_{descriptive_name}.py`
- Migrations must be reversible (downgrade function required)
- Test migration on staging YugabyteDB before production
- Never drop columns in a single migration — use deprecation pattern (rename → keep → drop in next release)
