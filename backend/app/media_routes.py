from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import text

from .auth import CurrentUser, get_current_user
from .database import engine
from .storage import get_media_storage, normalize_image

router = APIRouter(prefix="/api/encounters", tags=["media"])


def _owned_encounter_exists(encounter_id: int, user_id: int) -> bool:
    with engine.connect() as connection:
        return (
            connection.execute(
                text(
                    "SELECT 1 FROM encounters WHERE encounter_id = :encounter_id AND user_id = :user_id"
                ),
                {"encounter_id": encounter_id, "user_id": user_id},
            ).first()
            is not None
        )


def _media_mapping(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


async def save_encounter_photo(
    *,
    encounter_id: int,
    user_id: int,
    upload: UploadFile,
    caption: str | None = None,
) -> dict[str, Any]:
    if not _owned_encounter_exists(encounter_id, user_id):
        raise HTTPException(status_code=404, detail="Encounter not found")

    raw = await upload.read()
    try:
        normalized, extension, content_type = normalize_image(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        storage = get_media_storage()
        stored = storage.save(
            data=normalized,
            user_id=user_id,
            encounter_id=encounter_id,
            extension=extension,
            content_type=content_type,
            original_filename=upload.filename,
        )
    except (RuntimeError, httpx.HTTPError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Encounter photo storage is temporarily unavailable") from exc

    try:
        with engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    INSERT INTO encounter_media (
                        encounter_id, media_type, file_path, caption,
                        storage_provider, original_filename, content_type,
                        size_bytes, sha256, inat_sync_status
                    ) VALUES (
                        :encounter_id, 'photo', :file_path, :caption,
                        :storage_provider, :original_filename, :content_type,
                        :size_bytes, :sha256, 'not_requested'
                    )
                    RETURNING media_id, encounter_id, media_type, caption,
                              storage_provider, original_filename, content_type,
                              size_bytes, sha256, inat_sync_status, created_at
                    """
                ),
                {
                    "encounter_id": encounter_id,
                    "file_path": stored.storage_key,
                    "caption": caption,
                    "storage_provider": stored.storage_provider,
                    "original_filename": stored.original_filename,
                    "content_type": stored.content_type,
                    "size_bytes": stored.size_bytes,
                    "sha256": stored.sha256,
                },
            ).one()
    except Exception:
        storage.delete(stored.storage_key)
        raise

    result = _media_mapping(row)
    result["file_url"] = f"/api/encounters/{encounter_id}/photos/{row.media_id}/file"
    return result


@router.post("/{encounter_id}/photos", status_code=201)
async def upload_photo(
    encounter_id: int,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    file: UploadFile = File(...),
    caption: str | None = Form(default=None, max_length=500),
) -> dict[str, Any]:
    return await save_encounter_photo(
        encounter_id=encounter_id,
        user_id=current_user.user_id,
        upload=file,
        caption=caption,
    )


@router.get("/{encounter_id}/photos")
def list_photos(
    encounter_id: int,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[dict[str, Any]]:
    if not _owned_encounter_exists(encounter_id, current_user.user_id):
        raise HTTPException(status_code=404, detail="Encounter not found")

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT media_id, encounter_id, media_type, caption,
                       storage_provider, original_filename, content_type,
                       size_bytes, sha256, inat_observation_photo_id,
                       inat_sync_status, inat_sync_error, inat_synced_at, created_at
                FROM encounter_media
                WHERE encounter_id = :encounter_id AND media_type = 'photo'
                ORDER BY media_id
                """
            ),
            {"encounter_id": encounter_id},
        )
        result = [_media_mapping(row) for row in rows]
    for item in result:
        item["file_url"] = f"/api/encounters/{encounter_id}/photos/{item['media_id']}/file"
    return result


@router.get("/{encounter_id}/photos/{media_id}/file")
def get_photo_file(
    encounter_id: int,
    media_id: int,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> Response:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT m.file_path, m.storage_provider, m.content_type, m.original_filename
                FROM encounter_media m
                JOIN encounters e ON e.encounter_id = m.encounter_id
                WHERE m.media_id = :media_id
                  AND m.encounter_id = :encounter_id
                  AND m.media_type = 'photo'
                  AND e.user_id = :user_id
                """
            ),
            {
                "media_id": media_id,
                "encounter_id": encounter_id,
                "user_id": current_user.user_id,
            },
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    try:
        storage = get_media_storage(row.storage_provider)
        payload = storage.read(row.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Photo file not found") from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Photo file not found") from exc
        raise HTTPException(status_code=503, detail="Photo storage is temporarily unavailable") from exc
    except (httpx.HTTPError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Photo storage is temporarily unavailable") from exc

    return Response(
        content=payload,
        media_type=row.content_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=300"},
    )
