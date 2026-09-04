# SpriteDex Backend

SpriteDex V1 uses FastAPI with PostgreSQL/PostGIS. The backend currently supports authenticated personal encounters plus public Region/species exploration.

## Current V1 responsibilities

- database health checks
- Region listing and lookup
- point-in-Region spatial queries
- public Regional Dex reads
- species detail
- account registration and sign-in
- Argon2 password hashing
- short-lived signed access tokens
- revocable/rotating refresh sessions
- authenticated encounter creation and ownership
- automatic encounter-to-Region reconciliation through PostGIS
- private encounter history/detail
- `/api/me` Region progress and personal Regional Dex state

External iNaturalist OAuth, media upload and identification services are tracked as later V1 epics.

## Stack

- Python 3.12
- FastAPI
- SQLAlchemy 2
- psycopg 3
- PostgreSQL 16
- PostGIS
- pwdlib / Argon2
- PyJWT
- pytest

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

Create a local JWT signing secret. Do not commit real secrets:

```bash
export SPRITEDEX_JWT_SECRET="$(openssl rand -hex 32)"
```

Windows PowerShell example:

```powershell
$env:SPRITEDEX_JWT_SECRET="replace-with-a-locally-generated-random-secret"
```

Run the API from the repository root:

```bash
PYTHONPATH=backend uvicorn app.main:app --reload
```

On Windows PowerShell:

```powershell
$env:PYTHONPATH="backend"
uvicorn app.main:app --reload
```

The default local database URL is:

```text
postgresql://postgres:postgres@localhost:5432/spritedex
```

Override it with the `DATABASE_URL` environment variable.

## Current endpoints

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
GET  /api/regions/at?latitude=...&longitude=...
GET  /api/regions/{region_id}
GET  /api/regions/{region_id}/dex
GET  /api/species/{species_id}

POST /api/encounters
GET  /api/encounters
GET  /api/encounters/{encounter_id}
```

Encounter endpoints require a Bearer access token. The authenticated user is the only source of encounter ownership; the client cannot submit another `user_id`.

`POST /api/auth/token` uses OAuth2 form fields: send the user's email in the `username` field and their password in `password`.

Access tokens expire after 30 minutes. Refresh tokens are opaque random values; only their SHA-256 digest is stored in PostgreSQL. Refresh rotates the token, and logout revokes the server-side session so related access tokens stop authorizing immediately.

## Tests

With the PostGIS database prepared and `SPRITEDEX_JWT_SECRET` set:

```bash
PYTHONPATH=backend pytest -q backend/tests
```

The integration suite verifies registration, duplicate-email protection, password login, authentication requirements, authenticated encounter ownership, private encounter isolation between users, Regional Dex progress, refresh-token rotation and logout revocation.

GitHub Actions runs the same database preparation plus backend integration suite on backend/database pull-request changes.
