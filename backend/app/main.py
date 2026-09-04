from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .database import engine
from .species_routes import router as species_router

app = FastAPI(
    title="SpriteDex API",
    version="0.1.0",
    description="Core V1 API for ecological encounters and Regional Dex exploration.",
)
app.include_router(species_router)


class EncounterCreate(BaseModel):
    species_id: int
    # Temporary Epic 2 bridge. Epic 3 replaces caller-supplied ownership with auth.
    user_id: int | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    encountered_at: datetime | None = None
    location_description: str | None = None
    habitat: str | None = None
    life_stage: str | None = None
    quantity_estimate: str | None = None
    confidence_level: str | None = None
    notes: str | None = None


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
            s.iconic_taxon_name,
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


@app.post("/api/encounters", status_code=201)
def create_encounter(payload: EncounterCreate) -> dict[str, Any]:
    insert_sql = text(
        """
        INSERT INTO encounters (
            species_id,
            user_id,
            encountered_at,
            location,
            location_description,
            habitat,
            life_stage,
            quantity_estimate,
            confidence_level,
            notes
        ) VALUES (
            :species_id,
            :user_id,
            COALESCE(:encountered_at, NOW()),
            ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
            :location_description,
            :habitat,
            :life_stage,
            :quantity_estimate,
            :confidence_level,
            :notes
        )
        RETURNING encounter_id
        """
    )

    values = payload.model_dump()
    try:
        with engine.begin() as connection:
            encounter_id = connection.execute(insert_sql, values).scalar_one()
            connection.execute(
                text("SELECT process_encounter_regions(:encounter_id)"),
                {"encounter_id": encounter_id},
            )
            region_ids = list(
                connection.execute(
                    text(
                        """
                        SELECT region_id
                        FROM encounter_regions
                        WHERE encounter_id = :encounter_id
                          AND membership_status = 'confirmed'
                        ORDER BY region_id
                        """
                    ),
                    {"encounter_id": encounter_id},
                ).scalars()
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=400,
            detail="Encounter references an unknown user or species",
        ) from exc

    return {"encounter_id": encounter_id, "region_ids": region_ids}


@app.get("/api/encounters/{encounter_id}")
def get_encounter(encounter_id: int) -> dict[str, Any]:
    encounter_sql = text(
        """
        SELECT
            e.encounter_id,
            e.user_id,
            e.species_id,
            s.common_name,
            s.scientific_name,
            e.encountered_at,
            ST_Y(e.location::geometry) AS latitude,
            ST_X(e.location::geometry) AS longitude,
            e.location_description,
            e.habitat,
            e.life_stage,
            e.quantity_estimate,
            e.confidence_level,
            e.notes
        FROM encounters e
        LEFT JOIN species s ON s.species_id = e.species_id
        WHERE e.encounter_id = :encounter_id
        """
    )
    regions_sql = text(
        """
        SELECT r.region_id, r.name, r.slug, r.region_type
        FROM encounter_regions er
        JOIN regions r ON r.region_id = er.region_id
        WHERE er.encounter_id = :encounter_id
          AND er.membership_status = 'confirmed'
        ORDER BY r.name
        """
    )

    with engine.connect() as connection:
        row = connection.execute(
            encounter_sql,
            {"encounter_id": encounter_id},
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Encounter not found")
        result = _mapping(row)
        result["regions"] = [
            _mapping(region)
            for region in connection.execute(
                regions_sql,
                {"encounter_id": encounter_id},
            )
        ]
    return result
