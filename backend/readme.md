# SpriteDex Backend

SpriteDex V1 uses FastAPI with PostgreSQL/PostGIS. The backend now has a runnable core API rather than a planning-only placeholder.

## Current V1 responsibilities

- database health checks
- Region listing and lookup
- point-in-Region spatial queries
- Regional Dex reads
- encounter creation
- automatic encounter-to-Region reconciliation through PostGIS
- encounter detail with matched Regions

Authentication, iNaturalist OAuth, media upload, identification services and `/me` ownership enforcement are tracked as later V1 epics.

## Stack

- Python 3.12
- FastAPI
- SQLAlchemy 2
- psycopg 3
- PostgreSQL 16
- PostGIS
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
GET  /api/regions
GET  /api/regions/at?latitude=...&longitude=...
GET  /api/regions/{region_id}
GET  /api/regions/{region_id}/dex
POST /api/encounters
GET  /api/encounters/{encounter_id}
```

`POST /api/encounters` currently accepts an optional `user_id` only as an Epic 2 development bridge. Epic 3 will remove caller-controlled ownership and derive the user from authentication.

## Tests

With the PostGIS database prepared:

```bash
PYTHONPATH=backend pytest -q backend/tests
```

The integration test creates a temporary user, American Robin, playable Region and Regional Dex entry; it then posts an encounter inside the Region and verifies that Region membership and cached user progress are updated.

GitHub Actions runs the same database preparation plus backend integration test on backend/database pull-request changes.
