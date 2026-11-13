#!/usr/bin/env bash
set -euo pipefail
# Idempotently append Stage-3 lab-only secrets to existing .env.
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  echo 'Missing .env: retain Stage-2 POSTGRES_PASSWORD and other settings first' >&2
  exit 1
fi
command -v openssl >/dev/null || { echo 'Install openssl first' >&2; exit 1; }
umask 077
for var in AIRFLOW_DB_PASSWORD AIRFLOW_LAB_PASSWORD AIRFLOW_JWT_SECRET LLNET_INTERNAL_TOKEN; do
  if ! grep -q "^${var}=" .env; then
    printf '\n%s=%s\n' "$var" "$(openssl rand -hex 24)" >> .env
    echo "Added $var to .env"
  else
    echo "Kept existing $var"
  fi
done
chmod 600 .env
printf '\nStage-3 lab secrets configured (values intentionally hidden).\n'
