# SpriteDex V1 Production Runbook

## V1 deployment target

SpriteDex V1 is intentionally deployable as one same-origin HTTPS application:

```text
phone browser
    ↓ HTTPS
SpriteDex web service
    ├── React/Vite static client
    └── FastAPI API
             ↓
      Supabase PostgreSQL/PostGIS
             ↓
      private Supabase Storage
```

This shape avoids CORS complexity, avoids a paid map provider, and keeps private encounter media/coordinates behind SpriteDex authentication.

## Zero-cost pilot path

The V1 pilot is designed to fit within current free tiers:

- public GitHub repository + standard GitHub Actions
- Supabase Free for PostgreSQL/PostGIS and private object storage
- Render Free web service for the combined Docker image
- iNaturalist API/OAuth

Important free-tier compromises:

- a free Render web service can spin down while idle, so the first request after a quiet period may have a cold start;
- Render's local filesystem is ephemeral, which is why production encounter photos use Supabase Storage;
- free Supabase projects can have usage/inactivity limitations and do not replace an independent backup process;
- these choices are appropriate for a V1 pilot, not a promise that a growing public service will remain free forever.

## Production startup

`Dockerfile` builds the React application and Python runtime into one image.

At startup, `scripts/start_production.sh`:

1. runs `scripts/migrate_production.sh`;
2. ensures the private `encounter-media` bucket exists when using Supabase Storage;
3. imports/seeds Ganaraska Forest only if the pilot Region does not already exist;
4. starts Uvicorn/FastAPI on the host-provided `PORT`.

The migration runner records applied SQL files in `spritedex_schema_migrations` so restarts do not replay completed migrations.

## Required environment variables

Never commit production secret values. See `.env.production.example` for names.

Required before basic login/field testing:

- `DATABASE_URL`
- `SPRITEDEX_JWT_SECRET`
- `SPRITEDEX_TOKEN_ENCRYPTION_KEY`
- `SPRITEDEX_MEDIA_PROVIDER=supabase`
- `SPRITEDEX_MEDIA_BUCKET=encounter-media`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SPRITEDEX_APP_URL`

Required before live iNaturalist OAuth testing:

- `INAT_CLIENT_ID`
- `INAT_CLIENT_SECRET`
- `INAT_REDIRECT_URI`

## Media privacy

The production bucket is private. The browser does not receive Supabase's service-role credential or direct private object URLs. It requests a photo through the authenticated SpriteDex route; FastAPI verifies encounter ownership and fetches the object server-side.

The service-role credential is a trusted-backend secret and must never be copied into the React client, source repository, screenshots, or public issue reports.

## Database API exposure

SpriteDex does not use Supabase's browser Data API for application data. FastAPI connects directly to PostgreSQL. Do not grant `anon` or Supabase `authenticated` roles broad access to SpriteDex field-journal tables merely to make the Data API convenient.

After applying the production schema on Supabase, run Supabase security/performance advisors and resolve any meaningful findings before a broader public beta.

## Request safety and logs

The production app adds:

- per-client in-memory V1 rate limiting;
- stricter budgets for authentication, taxon search and OAuth routes;
- request-body size guards (25 MB for photo/field endpoints, 2 MB otherwise);
- request IDs and basic browser security headers;
- operational request logging without request bodies or query strings.

Do not add GPS coordinates, auth tokens, photo names, iNaturalist tokens, or user notes to application logs.

## Backups

Supabase is the live database, but V1 keeps an independent encrypted backup path.

Create a backup from a trusted machine:

```bash
export DATABASE_URL='...'
export SPRITEDEX_BACKUP_PASSPHRASE='...'
bash scripts/backup_database.sh
```

The output is an AES-256 encrypted PostgreSQL custom-format dump. Store it somewhere private and separate from the public GitHub repository.

Test restoration into a non-production database:

```bash
export TARGET_DATABASE_URL='...'
export SPRITEDEX_BACKUP_PASSPHRASE='...'
bash scripts/restore_database.sh backups/spritedex-TIMESTAMP.dump.enc
```

Production CI performs a synthetic encrypted backup and restores it into a clean database so the scripts cannot silently rot.

Field photos require their own object-storage backup/export strategy before SpriteDex grows beyond the small V1 pilot. Supabase's S3-compatible interface can be used for bulk private exports later.

## iNaturalist OAuth production registration

After the final public SpriteDex URL exists, register SpriteDex as an iNaturalist OAuth application using this callback:

```text
https://PUBLIC_SPRITEDEX_HOST/api/inaturalist/callback
```

Configure the same URL as `INAT_REDIRECT_URI`. Configure `SPRITEDEX_APP_URL` as the app root; after successful OAuth the backend returns the browser to SpriteDex.

## V1 release test

Do not tag V1 solely because CI is green. The final release gate is a physical phone test on the production URL:

1. create/sign into a real account;
2. allow camera and precise location permissions;
3. confirm a clearly outside location does not resolve to Ganaraska Forest;
4. enter the Ganaraska Forest pilot Region;
5. photograph an ordinary non-sensitive organism;
6. search/select the taxon and save;
7. confirm the New Discovery response and Regional Dex increment;
8. record the same species again and confirm no first-discovery points are duplicated;
9. if OAuth is live, sync the encounter to the tester's own iNaturalist account;
10. verify the linked iNaturalist observation and report any UI/GPS/photo oddities.

## Current public notices

The built frontend publishes:

- `/privacy.html`
- `/terms.html`
- `/contact.html`

Before invitations expand beyond known V1 testers, replace the pilot contact limitation with a dedicated private support/privacy email and perform a legal/privacy review appropriate to the intended audience and commercialization model.
