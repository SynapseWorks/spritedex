#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${SPRITEDEX_BACKUP_PASSPHRASE:?SPRITEDEX_BACKUP_PASSPHRASE is required}"

output_dir="${SPRITEDEX_BACKUP_DIR:-backups}"
mkdir -p "$output_dir"
chmod 700 "$output_dir"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="${1:-$output_dir/spritedex-$timestamp.dump.enc}"

echo "==> Creating encrypted SpriteDex backup: $output"
pg_dump "$DATABASE_URL" \
  --format=custom \
  --no-owner \
  --no-acl \
  | openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 \
      -pass env:SPRITEDEX_BACKUP_PASSPHRASE \
      -out "$output"

chmod 600 "$output"
echo "SpriteDex encrypted database backup complete: $output"
