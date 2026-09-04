#!/usr/bin/env python3
"""Import and validate the first real SpriteDex Region: Ganaraska Forest.

The Region boundary comes directly from the Ganaraska Region Conservation Authority
(GRCA) ArcGIS FeatureServer. Optional iNaturalist seeding imports a deliberately small,
rate-conscious sample of public Research Grade observations, filters unsafe/uncertain
records, spatially matches them with PostGIS, and calculates the first Regional Dex.
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any

import psycopg

GRCA_LAYER_URL = (
    "https://services1.arcgis.com/d0ZCwU7eGKVeNiEE/ArcGIS/rest/services/"
    "GF_Map_Layers/FeatureServer/6"
)
INAT_OBSERVATIONS_URL = "https://api.inaturalist.org/v1/observations"
USER_AGENT = "SpriteDex/0.1 (https://github.com/SynapseWorks/spritedex)"

REGION_SLUG = "ganaraska-forest"
REGION_NAME = "Ganaraska Forest"
BOUNDARY_SOURCE = "Ganaraska Region Conservation Authority (GRCA)"

# Northumberland Tourism publishes this Forest Centre GPS point. GRCA describes the
# Centre as being in the heart of the Ganaraska Forest.
INSIDE_POINT = (44.074384, -78.504256)  # lat, lon
# Port Hope waterfront/town area: deliberately far outside the managed Forest polygon.
OUTSIDE_POINT = (43.949085, -78.292440)  # lat, lon

# Broad enough to accommodate normal source edits while still catching the wrong layer.
EXPECTED_AREA_KM2 = (25.0, 75.0)


@dataclass
class PilotSummary:
    region_id: int
    name: str
    area_km2: float
    boundary_parts: int
    source_last_edit: str | None
    inside_control_passed: bool
    outside_control_passed: bool
    imported_observations: int = 0
    confirmed_regional_observations: int = 0
    regional_taxa: int = 0
    active_dex_taxa: int = 0


def _fetch_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not fetch JSON from {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected JSON payload from {url}")
    if payload.get("error"):
        raise RuntimeError(f"Remote service returned an error for {url}: {payload['error']}")
    return payload


def _arcgis_source_last_edit(metadata: dict[str, Any]) -> datetime | None:
    value = (metadata.get("editingInfo") or {}).get("lastEditDate")
    if value is None:
        value = metadata.get("lastEditDate")
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def fetch_grca_boundary() -> tuple[list[dict[str, Any]], datetime | None]:
    metadata = _fetch_json(GRCA_LAYER_URL, {"f": "json"})
    if metadata.get("name") not in {"GanaraskaForest", "Ganaraska Forest"}:
        raise RuntimeError(
            f"GRCA layer identity changed unexpectedly: {metadata.get('name')!r}"
        )

    payload = _fetch_json(
        f"{GRCA_LAYER_URL}/query",
        {
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
        },
    )
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        raise RuntimeError("GRCA GanaraskaForest layer returned no polygon features")

    geometries: list[dict[str, Any]] = []
    for feature in features:
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not isinstance(geometry, dict):
            continue
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise RuntimeError(
                f"Unexpected GRCA GanaraskaForest geometry type: {geometry.get('type')}"
            )
        geometries.append(geometry)
    if not geometries:
        raise RuntimeError("GRCA GanaraskaForest layer contained no usable polygons")
    return geometries, _arcgis_source_last_edit(metadata)


def _upsert_boundary(
    connection: psycopg.Connection[Any],
    geometries: list[dict[str, Any]],
    source_last_edit: datetime | None,
) -> tuple[int, float, bool, bool]:
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TEMP TABLE pilot_region_parts (geom geometry(MultiPolygon, 4326)) "
            "ON COMMIT DROP"
        )
        for geometry in geometries:
            cursor.execute(
                """
                INSERT INTO pilot_region_parts (geom)
                SELECT ST_Multi(
                    ST_CollectionExtract(
                        ST_MakeValid(
                            ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)
                        ),
                        3
                    )
                )
                """,
                (json.dumps(geometry),),
            )

        cursor.execute(
            """
            INSERT INTO regions (
                name, slug, region_type, description, boundary,
                boundary_source, boundary_source_ref, boundary_updated_at,
                status, visibility, is_playable, external_metrics_enabled,
                max_external_accuracy_m
            )
            SELECT
                %s,
                %s,
                'managed_forest',
                %s,
                ST_Multi(
                    ST_CollectionExtract(
                        ST_MakeValid(ST_UnaryUnion(ST_Collect(geom))),
                        3
                    )
                ),
                %s,
                %s,
                %s,
                'active',
                'public',
                TRUE,
                TRUE,
                1000
            FROM pilot_region_parts
            ON CONFLICT (slug) DO UPDATE
            SET name = EXCLUDED.name,
                region_type = EXCLUDED.region_type,
                description = EXCLUDED.description,
                boundary = EXCLUDED.boundary,
                boundary_source = EXCLUDED.boundary_source,
                boundary_source_ref = EXCLUDED.boundary_source_ref,
                boundary_updated_at = EXCLUDED.boundary_updated_at,
                status = 'active',
                visibility = 'public',
                is_playable = TRUE,
                external_metrics_enabled = TRUE,
                max_external_accuracy_m = 1000,
                updated_at = NOW()
            RETURNING region_id
            """,
            (
                REGION_NAME,
                REGION_SLUG,
                (
                    "GRCA-owned and managed multi-use forest used as the first "
                    "production SpriteDex Regional Dex pilot."
                ),
                BOUNDARY_SOURCE,
                GRCA_LAYER_URL,
                source_last_edit or datetime.now(timezone.utc),
            ),
        )
        region_id = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT
                ST_IsValid(boundary),
                ST_Area(boundary::geography) / 1000000.0,
                ST_Covers(
                    boundary,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)
                ),
                ST_Covers(
                    boundary,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)
                )
            FROM regions
            WHERE region_id = %s
            """,
            (
                INSIDE_POINT[1],
                INSIDE_POINT[0],
                OUTSIDE_POINT[1],
                OUTSIDE_POINT[0],
                region_id,
            ),
        )
        valid, area_km2, inside, outside = cursor.fetchone()

    if not valid:
        raise RuntimeError("Imported Ganaraska Forest boundary is not a valid geometry")
    if not (EXPECTED_AREA_KM2[0] <= float(area_km2) <= EXPECTED_AREA_KM2[1]):
        raise RuntimeError(
            f"Imported Ganaraska Forest area {float(area_km2):.2f} km² is outside "
            f"the pilot sanity range {EXPECTED_AREA_KM2}"
        )
    if not inside:
        raise RuntimeError("Forest Centre control point did not fall inside the GRCA boundary")
    if outside:
        raise RuntimeError("Port Hope outside-control point unexpectedly fell inside the GRCA boundary")
    return region_id, float(area_km2), bool(inside), not bool(outside)


