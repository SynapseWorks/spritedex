# SpriteDex V1 Pilot Region — Ganaraska Forest

## Decision

The first real SpriteDex Region is **Ganaraska Forest**, owned and managed by the Ganaraska Region Conservation Authority (GRCA).

This is intentionally a `managed_forest` Region rather than forcing the property into the existing `park` or `protected_area` labels. The real pilot exposed that distinction, so migration `011_managed_forest_regions.sql` adds the more accurate Region type.

## Why Ganaraska Forest

- GRCA owns and manages the approximately 11,000-acre Forest.
- GRCA publishes and actively maintains an official Ganaraska Forest Trails ArcGIS product.
- The official map's backing FeatureServer contains a polygon layer explicitly named `GanaraskaForest`.
- The Forest Centre provides a practical, documented control point for automated and later physical field testing.
- The property is large and biodiverse enough to make a Regional Dex meaningful while still being one bounded V1 pilot.
- The location is practical for local Ontario field validation before SpriteDex expands to additional Regions.

## Authoritative geometry

SpriteDex imports the boundary directly from the GRCA ArcGIS FeatureServer:

`https://services1.arcgis.com/d0ZCwU7eGKVeNiEE/ArcGIS/rest/services/GF_Map_Layers/FeatureServer/6`

Service item: `e7e9b6c9ed2b43b28225cc8800e92b79`

Layer: `GanaraskaForest` (ID 6)

The GRCA's public Ganaraska Forest Trails item is the official trail map and was updated July 7, 2026 when this pilot was selected:

`https://www.arcgis.com/home/item.html?id=977aae85ce414affb84e3c7edc23badd`

The importer requests the layer in EPSG:4326 GeoJSON, validates each polygon, unions all returned pieces in PostGIS, and stores the resulting MultiPolygon in `regions.boundary`.

SpriteDex does **not** trace a PDF map, infer a boundary from trails, or substitute OpenStreetMap geometry when this GRCA layer is available.

## Boundary controls

The import must pass all of these checks before the Region is accepted:

1. ArcGIS layer identity is `GanaraskaForest` / `Ganaraska Forest`.
2. At least one polygon geometry is returned.
3. The merged PostGIS geometry is valid.
4. Area is between 25 and 75 km². This deliberately broad sanity range catches a wrong ArcGIS layer without pretending the source geometry must equal a hard-coded acreage forever.
5. **Inside control:** Ganaraska Forest Centre / Northumberland Tourism GPS point `44.074384, -78.504256` must be covered by the polygon.
6. **Outside control:** Port Hope control point `43.949085, -78.292440` must not be covered by the polygon.

The stored Region records the GRCA layer URL as `boundary_source_ref` and uses the ArcGIS layer's edit timestamp when available.

## iNaturalist pilot evidence

Running:

```bash
python scripts/import_pilot_region.py --seed-inaturalist
```

performs a small, rate-conscious bootstrap rather than bulk scraping iNaturalist.

For the current season and each of the previous four years, the script requests at most two 200-record pages of nearby Research Grade observations, waiting between requests. The search radius is deliberately broader than the Region; **PostGIS decides which records actually belong to Ganaraska Forest**.

Before an observation is eligible for fine-scale Region matching, SpriteDex requires:

- Research Grade;
- not captive/cultivated;
- public/open geoprivacy;
- not marked obscured;
- no private location payload;
- public/open taxon geoprivacy;
- positional accuracy present and no worse than 1,000 m;
- a public coordinate;
- species-rank taxon for the current V1 `species` table;
- an observer ID and observation date.

SpriteDex never attempts to reconstruct or infer hidden coordinates. Records that fail these safeguards are simply not used for fine-scale Ganaraska metrics.

Safe records are normalized into `external_observations`, then existing SpriteDex functions perform:

```text
refresh_external_observation_regions(region_id)
        ↓
PostGIS exact boundary match
        ↓
calculate_region_encounter_tiers(region_id)
        ↓
region_species
        ↓
first real Ganaraska Regional Dex
```

## Reproducible validation

`.github/workflows/pilot-region-ci.yml` starts a clean PostGIS database, applies every SpriteDex migration, fetches the live GRCA boundary, seeds a bounded iNaturalist sample, and requires:

- valid persisted Ganaraska geometry;
- expected area sanity range;
- inside/outside control points to behave correctly;
- at least one safe public iNaturalist observation to intersect the Region;
- at least one Regional Dex taxon to be generated.

The CI baseline uses September 4, 2026 as the seasonal calculation date so the integration check stays reproducible. Normal imports default to the current date.

## Local import

After preparing the database and Python environment:

```bash
docker compose -f docker-compose.dev.yml up -d db
bash scripts/validate_database.sh
python -m pip install -r backend/requirements.txt
python scripts/import_pilot_region.py --seed-inaturalist
```

Boundary-only refresh:

```bash
python scripts/import_pilot_region.py
```

The importer is idempotent: `ganaraska-forest` is updated rather than duplicated, external observations are upserted by source observation ID, and Regional Dex calculations reuse the existing SpriteDex reconciliation functions.

## Final V1 field check still requiring a human

Automated tests can prove the GIS math. They cannot physically carry a phone across a forest boundary.

Before Issue #8 is closed, perform one real field test using the production/mobile client:

1. sign into SpriteDex;
2. confirm GPS at/near the Ganaraska Forest Centre resolves to Ganaraska Forest;
3. record a non-sensitive organism with a photo;
4. verify the encounter appears in the Ganaraska Regional Dex exactly once;
5. confirm a known location outside the Forest does not resolve to the Ganaraska Region;
6. if iNaturalist OAuth is live, sync the observation and verify the linked record.

GRCA currently directs Forest visitors to use its official up-to-date trail map and requires the applicable Forest day pass or membership for recreation. Physical testing should follow current GRCA access rules and trail conditions.
