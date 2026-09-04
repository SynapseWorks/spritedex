#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS spritedex_schema_migrations (
    migration_name TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
SQL

is_applied() {
  local name="$1"
  [[ "$(psql "$DATABASE_URL" -Atqc "SELECT COUNT(*) FROM spritedex_schema_migrations WHERE migration_name = '$name'")" == "1" ]]
}

record_applied() {
  local name="$1"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c \
    "INSERT INTO spritedex_schema_migrations (migration_name) VALUES ('$name') ON CONFLICT DO NOTHING" >/dev/null
}

if ! is_applied "000_base_schema.sql"; then
  species_exists="$(psql "$DATABASE_URL" -Atqc "SELECT to_regclass('public.species') IS NOT NULL")"
  if [[ "$species_exists" == "f" ]]; then
    echo "==> Applying database/schema.sql"
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/schema.sql
  else
    echo "==> Existing SpriteDex base schema detected; adopting it into migration tracking"
  fi
  record_applied "000_base_schema.sql"
fi

for migration in database/migrations/*.sql; do
  name="$(basename "$migration")"
  if is_applied "$name"; then
    echo "==> Already applied: $name"
    continue
  fi
  echo "==> Applying $name"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$migration"
  record_applied "$name"
done

echo "SpriteDex production migrations are current."
