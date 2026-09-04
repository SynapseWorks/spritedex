from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth import CurrentUser, get_current_user
from .database import engine

router = APIRouter(prefix="/api/taxa", tags=["taxa"])
INAT_TAXA_API_BASE = "https://api.inaturalist.org/v1"


class TaxonImport(BaseModel):
    inat_taxon_id: int = Field(gt=0)


def _first_result(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            return results[0]
    raise HTTPException(status_code=502, detail="Unexpected iNaturalist taxon response")


def _taxon_summary(taxon: dict[str, Any], local_species_id: int | None = None) -> dict[str, Any]:
    photo = taxon.get("default_photo") or {}
    return {
        "inat_taxon_id": taxon.get("id"),
        "scientific_name": taxon.get("name"),
        "common_name": taxon.get("preferred_common_name") or taxon.get("name"),
        "rank": taxon.get("rank"),
        "iconic_taxon_name": taxon.get("iconic_taxon_name"),
        "observations_count": taxon.get("observations_count"),
        "default_photo_url": photo.get("medium_url") or photo.get("url") or photo.get("square_url"),
        "species_id": local_species_id,
    }


def _inat_get(url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = httpx.get(url, timeout=20, **kwargs)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        detail = "iNaturalist taxon request failed"
        if isinstance(exc, httpx.HTTPStatusError):
            detail += f" ({exc.response.status_code})"
        raise HTTPException(status_code=502, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Invalid iNaturalist taxon response") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Unexpected iNaturalist taxon response")
    return payload


def _upsert_local_taxon(taxon: dict[str, Any]) -> dict[str, Any]:
    taxon_id = taxon.get("id")
    if not taxon_id:
        raise HTTPException(status_code=502, detail="iNaturalist taxon response missing ID")

    scientific_name = taxon.get("name") or f"iNaturalist taxon {taxon_id}"
    common_name = taxon.get("preferred_common_name") or scientific_name
    photo = taxon.get("default_photo") or {}
    photo_url = photo.get("medium_url") or photo.get("url") or photo.get("square_url")

    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT species_id FROM species WHERE inat_taxon_id = :taxon_id FOR UPDATE"),
            {"taxon_id": taxon_id},
        ).first()
        values = {
            "common_name": common_name,
            "scientific_name": scientific_name,
            "category": taxon.get("iconic_taxon_name") or "Unknown",
            "inat_taxon_id": taxon_id,
            "iconic_taxon_name": taxon.get("iconic_taxon_name"),
            "inat_rank": taxon.get("rank"),
            "photo_url": photo_url,
        }
        if row is None:
            species_id = connection.execute(
                text(
                    """
                    INSERT INTO species (
                        common_name, scientific_name, category,
                        inat_taxon_id, iconic_taxon_name, inat_rank,
                        inat_default_photo_url, source_updated_at
                    ) VALUES (
                        :common_name, :scientific_name, :category,
                        :inat_taxon_id, :iconic_taxon_name, :inat_rank,
                        :photo_url, NOW()
                    )
                    RETURNING species_id
                    """
                ),
                values,
            ).scalar_one()
        else:
            species_id = row.species_id
            connection.execute(
                text(
                    """
                    UPDATE species
                    SET common_name = :common_name,
                        scientific_name = :scientific_name,
                        category = :category,
                        iconic_taxon_name = :iconic_taxon_name,
                        inat_rank = :inat_rank,
                        inat_default_photo_url = :photo_url,
                        source_updated_at = NOW()
                    WHERE species_id = :species_id
                    """
                ),
                {**values, "species_id": species_id},
            )
    return _taxon_summary(taxon, species_id)


@router.get("/search")
def search_taxa(
    q: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=10, ge=1, le=25),
) -> list[dict[str, Any]]:
    payload = _inat_get(
        f"{INAT_TAXA_API_BASE}/taxa",
        params={"q": q, "per_page": limit, "is_active": "true"},
    )
    results = payload.get("results") or []
    if not isinstance(results, list):
        raise HTTPException(status_code=502, detail="Unexpected iNaturalist taxon response")

    taxon_ids = [item.get("id") for item in results if isinstance(item, dict) and item.get("id")]
    local_by_inat: dict[int, int] = {}
    if taxon_ids:
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT species_id, inat_taxon_id FROM species WHERE inat_taxon_id = ANY(:taxon_ids)"),
                {"taxon_ids": taxon_ids},
            )
            local_by_inat = {row.inat_taxon_id: row.species_id for row in rows}

    return [
        _taxon_summary(item, local_by_inat.get(item.get("id")))
        for item in results
        if isinstance(item, dict)
    ]


@router.post("/import", status_code=201)
def import_taxon(
    payload: TaxonImport,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, Any]:
    del current_user  # authentication is the permission boundary; import itself is shared canonical data
    taxon_payload = _inat_get(f"{INAT_TAXA_API_BASE}/taxa/{payload.inat_taxon_id}")
    taxon = _first_result(taxon_payload)
    return _upsert_local_taxon(taxon)