def _season_window(year: int, month: int) -> tuple[date, date]:
    previous_month = 12 if month == 1 else month - 1
    previous_year = year - 1 if month == 1 else year
    next_month = 1 if month == 12 else month + 1
    next_year = year + 1 if month == 12 else year
    start = date(previous_year, previous_month, 1)
    end = date(next_year, next_month, calendar.monthrange(next_year, next_month)[1])
    return start, end


def _iter_inat_observations(as_of: date, lookback_years: int) -> list[dict[str, Any]]:
    observations: dict[int, dict[str, Any]] = {}
    for year in range(as_of.year - lookback_years + 1, as_of.year + 1):
        start, end = _season_window(year, as_of.month)
        for page in (1, 2):
            payload = _fetch_json(
                INAT_OBSERVATIONS_URL,
                {
                    "lat": INSIDE_POINT[0],
                    "lng": INSIDE_POINT[1],
                    "radius": 25,
                    "d1": start.isoformat(),
                    "d2": end.isoformat(),
                    "quality_grade": "research",
                    "captive": "false",
                    "photos": "true",
                    "per_page": 200,
                    "page": page,
                    "order_by": "observed_on",
                    "order": "desc",
                },
            )
            results = payload.get("results") or []
            if not isinstance(results, list):
                raise RuntimeError("Unexpected iNaturalist observation payload")
            for item in results:
                if isinstance(item, dict) and isinstance(item.get("id"), int):
                    observations[item["id"]] = item
            if len(results) < 200:
                break
            # iNaturalist asks API clients to stay at roughly one request per second.
            time.sleep(1.05)
        time.sleep(1.05)
    return list(observations.values())


