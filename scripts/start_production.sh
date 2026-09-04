#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required}"

bash scripts/migrate_production.sh

if [[ "${SPRITEDEX_MEDIA_PROVIDER:-local}" == "supabase" ]]; then
  bucket="${SPRITEDEX_MEDIA_BUCKET:-encounter-media}"
  has_storage="$(psql "$DATABASE_URL" -Atqc "SELECT to_regclass('storage.buckets') IS NOT NULL")"
  if [[ "$has_storage" == "t" ]]; then
    echo "==> Ensuring private Supabase media bucket exists"
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -v bucket="$bucket" <<'SQL'
INSERT INTO storage.buckets (
    id, name, public, file_size_limit, allowed_mime_types
)
VALUES (
    :'bucket', :'bucket', FALSE, 20971520, ARRAY['image/jpeg', 'image/png']
)
ON CONFLICT (id) DO UPDATE
SET public = FALSE,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;
SQL
  else
    echo "WARNING: Supabase media provider configured but storage.buckets is unavailable"
  fi
fi

pilot_exists="$(psql "$DATABASE_URL" -Atqc "SELECT EXISTS(SELECT 1 FROM regions WHERE slug = 'ganaraska-forest')")"
if [[ "$pilot_exists" != "t" ]]; then
  echo "==> Bootstrapping Ganaraska Forest pilot Region"
  python scripts/import_pilot_region.py \
    --database-url "$DATABASE_URL" \
    --seed-inaturalist
else
  echo "==> Ganaraska Forest pilot Region already present"
fi

exec uvicorn app.main:app \
  --app-dir backend \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips="*"
