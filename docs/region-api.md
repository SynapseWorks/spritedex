# SpriteDex Region API v1

This document defines the first production-facing API contract for SpriteDex Regions.

The Region API sits above the existing SpeciesDex / Encounter model. A Region is a SpriteDex-owned geographic polygon; it may optionally link to an iNaturalist Place but is not dependent on one.

## Design rules

1. An encounter may belong to many Regions.
2. Region membership is calculated server-side from GPS location and PostGIS geometry.
3. Encounter tiers are gameplay metadata, not claims of scientific rarity.
4. Scientific conservation status remains distinct from SpriteDex encounter tiers.
5. Sensitive or obscured locations must never be reverse-engineered or exposed through Region endpoints.
6. The client never directly mutates `encounter_regions`, `user_region_species`, or `user_region_progress`.
7. Posting observations to iNaturalist must use the individual user's iNaturalist authorization, never a shared SpriteDex group account.

---

## Public Region discovery

### `GET /api/regions`

Lists discoverable Regions.

Suggested query parameters:

- `type`
- `parent_region_id`
- `playable=true|false`
- `visibility=public`
- `lat`
- `lon`
- `limit`
- `cursor`

Example response:

```json
{
  "regions": [
    {
      "regionId": 153,
      "name": "Example Conservation Area",
      "slug": "example-conservation-area",
      "regionType": "conservation_area",
      "isPlayable": true,
      "inatPlaceId": null
    }
  ]
}
```

### `GET /api/regions/{region_id}`

Returns Region metadata, primary breadcrumb, related Regions, partner status, and public-safe map geometry or map bounds.

Sensitive/private geometry should be generalized or omitted according to policy.

### `GET /api/regions/at?lat={lat}&lon={lon}`

Returns playable Regions containing a supplied point.

This is useful for preview UI, but encounter submission must still calculate membership server-side from the stored encounter location rather than trusting a client-provided Region list.

---

## Regional Dex

### `GET /api/regions/{region_id}/dex`

Returns the active Regional Dex.

Suggested parameters:

- `category`
- `tier`
- `season=current|all`
- `discovered=true|false` when authenticated
- `cursor`

Example item:

```json
{
  "speciesId": 42,
  "commonName": "American Robin",
  "scientificName": "Turdus migratorius",
  "encounterTier": "familiar",
  "dexEligible": true,
  "conservationStatus": null,
  "sensitiveLocation": false,
  "discovered": true
}
```

### `GET /api/regions/{region_id}/catalogue`

Returns documented regional taxa, including records that are not currently `dex_eligible`.

This separates the complete ecological catalogue from the playable active Dex.

---

## User Region progress

### `GET /api/me/regions`

Returns Regions in which the current user has progress.

Example:

```json
{
  "regions": [
    {
      "regionId": 153,
      "discoveredSpeciesCount": 184,
      "eligibleSpeciesCount": 503,
      "completionPercent": 36.581,
      "regionalScore": 1240
    }
  ]
}
```

### `GET /api/me/regions/{region_id}`

Returns one user's summary for one Region.

### `GET /api/me/regions/{region_id}/dex`

Returns the Regional Dex with personal discovery state, first encounter, last encounter, and encounter count.

---

## Encounter write path

### `POST /api/encounters`

The existing encounter endpoint becomes the canonical Region entry point.

High-level server transaction:

1. Validate authenticated SpriteDex user.
2. Save encounter + GPS point.
3. Save media / initial identification state as applicable.
4. Call `process_encounter_regions(encounter_id)`.
5. Return the encounter plus matched public Regions and newly unlocked Regional Dex entries.

The client must not submit its own authoritative `region_ids`.

Suggested success response extension:

```json
{
  "encounterId": 9381,
  "speciesId": 42,
  "regions": [
    {
      "regionId": 153,
      "name": "Example Conservation Area",
      "newRegionalDiscovery": true
    }
  ]
}
```

### `PUT /api/encounters/{encounter_id}`

If location or species changes, the backend re-runs `process_encounter_regions(encounter_id)` so cached game state remains correct.

---

## Leaderboards (reserved for Region v2)

### `GET /api/regions/{region_id}/leaderboard`

Recommended parameters:

- `period=week|month|season|year|all_time`
- `metric=regional_score|unique_taxa|verified_observations|identifications`

Leaderboard snapshots should be precomputed rather than generated from raw encounters on every request.

---

## Challenges and BioBlitzes (reserved for Region v2)

Future endpoints:

- `GET /api/regions/{region_id}/challenges`
- `GET /api/regions/{region_id}/events`
- `GET /api/bioblitzes/{id}`
- `POST /api/bioblitzes/{id}/join`

These should consume the Region model rather than inventing a second geographic system.

---

## iNaturalist integration boundary

SpriteDex owns:

- game progress
- Regional Dex state
- XP / points
- achievements
- challenges
- partner-region features
- cached regional calculations

The iNaturalist relationship should provide or reconcile:

- taxon identity
- user-owned observations
- community identification state
- public-safe biodiversity context

For authenticated iNaturalist actions, SpriteDex should use individual OAuth authorization. Public read traffic should prefer the supported `api.inaturalist.org` API and cached/batched synchronization rather than repetitive per-screen polling.

---

## Internal/admin endpoints later

Region creation and authoritative boundary changes should not initially be public user endpoints.

Future protected operations may include:

- create Region
- import/replace boundary
- link iNaturalist Place
- set Region relationships
- mark a Region partner-managed
- override `dex_eligible`
- override encounter tier
- flag sensitive regional taxa

These operations require provenance and audit history before organizational partners are introduced.
