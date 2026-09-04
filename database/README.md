# SpriteDex Database Development

SpriteDex uses PostgreSQL with PostGIS. The V1 database path is intentionally reproducible locally and in GitHub Actions.

## Start PostGIS locally

```bash
docker compose -f docker-compose.dev.yml up -d db
```

The development database defaults to:

```text
postgresql://postgres:postgres@localhost:5432/spritedex
```

These credentials are for local development only.

## Validate the complete database

You need the PostgreSQL `psql` client installed locally.

```bash
bash scripts/validate_database.sh
```

The validation script applies, in order:

1. `database/schema.sql`
2. every SQL file in `database/migrations/` in filename order
3. `database/pilot_region_test.sql`
4. `database/encounter_tier_test.sql`

The smoke tests run transactionally and roll back their test data.

A successful run ends with:

```text
SpriteDex database validation PASSED
```

## Custom connection

Set `DATABASE_URL` before running the script:

```bash
DATABASE_URL="postgresql://user:password@host:5432/dbname" bash scripts/validate_database.sh
```

Never commit production database credentials.

## GitHub Actions

`.github/workflows/database-ci.yml` starts a clean PostGIS service and runs the same validation script for database-related pull-request changes and pushes to `main`.

This means local development and CI exercise the same schema/migration/test path.

## Migration rule

Do not rewrite previously applied production migrations. Add a new numbered migration for schema changes. The original `database/schema.sql` remains the prototype baseline; V1 evolution happens through `database/migrations/`.
