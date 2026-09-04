#!/usr/bin/env bash
set -euo pipefail

: "${TARGET_DATABASE_URL:?TARGET_DATABASE_URL is required}"
: "${SPRITEDEX_BACKUP_PASSPHRASE:?SPRITEDEX_BACKUP_PASSPHRASE is required}"

backup_file="${1:?Usage: scripts/restore_database.sh path/to/backup.dump.enc}"
if [[ ! -f "$backup_file" ]]; then
  echo "Backup file not found: $backup_file" >&2
  exit 1
fi

temp_dump="$(mktemp)"
trap 'rm -f "$temp_dump"' EXIT
chmod 600 "$temp_dump"

echo "==> Decrypting SpriteDex backup"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -pass env:SPRITEDEX_BACKUP_PASSPHRASE \
  -in "$backup_file" \
  -out "$temp_dump"

echo "==> Restoring SpriteDex backup"
pg_restore \
  --dbname "$TARGET_DATABASE_URL" \
  --clean \
  --if-exists \
  --no-owner \
  --no-acl \
  "$temp_dump"

echo "SpriteDex restore complete."
