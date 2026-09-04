from typing import Any

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .auth import me_router, router as auth_router
from .database import engine
from .encounter_routes import router as encounter_router
from .field_routes import router as field_router
from .inaturalist import encounter_sync_router, router as inaturalist_router
from .media_routes import router as media_router
from .oauth_redirect import InaturalistCallbackRedirectMiddleware
from .production import configure_production
from .species_routes import router as species_router
from .taxon_routes import router as taxon_router

app = FastAPI(
    title="SpriteDex API",
    version="0.6.0",
    description="V1 API for field encounters, Regional Dex discovery, media, authentication, and iNaturalist sync.",
)
app.add_middleware(InaturalistCallbackRedirectMiddleware)
app.include_router(auth_router)
app.include_router(me_router)
app.include_router(encounter_router)
app.include_router(media_router)
app.include_router(encounter_sync_router)
app.include_router(inaturalist_router)
app.include_router(taxon_router)
app.include_router(field_router)
app.include_router(species_router)


def _mapping(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


@app.get("/health")
def health() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ok", "database": "ok"}


@app.get("/api/regions")
def list_regions() -> list[dict[str, Any]]:
    sql = text(
        """
        SELECT
            region_id,
            name,
            slug,
            region_type,
            description,
            status,
            visibility,
            is_playable,
            inat_place_id
        FROM regions
        WHERE status = 'active'
          AND visibility IN ('public', 'unlisted')
        ORDER BY name
        """
    )
    with engine.connect() as connection:
        return [_mapping(row) for row in connection.execute(sql)]


@app.get("/api/regions/at")
def regions_at(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
) -> list[dict[str, Any]]:
    sql = text(
        """
        SELECT region_id, name, slug, region_type
        FROM regions
        WHERE status = 'active'
          AND is_playable = TRUE
          AND ST_Covers(
              boundary,
              ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)
          )
        ORDER BY name
        """
    )
    with engine.connect() as connection:
        rows = connection.execute(
            sql,
            {"latitude": latitude, "longitude": longitude},
        )
        return [_mapping(row) for row in rows]


@app.get("/api/regions/{region_id}")
def get_region(region_id: int) -> dict[str, Any]:
    sql = text(
        """
        SELECT
            region_id,
            name,
            slug,
            region_type,
            description,
            status,
            visibility,
            is_playable,
            inat_place_id,
            boundary_source,
            boundary_source_ref,
            boundary_updated_at,
            ST_AsGeoJSON(ST_Envelope(boundary)) AS bounding_box_geojson
        FROM regions
        WHERE region_id = :region_id
        """
    )
    with engine.connect() as connection:
        row = connection.execute(sql, {"region_id": region_id}).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Region not found")
    return _mapping(row)


@app.get("/api/regions/{region_id}/dex")
def get_region_dex(
    region_id: int,
    eligible_only: bool = True,
) -> list[dict[str, Any]]:
    sql = text(
        """
        SELECT
            rs.region_id,
            s.species_id,
            s.common_name,
            s.scientific_name,
            s.category,
            s.inat_taxon_id,
            s.inat_rank,
            s.iconic_taxon_name,
            s.inat_default_photo_url,
            rs.dex_eligible,
            rs.seasonal_active,
            rs.public_tier,
            rs.encounter_tier,
            rs.tier_confidence,
            rs.encounter_score,
            rs.encounter_rate,
            rs.last_observed_at
        FROM region_species rs
        JOIN species s ON s.species_id = rs.species_id
        WHERE rs.region_id = :region_id
          AND (:eligible_only = FALSE OR rs.dex_eligible = TRUE)
        ORDER BY COALESCE(s.common_name, s.scientific_name), s.species_id
        """
    )
    with engine.connect() as connection:
        rows = connection.execute(
            sql,
            {"region_id": region_id, "eligible_only": eligible_only},
        )
        return [_mapping(row) for row in rows]


# Mount the built mobile client only after all API routes have been registered.
configure_production(app)
