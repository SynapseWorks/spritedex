# SpriteDex Backend

SpriteDex V1 uses FastAPI with PostgreSQL/PostGIS. The backend now supports the complete local field encounter loop: authenticated identity, taxon search/import, GPS Region matching, photo evidence, Regional Dex discovery state, and retryable iNaturalist synchronization.

## Current V1 responsibilities

- database health checks
- Region listing and point-in-Region spatial queries
- public Regional Dex reads and species detail
- account registration/sign-in with Argon2 password hashing
- short-lived signed access tokens and revocable rotating refresh sessions
- iNaturalist OAuth connection with encrypted credentials
- iNaturalist taxon search/import into the temporary local `species` reference table
- authenticated encounter creation and ownership
- JPEG/PNG/HEIC/HEIF field-photo validation and storage
- automatic PostGIS encounter-to-Region reconciliation
- exactly-once Regional Dex discovery/points calculation
- private encounter/photo history
- `/api/me` Region progress and personal Regional Dex state
- retryable encounter + photo synchronization to iNaturalist

## Stack

- Python 3.12
- FastAPI
- SQLAlchemy 2 / psycopg 3
- PostgreSQL 16 / PostGIS
- pwdlib / Argon2
- PyJWT
- cryptography / Fernet
- Pillow + pillow-heif
- pytest / respx

## Local setup

Start the development database from the repository root:

```bash
docker compose -f docker-compose.dev.yml up -d db
bash scripts/validate_database.sh
```

Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
```

Create local secrets. Do not commit real secrets:

```bash
export SPRITEDEX_JWT_SECRET="$(openssl rand -hex 32)"
export SPRITEDEX_TOKEN_ENCRYPTION_KEY="<Fernet key>"
export SPRITEDEX_MEDIA_ROOT="./var/media"
```

Real iNaturalist connection additionally requires `INAT_CLIENT_ID`, `INAT_CLIENT_SECRET`, and `INAT_REDIRECT_URI` from a registered iNaturalist OAuth application.

Run the API:

```bash
PYTHONPATH=backend uvicorn app.main:app --reload
```

The default local database URL is `postgresql://postgres:postgres@localhost:5432/spritedex`; override it with `DATABASE_URL`.

## Current endpoint groups

```text
GET  /health

POST /api/auth/register
POST /api/auth/token
POST /api/auth/refresh
POST /api/auth/logout

GET  /api/me
GET  /api/me/regions
GET  /api/me/regions/{region_id}/dex

GET  /api/regions
GET  /api/regions/at
GET  /api/regions/{region_id}
GET  /api/regions/{region_id}/dex
GET  /api/species/{species_id}

GET  /api/taxa/search?q=...
POST /api/taxa/import

POST /api/encounters
GET  /api/encounters
GET  /api/encounters/{encounter_id}
POST /api/encounters/{encounter_id}/photos
GET  /api/encounters/{encounter_id}/photos
GET  /api/encounters/{encounter_id}/photos/{media_id}/file

POST /api/field/encounters
POST /api/field/encounters/{encounter_id}/sync/inaturalist

GET    /api/inaturalist/connect
GET    /api/inaturalist/callback
GET    /api/inaturalist/status
DELETE /api/inaturalist/connection
POST   /api/encounters/{encounter_id}/sync/inaturalist
```

## Field encounter request

`POST /api/field/encounters` is multipart. Put the normal encounter JSON in a `metadata` form field and optionally send a `photo` file, `caption`, and `sync_inaturalist=true|false`.

The encounter is committed locally before photo processing or any remote synchronization. The response includes matched Regions, encounter tier, current Regional Dex progress, `new_discovery`, and per-Region `points_awarded`.

A repeated encounter of the same taxon in the same Region does not award discovery points again. The canonical first encounter ID in `user_region_species` determines whether an encounter represents the unlock.

## Media

V1 accepts JPEG, PNG, HEIC and HEIF up to 20 MB and 40 megapixels. HEIC/HEIF is normalized to JPEG. The database stores a provider-neutral storage key and metadata; the current implementation uses `SPRITEDEX_MEDIA_ROOT` on a persistent filesystem. This can later be replaced by object storage without changing encounter records.

## iNaturalist synchronization

SpriteDex saves its own encounter first. If iNaturalist synchronization fails, the local observation and its Regional Dex progress survive. Retrying is idempotent: an existing iNaturalist observation is reconciled rather than recreated, and photos with an existing remote observation-photo ID are skipped.

Taxon search currently uses the supported `api.inaturalist.org/v1/taxa` search surface. Observation and photo writes use the modern v2 API flow and API JWT authentication.

## Tests

With the database prepared and CI/test secrets set:

```bash
PYTHONPATH=backend pytest -q backend/tests
```

The suite covers auth/ownership, Region matching, Regional Dex progress, iNaturalist OAuth/reconciliation, taxon search/import, image validation/storage, exactly-once discovery scoring, v2 photo upload, and retry idempotency.
