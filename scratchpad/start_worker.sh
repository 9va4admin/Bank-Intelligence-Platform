#!/bin/bash
export BANK_ID=saraswat-coop
export ASTRA_SECRETS_BACKEND=env
export ASTRA_ENV=development
export ENV=development
export OPA_REQUIRED=false
export TEMPORAL_ADDRESS=localhost:17233
export TEMPORAL_NAMESPACE=default
export ASTRA_SECRET_REDIS_CONFIG_URL=redis://localhost:16379/1
export ASTRA_SECRET_DB_CONFIG_DSN=postgresql://yugabyte:yugabyte@localhost:15433/yugabyte
export ASTRA_SECRET_REDIS_CTS_URL=redis://localhost:16379/0
export ASTRA_SECRET_DB_CTS_DSN=postgresql://yugabyte:yugabyte@localhost:15433/yugabyte
export ASTRA_SECRET_KAFKA_BOOTSTRAP_SERVERS=localhost:19092
export ASTRA_SECRET_MINIO_ENDPOINT=localhost:19000
export ASTRA_SECRET_MINIO_ACCESS_KEY=astra-dev
export ASTRA_SECRET_MINIO_SECRET_KEY=astra-dev-secret
export ASTRA_SECRET_PII_HASH_PEPPER=dev-pepper-change-before-prod-saraswat-coop
export ASTRA_SECRET_TEMPORAL_HOST=localhost:17233
export ASTRA_SECRET_NGCH_API_KEY=pilot-placeholder

python -u -m modules.cts.worker --bank-id saraswat-coop 2>&1