def _safe_public_observation(item: dict[str, Any]) -> bool:
    if item.get("obscured") is True:
        return False
    if item.get("private_location"):
        return False
    if item.get("geoprivacy") not in (None, "open"):
        return False
    if item.get("taxon_geoprivacy") not in (None, "open"):
        return False
    if item.get("captive") is True:
        return False
    if item.get("quality_grade") != "research":
        return False
    accuracy = item.get("positional_accuracy")
    if accuracy is None:
        return False
    try:
        if float(accuracy) > 1000:
            return False
    except (TypeError, ValueError):
        return False
    coordinates = (item.get("geojson") or {}).get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return False
    taxon = item.get("taxon") or {}
    # The current Region model is still named species, so V1 seeds species-rank taxa only.
    if taxon.get("rank") != "species" or not taxon.get("id") or not taxon.get("name"):
        return False
    observer = item.get("user") or {}
    return bool(observer.get("id") and item.get("observed_on"))


def _upsert_species(cursor: psycopg.Cursor[Any], taxon: dict[str, Any]) -> int:
    cursor.execute(
        "SELECT species_id FROM species WHERE inat_taxon_id = %s FOR UPDATE",
        (taxon["id"],),
    )
    row = cursor.fetchone()
    common_name = taxon.get("preferred_common_name") or taxon["name"]
    category = taxon.get("iconic_taxon_name") or "Unknown"
    if row:
        species_id = row[0]
        cursor.execute(
            """
            UPDATE species
            SET common_name = %s,
                scientific_name = %s,
                category = %s,
                iconic_taxon_name = %s,
                inat_rank = 'species',
                source_updated_at = NOW()
            WHERE species_id = %s
            """,
            (common_name, taxon["name"], category, taxon.get("iconic_taxon_name"), species_id),
        )
        return species_id

    cursor.execute(
        """
        INSERT INTO species (
            common_name, scientific_name, category,
            inat_taxon_id, iconic_taxon_name, inat_rank, source_updated_at
        ) VALUES (%s, %s, %s, %s, %s, 'species', NOW())
        RETURNING species_id
        """,
        (
            common_name,
            taxon["name"],
            category,
            taxon["id"],
            taxon.get("iconic_taxon_name"),
        ),
    )
    return cursor.fetchone()[0]


