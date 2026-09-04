# SpriteDex Pilot Region Workflow

The first pilot is intentionally tiny. The goal is not to populate Ontario. The goal is to prove the atomic SpriteDex loop:

**GPS encounter → Region match → Regional discovery → progress update**

Once this works reliably, leaderboards, BioBlitzes, seasonal Dexes, achievements, and partner Regions can all build on top of it.

## Phase 0 — Apply the Region v1 database layer

Starting from the existing `database/schema.sql`, apply:

1. `database/migrations/001_users.sql`
2. `database/migrations/002_regions.sql`
3. `database/migrations/003_region_processing.sql`

Do not replace the original schema file. These migrations document the evolution from the prototype data model.

## Phase 1 — Run the synthetic smoke test

Run:

`database/pilot_region_test.sql`

The test creates, inside a transaction:

- one temporary user
- one temporary species
- one temporary MultiPolygon Region
- one dex-eligible Region/species relationship
- one encounter point inside the Region

It then runs `process_encounter_regions()` and verifies:

- exactly one confirmed Region membership
- 1 discovered eligible species
- 1 total eligible species
- 100% Regional Dex completion
- the expected regional score

The script ends with `ROLLBACK`, leaving the database unchanged.

Expected notice:

`SpriteDex Region v1 smoke test PASSED`

## Phase 2 — Choose one real pilot Region

Use exactly one real area first.

Good candidates:

- a frequently visited local conservation area for repeated testing
- The Gut Conservation Area for direct Department of Dubious content integration
- a Ganaraska-area property if an authoritative boundary is easy to obtain and field testing is convenient

Selection criteria:

1. authoritative public boundary data is available
2. public visitation is appropriate
3. the area is large enough to contain useful biodiversity observations
4. the boundary does not expose private/sensitive property information
5. we can physically field-test it

## Phase 3 — Load authoritative geometry

Preferred boundary-source order:

1. managing organization / government open GIS
2. authoritative open-data portal
3. existing iNaturalist Place boundary when appropriate
4. manually curated SpriteDex boundary only as a documented fallback

Normalize geometry to EPSG:4326 and validate it before insert.

Illustrative PostGIS insert using a GeoJSON geometry object:

```sql
INSERT INTO regions (
    name,
    slug,
    region_type,
    description,
    boundary,
    boundary_source,
    boundary_source_ref,
    boundary_updated_at,
    status,
    visibility,
    is_playable
)
VALUES (
    :name,
    :slug,
    :region_type,
    :description,
    ST_Multi(
        ST_SetSRID(
            ST_GeomFromGeoJSON(:geojson_geometry),
            4326
        )
    ),
    :boundary_source,
    :boundary_source_ref,
    NOW(),
    'active',
    'public',
    TRUE
);
```

Before activation, verify:

```sql
SELECT
    region_id,
    name,
    ST_IsValid(boundary) AS valid_geometry,
    ST_Area(boundary::geography) / 1000000.0 AS area_sq_km
FROM regions
WHERE slug = :slug;
```

## Phase 4 — Seed the pilot Regional Dex

For the first live pilot, keep the Dex intentionally small.

Start with perhaps 20–50 common, recognizable taxa with credible recent evidence inside the Region. This makes testing understandable before automated rarity/eligibility calculation exists.

Each seed row goes into `region_species` with:

- `dex_eligible = TRUE`
- provisional encounter tier
- encounter score
- source statistics / calculation timestamp when available

The seed set is gameplay scaffolding, not a claim that these are the only species in the Region.

## Phase 5 — Create the first real user encounter

The future API call is `POST /api/encounters`.

For the first database-level field test:

1. create/assign a SpriteDex test user
2. choose one seeded species
3. capture a GPS point while physically inside the pilot Region
4. insert the encounter
5. call:

```sql
SELECT process_encounter_regions(:encounter_id);
```

## Phase 6 — Validate the whole chain

Check Region membership:

```sql
SELECT
    er.encounter_id,
    r.name,
    er.membership_status,
    er.membership_method
FROM encounter_regions er
JOIN regions r ON r.region_id = er.region_id
WHERE er.encounter_id = :encounter_id;
```

Check discovery:

```sql
SELECT
    u.display_name,
    r.name AS region,
    s.common_name,
    urs.first_observed_at,
    urs.encounter_count,
    urs.regional_points
FROM user_region_species urs
JOIN app_users u ON u.user_id = urs.user_id
JOIN regions r ON r.region_id = urs.region_id
JOIN species s ON s.species_id = urs.species_id
WHERE urs.user_id = :user_id;
```

Check cached progress:

```sql
SELECT *
FROM user_region_progress
WHERE user_id = :user_id
  AND region_id = :region_id;
```

## Phase 7 — Test overlapping Regions

After one Region works, add one containing Region or overlapping ecological Region.

The same encounter should create multiple rows in `encounter_regions`, while the biological encounter itself remains one record.

This proves the design:

- one encounter
- one global biological event
- many valid Regional Dex updates
- no duplicated encounter record

## Phase 8 — Connect iNaturalist

Do this only after the local Region loop works.

The production flow becomes:

1. user authenticates SpriteDex
2. user optionally connects their own iNaturalist account via OAuth
3. SpriteDex encounter is created
4. observation is published/reconciled under that user's iNaturalist identity
5. SpriteDex stores the external observation ID
6. community identification changes can reconcile the SpriteDex species assignment
7. `process_encounter_regions()` reruns when a confirmed taxon changes

This sequencing prevents the geographic/game architecture from depending on unfinished OAuth work.

## Definition of pilot success

Region v1 is proven when we can stand physically inside the pilot area, log one real organism, and watch SpriteDex correctly produce:

**Encounter saved**

→ **Region matched**

→ **new Regional Dex discovery**

→ **completion percentage updated**

without manually assigning the Region.
