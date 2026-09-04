from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .auth import CurrentUser, get_current_user
from .database import engine

router = APIRouter(prefix="/api/encounters", tags=["encounters"])


class EncounterCreate(BaseModel):
    species_id: int
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


def create_encounter_for_user(payload: EncounterCreate, user_id: int) -> dict[str, Any]:
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
    values["user_id"] = user_id
    try:
        with engine.begin() as connection:
            encounter_id = connection.execute(insert_sql, values).scalar_one()
            connection.execute(
                text("SELECT process_encounter_regions(:encounter_id)"),
                {"encounter_id": encounter_id},
            )

            species = connection.execute(
                text(
                    """
                    SELECT species_id, common_name, scientific_name,
                           inat_taxon_id, inat_rank, iconic_taxon_name,
                           inat_default_photo_url
                    FROM species
                    WHERE species_id = :species_id
                    """
                ),
                {"species_id": payload.species_id},
            ).one()

            region_rows = connection.execute(
                text(
                    """
                    SELECT
                        r.region_id,
                        r.name,
                        r.slug,
                        r.region_type,
                        rs.public_tier,
                        rs.encounter_tier,
                        rs.tier_confidence,
                        COALESCE(rs.encounter_score, 0) AS encounter_score,
                        urs.first_encounter_id,
                        (urs.first_encounter_id = :encounter_id) AS new_discovery,
                        CASE
                            WHEN urs.first_encounter_id = :encounter_id
                            THEN COALESCE(rs.encounter_score, 0)
                            ELSE 0
                        END AS points_awarded,
                        urp.discovered_species_count,
                        urp.eligible_species_count,
                        urp.completion_percent,
                        urp.regional_score
                    FROM encounter_regions er
                    JOIN regions r ON r.region_id = er.region_id
                    LEFT JOIN region_species rs
                      ON rs.region_id = er.region_id
                     AND rs.species_id = :species_id
                    LEFT JOIN user_region_species urs
                      ON urs.user_id = :user_id
                     AND urs.region_id = er.region_id
                     AND urs.species_id = :species_id
                    LEFT JOIN user_region_progress urp
                      ON urp.user_id = :user_id
                     AND urp.region_id = er.region_id
                    WHERE er.encounter_id = :encounter_id
                      AND er.membership_status = 'confirmed'
                    ORDER BY r.name
                    """
                ),
                {
                    "encounter_id": encounter_id,
                    "species_id": payload.species_id,
                    "user_id": user_id,
                },
            )
            regions = [_mapping(row) for row in region_rows]
    except IntegrityError as exc:
        raise HTTPException(status_code=400, detail="Unknown species") from exc

    return {
        "encounter_id": encounter_id,
        "species": _mapping(species),
        "region_ids": [item["region_id"] for item in regions],
        "regions": regions,
        "new_discovery": any(bool(item.get("new_discovery")) for item in regions),
        "inat_sync_status": "not_requested",
    }


@router.post("", status_code=201)
def create_encounter(
    payload: EncounterCreate,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, Any]:
    return create_encounter_for_user(payload, current_user.user_id)


@router.get("")
def list_encounters(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    e.encounter_id,
                    e.species_id,
                    s.common_name,
                    s.scientific_name,
                    e.encountered_at,
                    ST_Y(e.location::geometry) AS latitude,
                    ST_X(e.location::geometry) AS longitude,
                    e.location_description,
                    e.notes,
                    e.inat_observation_id,
                    e.inat_observation_uuid,
                    e.inat_sync_status,
                    e.inat_quality_grade,
                    (
                        SELECT COUNT(*)
                        FROM encounter_media m
                        WHERE m.encounter_id = e.encounter_id
                          AND m.media_type = 'photo'
                    ) AS photo_count
                FROM encounters e
                LEFT JOIN species s ON s.species_id = e.species_id
                WHERE e.user_id = :user_id
                ORDER BY e.encountered_at DESC, e.encounter_id DESC
                LIMIT :limit
                """
            ),
            {"user_id": current_user.user_id, "limit": limit},
        )
        return [_mapping(row) for row in rows]


@router.get("/{encounter_id}")
def get_encounter(
    encounter_id: int,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, Any]:
    encounter_sql = text(
        """
        SELECT
            e.encounter_id,
            e.user_id,
            e.species_id,
            s.common_name,
            s.scientific_name,
            s.inat_taxon_id,
            s.inat_rank,
            s.inat_default_photo_url,
            e.encountered_at,
            ST_Y(e.location::geometry) AS latitude,
            ST_X(e.location::geometry) AS longitude,
            e.location_description,
            e.habitat,
            e.life_stage,
            e.quantity_estimate,
            e.confidence_level,
            e.notes,
            e.inat_observation_id,
            e.inat_observation_uuid,
            e.inat_sync_status,
            e.inat_sync_error,
            e.inat_quality_grade,
            e.inat_synced_at,
            e.inat_last_reconciled_at
        FROM encounters e
        LEFT JOIN species s ON s.species_id = e.species_id
        WHERE e.encounter_id = :encounter_id
          AND e.user_id = :user_id
        """
    )
    regions_sql = text(
        """
        SELECT
            r.region_id,
            r.name,
            r.slug,
            r.region_type,
            rs.public_tier,
            urs.first_encounter_id,
            (urs.first_encounter_id = :encounter_id) AS was_first_regional_discovery,
            urp.discovered_species_count,
            urp.eligible_species_count,
            urp.completion_percent,
            urp.regional_score
        FROM encounter_regions er
        JOIN regions r ON r.region_id = er.region_id
        JOIN encounters e ON e.encounter_id = er.encounter_id
        LEFT JOIN region_species rs
          ON rs.region_id = er.region_id
         AND rs.species_id = e.species_id
        LEFT JOIN user_region_species urs
          ON urs.user_id = e.user_id
         AND urs.region_id = er.region_id
         AND urs.species_id = e.species_id
        LEFT JOIN user_region_progress urp
          ON urp.user_id = e.user_id
         AND urp.region_id = er.region_id
        WHERE er.encounter_id = :encounter_id
          AND er.membership_status = 'confirmed'
        ORDER BY r.name
        """
    )

    with engine.connect() as connection:
        row = connection.execute(
            encounter_sql,
            {"encounter_id": encounter_id, "user_id": current_user.user_id},
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