def seed_inaturalist(
    connection: psycopg.Connection[Any],
    region_id: int,
    as_of: date,
    lookback_years: int,
) -> tuple[int, int, int, int]:
    observations = _iter_inat_observations(as_of, lookback_years)
    safe = [item for item in observations if _safe_public_observation(item)]
    if not safe:
        raise RuntimeError("No safe public Research Grade iNaturalist observations were returned")

    imported = 0
    with connection.cursor() as cursor:
        for item in safe:
            taxon = item["taxon"]
            species_id = _upsert_species(cursor, taxon)
            longitude, latitude = item["geojson"]["coordinates"][:2]
            observer_id = (item.get("user") or {}).get("id")
            cursor.execute(
                """
                INSERT INTO external_observations (
                    source, source_observation_id, species_id, source_taxon_id,
                    observer_source_user_id, observed_on, created_at_source,
                    location, positional_accuracy_m, quality_grade,
                    geoprivacy, taxon_geoprivacy, captive_cultivated,
                    source_uri, synced_at
                ) VALUES (
                    'inaturalist', %s, %s, %s,
                    %s, %s, %s,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                    %s, 'research', 'open', 'open', FALSE,
                    %s, NOW()
                )
                ON CONFLICT (source, source_observation_id) DO UPDATE
                SET species_id = EXCLUDED.species_id,
                    source_taxon_id = EXCLUDED.source_taxon_id,
                    observer_source_user_id = EXCLUDED.observer_source_user_id,
                    observed_on = EXCLUDED.observed_on,
                    created_at_source = EXCLUDED.created_at_source,
                    location = EXCLUDED.location,
                    positional_accuracy_m = EXCLUDED.positional_accuracy_m,
                    quality_grade = EXCLUDED.quality_grade,
                    geoprivacy = EXCLUDED.geoprivacy,
                    taxon_geoprivacy = EXCLUDED.taxon_geoprivacy,
                    captive_cultivated = FALSE,
                    source_uri = EXCLUDED.source_uri,
                    synced_at = NOW()
                """,
                (
                    item["id"],
                    species_id,
                    taxon["id"],
                    observer_id,
                    item["observed_on"],
                    item.get("created_at"),
                    longitude,
                    latitude,
                    item["positional_accuracy"],
                    item.get("uri"),
                ),
            )
            imported += 1

        cursor.execute("SELECT refresh_external_observation_regions(%s)", (region_id,))
        cursor.execute(
            "SELECT calculate_region_encounter_tiers(%s, %s, %s)",
            (region_id, as_of, lookback_years),
        )
        cursor.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE eor.membership_status = 'confirmed'),
                COUNT(DISTINCT rs.species_id),
                COUNT(DISTINCT rs.species_id) FILTER (WHERE rs.dex_eligible)
            FROM regions r
            LEFT JOIN external_observation_regions eor ON eor.region_id = r.region_id
            LEFT JOIN region_species rs ON rs.region_id = r.region_id
            WHERE r.region_id = %s
            """,
            (region_id,),
        )
        confirmed, regional_taxa, active_dex = cursor.fetchone()

    if confirmed < 1:
        raise RuntimeError(
            "Safe iNaturalist observations were imported, but none intersected the GRCA boundary"
        )
    if regional_taxa < 1:
        raise RuntimeError("Ganaraska pilot calculation produced no Region/species records")
    return imported, int(confirmed), int(regional_taxa), int(active_dex)


def run(database_url: str, seed_inat: bool, as_of: date, lookback_years: int) -> PilotSummary:
    geometries, source_last_edit = fetch_grca_boundary()
    with psycopg.connect(database_url) as connection:
        region_id, area_km2, inside, outside = _upsert_boundary(
            connection, geometries, source_last_edit
        )
        imported = confirmed = regional_taxa = active_dex = 0
        if seed_inat:
            imported, confirmed, regional_taxa, active_dex = seed_inaturalist(
                connection, region_id, as_of, lookback_years
            )
        connection.commit()

    return PilotSummary(
        region_id=region_id,
        name=REGION_NAME,
        area_km2=round(area_km2, 3),
        boundary_parts=len(geometries),
        source_last_edit=source_last_edit.isoformat() if source_last_edit else None,
        inside_control_passed=inside,
        outside_control_passed=outside,
        imported_observations=imported,
        confirmed_regional_observations=confirmed,
        regional_taxa=regional_taxa,
        active_dex_taxa=active_dex,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv(
            "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/spritedex"
        ),
    )
    parser.add_argument("--seed-inaturalist", action="store_true")
    parser.add_argument("--as-of-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--lookback-years", type=int, default=5, choices=range(1, 21))
    args = parser.parse_args()

    summary = run(
        database_url=args.database_url,
        seed_inat=args.seed_inaturalist,
        as_of=args.as_of_date,
        lookback_years=args.lookback_years,
    )
    print("SpriteDex Ganaraska Forest pilot validation PASSED")
    print(json.dumps(asdict(summary), indent=2, default=str))


if __name__ == "__main__":
    main()
