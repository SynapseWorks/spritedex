# iNaturalist Integration V1

SpriteDex treats iNaturalist as the scientific/community observation system and SpriteDex as the exploration/game layer.

## Core rule

**iNaturalist records the living world. SpriteDex turns the living world into somewhere you can explore.**

A SpriteDex encounter is always saved locally first. Connecting or syncing with iNaturalist enriches that encounter; an external failure must never destroy the local field record.

## Current iNaturalist API direction

As of 2026, iNaturalist recommends its newer `api.inaturalist.org` API for new application work. OAuth authorization still happens through `www.inaturalist.org`.

Authenticated flow:

1. SpriteDex creates a short-lived, single-use OAuth state.
2. User authorizes SpriteDex at `https://www.inaturalist.org/oauth/authorize`.
3. Callback exchanges the authorization code for an OAuth access token.
4. SpriteDex exchanges that OAuth token at `/users/api_token` for an iNaturalist API JWT.
5. SpriteDex uses the API JWT for `api.inaturalist.org/v2` requests.
6. The API JWT is cached for less than its documented 24-hour lifetime and refreshed from the OAuth token as needed.

## Credential storage

- OAuth access tokens are encrypted with Fernet before database storage.
- API JWTs are encrypted before database storage.
- `SPRITEDEX_TOKEN_ENCRYPTION_KEY` must be provided by the runtime and never committed.
- OAuth CSRF state is stored only as a SHA-256 digest and is consumed once.
- Disconnecting removes SpriteDex's stored iNaturalist credentials. Users can separately revoke application access from iNaturalist.

## Required runtime configuration

```text
INAT_CLIENT_ID
INAT_CLIENT_SECRET
INAT_REDIRECT_URI
SPRITEDEX_TOKEN_ENCRYPTION_KEY
```

The redirect URI must exactly match the URI registered with the iNaturalist application.

Generate a Fernet key locally with Python:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## API endpoints

```text
GET    /api/inaturalist/connect
GET    /api/inaturalist/callback
GET    /api/inaturalist/status
DELETE /api/inaturalist/connection

POST   /api/encounters/{encounter_id}/sync/inaturalist
```

The connect/status/disconnect and encounter sync endpoints require SpriteDex authentication. The OAuth callback uses the single-use state to resolve the SpriteDex user because browser redirects do not carry the SpriteDex Bearer header.

## Observation creation

When a user explicitly syncs a local encounter, SpriteDex sends the linked iNaturalist taxon, observed timestamp, coordinates, and description to iNaturalist. Media attachment is handled by the encounter/media V1 work and can be added before the public release flow automatically syncs observations.

SpriteDex stores the returned iNaturalist observation ID on the encounter.

## Reconciliation

Calling sync again for an encounter that already has an iNaturalist observation ID performs reconciliation rather than creating a duplicate.

If iNaturalist community identification changes the taxon:

1. SpriteDex maps the iNaturalist taxon ID to a local species record (creating a reference record if necessary).
2. The encounter's species is updated.
3. Region membership is reprocessed.
4. The old species discovery is rebuilt from remaining encounters so a superseded ID does not remain falsely discovered.
5. Personal Regional Dex state is recalculated.

The current iNaturalist quality grade and reconciliation timestamp are retained on the encounter.

## Geoprivacy

SpriteDex never replaces its user's private local encounter coordinates with public iNaturalist coordinates. Public/obscured iNaturalist coordinates are also never reverse-engineered to infer a precise Region.

Fine-scale external observation matching continues to use the privacy/accuracy rules in the Region and Encounter Tier architecture.

## Failure behaviour

If iNaturalist is unavailable or rejects a submission:

- the SpriteDex encounter remains saved;
- `inat_sync_status` becomes `failed`;
- a bounded error message is stored for diagnostics;
- the user can retry later;
- no duplicate local encounter is created.

## API stewardship

External calls must remain rate-conscious and application-oriented. Bulk taxonomy/observation analytics should continue to use cached datasets/import jobs rather than per-user API scraping.
