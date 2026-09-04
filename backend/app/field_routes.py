from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy import text

from .auth import CurrentUser, get_current_user
from .database import engine
from .encounter_routes import EncounterCreate, create_encounter_for_user
from .inaturalist import get_valid_inat_api_jwt, sync_encounter
from .media_routes import save_encounter_photo
from .storage import get_media_storage

router = APIRouter(prefix="/api/field", tags=["field"])
INAT_API_V2 = "https://api.inaturalist.org/v2"


def _first_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            return results[0]
        return payload
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    raise HTTPException(status_code=502, detail="Unexpected iNaturalist response")


def _ensure_observation_uuid(encounter_id: int, user_id: int, api_jwt: str) -> str:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT inat_observation_id, inat_observation_uuid
                FROM encounters
                WHERE encounter_id = :encounter_id AND user_id = :user_id
                """
            ),
            {"encounter_id": encounter_id, "user_id": user_id},
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Encounter not found")
    if row.inat_observation_uuid:
        return str(row.inat_observation_uuid)
    if not row.inat_observation_id:
        raise HTTPException(status_code=409, detail="Encounter has not been synced to iNaturalist")

    try:
        response = httpx.get(
            f"{INAT_API_V2}/observations/{row.inat_observation_id}",
            params={"fields": "id,uuid"},
            headers={"Authorization": f"Bearer {api_jwt}"},
            timeout=20,
        )
        response.raise_for_status()
        observation = _first_payload(response.json())
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not retrieve iNaturalist observation UUID") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Invalid iNaturalist observation response") from exc

    observation_uuid = observation.get("uuid")
    if not observation_uuid:
        raise HTTPException(status_code=502, detail="iNaturalist observation response missing UUID")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE encounters
                SET inat_observation_uuid = :uuid
                WHERE encounter_id = :encounter_id AND user_id = :user_id
                """
            ),
            {"uuid": observation_uuid, "encounter_id": encounter_id, "user_id": user_id},
        )
    return str(observation_uuid)


def sync_pending_photos(encounter_id: int, user_id: int) -> list[dict[str, Any]]:
    api_jwt = get_valid_inat_api_jwt(user_id)
    observation_uuid = _ensure_observation_uuid(encounter_id, user_id, api_jwt)

    with engine.connect() as connection:
        rows = list(
            connection.execute(
                text(
                    """
                    SELECT m.media_id, m.file_path, m.storage_provider,
                           m.original_filename, m.content_type
                    FROM encounter_media m
                    JOIN encounters e ON e.encounter_id = m.encounter_id
                    WHERE m.encounter_id = :encounter_id
                      AND e.user_id = :user_id
                      AND m.media_type = 'photo'
                      AND m.inat_observation_photo_id IS NULL
                    ORDER BY m.media_id
                    """
                ),
                {"encounter_id": encounter_id, "user_id": user_id},
            )
        )

    storage = get_media_storage()
    synced: list[dict[str, Any]] = []
    for row in rows:
        if row.storage_provider != "local":
            raise HTTPException(status_code=501, detail="Configured media provider cannot sync photos yet")
        path = storage.path_for(row.file_path)
        if not path.exists():
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE encounter_media
                        SET inat_sync_status = 'failed',
                            inat_sync_error = 'Stored photo file is missing'
                        WHERE media_id = :media_id
                        """
                    ),
                    {"media_id": row.media_id},
                )
            raise HTTPException(status_code=500, detail="Stored encounter photo is missing")

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE encounter_media
                    SET inat_sync_status = 'pending', inat_sync_error = NULL
                    WHERE media_id = :media_id
                    """
                ),
                {"media_id": row.media_id},
            )

        try:
            with path.open("rb") as handle:
                response = httpx.post(
                    f"{INAT_API_V2}/observation_photos",
                    data={"observation_photo[observation_id]": observation_uuid},
                    files={
                        "file": (
                            row.original_filename or path.name,
                            handle,
                            row.content_type or "image/jpeg",
                        )
                    },
                    headers={"Authorization": f"Bearer {api_jwt}"},
                    timeout=45,
                )
            response.raise_for_status()
            remote = _first_payload(response.json())
            observation_photo_id = remote.get("id")
            if not observation_photo_id:
                raise HTTPException(status_code=502, detail="iNaturalist photo response missing ID")
        except (httpx.HTTPError, ValueError, HTTPException) as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else "iNaturalist photo upload failed"
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE encounter_media
                        SET inat_sync_status = 'failed', inat_sync_error = :error
                        WHERE media_id = :media_id
                        """
                    ),
                    {"error": str(detail), "media_id": row.media_id},
                )
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=502, detail="iNaturalist photo upload failed") from exc

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE encounter_media
                    SET inat_observation_photo_id = :remote_id,
                        inat_sync_status = 'synced',
                        inat_sync_error = NULL,
                        inat_synced_at = NOW()
                    WHERE media_id = :media_id
                    """
                ),
                {"remote_id": observation_photo_id, "media_id": row.media_id},
            )
        synced.append(
            {
                "media_id": row.media_id,
                "inat_observation_photo_id": observation_photo_id,
                "status": "synced",
            }
        )
    return synced


@router.post("/encounters", status_code=201)
async def create_field_encounter(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    metadata: str = Form(...),
    photo: UploadFile | None = File(default=None),
    caption: str | None = Form(default=None, max_length=500),
    sync_inaturalist: bool = Form(default=False),
) -> dict[str, Any]:
    try:
        payload = EncounterCreate.model_validate_json(metadata)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    result = create_encounter_for_user(payload, current_user.user_id)
    encounter_id = result["encounter_id"]

    if photo is not None:
        try:
            result["photo"] = await save_encounter_photo(
                encounter_id=encounter_id,
                user_id=current_user.user_id,
                upload=photo,
                caption=caption,
            )
        except HTTPException as exc:
            # The field record survives a bad/malformed photo. The client can replace it.
            result["photo"] = None
            result["photo_error"] = exc.detail

    if sync_inaturalist:
        try:
            observation = sync_encounter(encounter_id, current_user)
            photos = sync_pending_photos(encounter_id, current_user.user_id)
            result["inaturalist"] = {"status": "synced", "observation": observation, "photos": photos}
        except HTTPException as exc:
            # Local save is the release gate: remote failure must never discard the encounter.
            result["inaturalist"] = {"status": "failed", "detail": exc.detail}
    return result


@router.post("/encounters/{encounter_id}/sync/inaturalist")
def sync_field_encounter(
    encounter_id: int,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, Any]:
    observation = sync_encounter(encounter_id, current_user)
    photos = sync_pending_photos(encounter_id, current_user.user_id)
    return {"status": "synced", "observation": observation, "photos": photos}
