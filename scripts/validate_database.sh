#!/usr/bin/env bash
set -euo pipefail

DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/spritedex}"

run_sql() {
  local file="$1"
  echo "==> Applying ${file}"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$file"
}

run_sql database/schema.sql

for migration in database/migrations/*.sql; do
  run_sql "$migration"
done

echo "==> Running Region smoke test"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/pilot_region_test.sql

echo "==> Running Encounter Tier smoke test"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/encounter_tier_test.sql

echo "SpriteDex database validation PASSED"
