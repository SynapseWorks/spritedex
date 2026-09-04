from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from .database import engine

router = APIRouter()


@router.get("/api/species/{species_id}")
def get_species(species_id: int) -> dict[str, Any]:
    sql = text(
        """
        SELECT
            species_id,
            common_name,
            scientific_name,
            kingdom,
            category,
            description,
            edible_status,
            toxicity_status,
            inat_taxon_id,
            iconic_taxon_name,
            created_at
        FROM species
        WHERE species_id = :species_id
        """
    )
    with engine.connect() as connection:
        row = connection.execute(sql, {"species_id": species_id}).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Species not found")
    return dict(row._mapping)
