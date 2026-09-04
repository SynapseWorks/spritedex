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


@router.post("", status_code=201)
def create_encounter(
    payload: EncounterCreate,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, Any]:
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
    values["user_id"] = current_user.user_id
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
        raise HTTPException(status_code=400, detail="Unknown species") from exc

    return {"encounter_id": encounter_id, "region_ids": region_ids}


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
                    e.notes
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
          AND e.user_id = :user_id
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
