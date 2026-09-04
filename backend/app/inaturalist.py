import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .auth import CurrentUser, get_current_user
from .database import engine

router = APIRouter(prefix="/api/inaturalist", tags=["inaturalist"])
encounter_sync_router = APIRouter(prefix="/api/encounters", tags=["inaturalist"])

INAT_WEB_BASE = "https://www.inaturalist.org"
INAT_API_BASE = "https://api.inaturalist.org/v2"
OAUTH_STATE_MINUTES = 10
API_JWT_CACHE_HOURS = 23


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise HTTPException(status_code=503, detail=f"Server configuration missing {name}")
    return value


def _fernet() -> Fernet:
    try:
        return Fernet(_required_env("SPRITEDEX_TOKEN_ENCRYPTION_KEY").encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="Invalid token encryption configuration") from exc


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise HTTPException(status_code=503, detail="Stored integration credential cannot be decrypted") from exc


def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _response_first(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            return results[0]
        observation = payload.get("observation")
        if isinstance(observation, dict):
            return observation
        return payload
    raise HTTPException(status_code=502, detail="Unexpected iNaturalist response")


def _http_error(exc: httpx.HTTPError, action: str) -> HTTPException:
    detail = f"iNaturalist {action} failed"
    if isinstance(exc, httpx.HTTPStatusError):
        detail += f" ({exc.response.status_code})"
    return HTTPException(status_code=502, detail=detail)


def _fetch_api_jwt_from_oauth(oauth_access_token: str) -> str:
    try:
        response = httpx.get(
            f"{INAT_WEB_BASE}/users/api_token",
            headers={"Authorization": f"Bearer {oauth_access_token}", "Accept": "application/json"},
            timeout=20,
        )
        response.raise_for_status()
        token = response.json().get("api_token")
    except (httpx.HTTPError, ValueError) as exc:
        if isinstance(exc, httpx.HTTPError):
            raise _http_error(exc, "API-token exchange") from exc
        raise HTTPException(status_code=502, detail="Invalid iNaturalist API-token response") from exc
    if not token:
        raise HTTPException(status_code=502, detail="iNaturalist API-token response contained no token")
    return token


def _fetch_current_inat_user(api_jwt: str) -> dict[str, Any]:
    try:
        response = httpx.get(
            f"{INAT_API_BASE}/users/me",
            params={"fields": "id,login"},
            headers={"Authorization": f"Bearer {api_jwt}"},
            timeout=20,
        )
        response.raise_for_status()
        return _response_first(response.json())
    except httpx.HTTPError as exc:
        raise _http_error(exc, "profile lookup") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Invalid iNaturalist profile response") from exc


def get_valid_inat_api_jwt(user_id: int) -> str:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT oauth_access_token_encrypted, api_jwt_encrypted, api_jwt_expires_at
                FROM inaturalist_accounts
                WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id},
        ).first()
    if row is None:
        raise HTTPException(status_code=409, detail="Connect an iNaturalist account first")

    now = datetime.now(timezone.utc)
    if (
        row.api_jwt_encrypted
        and row.api_jwt_expires_at
        and row.api_jwt_expires_at > now + timedelta(minutes=5)
    ):
        return _decrypt(row.api_jwt_encrypted)

    oauth_token = _decrypt(row.oauth_access_token_encrypted)
    api_jwt = _fetch_api_jwt_from_oauth(oauth_token)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE inaturalist_accounts
                SET api_jwt_encrypted = :jwt,
                    api_jwt_expires_at = :expires,
                    last_verified_at = NOW()
                WHERE user_id = :user_id
                """
            ),
            {
                "jwt": _encrypt(api_jwt),
                "expires": now + timedelta(hours=API_JWT_CACHE_HOURS),
                "user_id": user_id,
            },
        )
    return api_jwt


def _fetch_observation(api_jwt: str, observation_id: int) -> dict[str, Any]:
    try:
        response = httpx.get(
            f"{INAT_API_BASE}/observations/{observation_id}",
            params={
                "fields": "id,quality_grade,taxon.id,taxon.name,taxon.preferred_common_name,taxon.iconic_taxon_name"
            },
            headers={"Authorization": f"Bearer {api_jwt}"},
            timeout=20,
        )
        response.raise_for_status()
        return _response_first(response.json())
    except httpx.HTTPError as exc:
        raise _http_error(exc, "observation lookup") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Invalid iNaturalist observation response") from exc


def _upsert_local_species(connection: Any, taxon: dict[str, Any]) -> int | None:
    taxon_id = taxon.get("id")
    if not taxon_id:
        return None
    existing = connection.execute(
        text("SELECT species_id FROM species WHERE inat_taxon_id = :taxon_id"),
        {"taxon_id": taxon_id},
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    scientific_name = taxon.get("name") or f"iNaturalist taxon {taxon_id}"
    common_name = taxon.get("preferred_common_name") or scientific_name
    return connection.execute(
        text(
            """
            INSERT INTO species (
                common_name, scientific_name, category, inat_taxon_id, iconic_taxon_name
            ) VALUES (
                :common_name, :scientific_name, :category, :inat_taxon_id, :iconic_taxon_name
            )
            RETURNING species_id
            """
        ),
        {
            "common_name": common_name,
            "scientific_name": scientific_name,
            "category": taxon.get("iconic_taxon_name") or "Unknown",
            "inat_taxon_id": taxon_id,
            "iconic_taxon_name": taxon.get("iconic_taxon_name"),
        },
    ).scalar_one()


def _rebuild_previous_species_progress(connection: Any, user_id: int, species_id: int) -> None:
    connection.execute(
        text("DELETE FROM user_region_species WHERE user_id = :user_id AND species_id = :species_id"),
        {"user_id": user_id, "species_id": species_id},
    )
    connection.execute(
        text(
            """
            INSERT INTO user_region_species (
                user_id, region_id, species_id, first_encounter_id,
                first_observed_at, last_observed_at, encounter_count,
                verified_encounter_count, regional_points, last_reconciled_at
            )
            SELECT
                e.user_id,
                er.region_id,
                e.species_id,
                (ARRAY_AGG(e.encounter_id ORDER BY e.encountered_at, e.encounter_id))[1],
                MIN(e.encountered_at),
                MAX(e.encountered_at),
                COUNT(DISTINCT e.encounter_id),
                0,
                COALESCE(rs.encounter_score, 0),
                NOW()
            FROM encounters e
            JOIN encounter_regions er
              ON er.encounter_id = e.encounter_id
             AND er.membership_status = 'confirmed'
            LEFT JOIN region_species rs
              ON rs.region_id = er.region_id
             AND rs.species_id = e.species_id
            WHERE e.user_id = :user_id
              AND e.species_id = :species_id
            GROUP BY e.user_id, er.region_id, e.species_id, rs.encounter_score
            """
        ),
        {"user_id": user_id, "species_id": species_id},
    )
    connection.execute(text("SELECT refresh_user_region_progress(:user_id)"), {"user_id": user_id})


def _apply_observation_to_encounter(
    encounter_id: int,
    user_id: int,
    observation: dict[str, Any],
) -> dict[str, Any]:
    taxon = observation.get("taxon") or {}
    quality_grade = observation.get("quality_grade")
    with engine.begin() as connection:
        current = connection.execute(
            text(
                """
                SELECT species_id
                FROM encounters
                WHERE encounter_id = :encounter_id AND user_id = :user_id
                FOR UPDATE
                """
            ),
            {"encounter_id": encounter_id, "user_id": user_id},
        ).first()
        if current is None:
            raise HTTPException(status_code=404, detail="Encounter not found")

        old_species_id = current.species_id
        new_species_id = _upsert_local_species(connection, taxon) or old_species_id
        connection.execute(
            text(
                """
                UPDATE encounters
                SET species_id = :species_id,
                    inat_observation_id = COALESCE(:inat_observation_id, inat_observation_id),
                    inat_quality_grade = :quality_grade,
                    inat_sync_status = 'synced',
                    inat_sync_error = NULL,
                    inat_synced_at = COALESCE(inat_synced_at, NOW()),
                    inat_last_reconciled_at = NOW()
                WHERE encounter_id = :encounter_id AND user_id = :user_id
                """
            ),
            {
                "species_id": new_species_id,
                "inat_observation_id": observation.get("id"),
                "quality_grade": quality_grade,
                "encounter_id": encounter_id,
                "user_id": user_id,
            },
        )
        connection.execute(
            text("SELECT process_encounter_regions(:encounter_id)"),
            {"encounter_id": encounter_id},
        )
        if old_species_id and new_species_id != old_species_id:
            _rebuild_previous_species_progress(connection, user_id, old_species_id)

    return {
        "encounter_id": encounter_id,
        "inat_observation_id": observation.get("id"),
        "quality_grade": quality_grade,
        "species_id": new_species_id,
        "source_taxon_id": taxon.get("id"),
        "status": "synced",
    }


@router.get("/connect")
def connect(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, str]:
    client_id = _required_env("INAT_CLIENT_ID")
    redirect_uri = _required_env("INAT_REDIRECT_URI")
    state = secrets.token_urlsafe(32)
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM inaturalist_oauth_states WHERE expires_at <= NOW()"),
        )
        connection.execute(
            text(
                """
                INSERT INTO inaturalist_oauth_states (state_hash, user_id, expires_at)
                VALUES (:state_hash, :user_id, :expires_at)
                """
            ),
            {
                "state_hash": _state_hash(state),
                "user_id": current_user.user_id,
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=OAUTH_STATE_MINUTES),
            },
        )

    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
    )
    return {"authorization_url": f"{INAT_WEB_BASE}/oauth/authorize?{query}"}


@router.get("/callback")
def callback(
    code: str = Query(min_length=1),
    state: str = Query(min_length=16),
) -> dict[str, Any]:
    with engine.begin() as connection:
        oauth_state = connection.execute(
            text(
                """
                DELETE FROM inaturalist_oauth_states
                WHERE state_hash = :state_hash
                  AND expires_at > NOW()
                RETURNING user_id
                """
            ),
            {"state_hash": _state_hash(state)},
        ).first()
    if oauth_state is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    client_id = _required_env("INAT_CLIENT_ID")
    client_secret = _required_env("INAT_CLIENT_SECRET")
    redirect_uri = _required_env("INAT_REDIRECT_URI")
    try:
        response = httpx.post(
            f"{INAT_WEB_BASE}/oauth/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
        response.raise_for_status()
        oauth_access_token = response.json().get("access_token")
    except httpx.HTTPError as exc:
        raise _http_error(exc, "OAuth exchange") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Invalid iNaturalist OAuth response") from exc
    if not oauth_access_token:
        raise HTTPException(status_code=502, detail="iNaturalist OAuth response contained no token")

    api_jwt = _fetch_api_jwt_from_oauth(oauth_access_token)
    inat_user = _fetch_current_inat_user(api_jwt)
    inat_user_id = inat_user.get("id")
    inat_login = inat_user.get("login")
    if not inat_user_id or not inat_login:
        raise HTTPException(status_code=502, detail="iNaturalist profile response missing identity")

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO inaturalist_accounts (
                        user_id, inat_user_id, inat_login,
                        oauth_access_token_encrypted,
                        api_jwt_encrypted, api_jwt_expires_at,
                        connected_at, last_verified_at
                    ) VALUES (
                        :user_id, :inat_user_id, :inat_login,
                        :oauth_token, :api_jwt, :jwt_expires,
                        NOW(), NOW()
                    )
                    ON CONFLICT (user_id) DO UPDATE SET
                        inat_user_id = EXCLUDED.inat_user_id,
                        inat_login = EXCLUDED.inat_login,
                        oauth_access_token_encrypted = EXCLUDED.oauth_access_token_encrypted,
                        api_jwt_encrypted = EXCLUDED.api_jwt_encrypted,
                        api_jwt_expires_at = EXCLUDED.api_jwt_expires_at,
                        connected_at = NOW(),
                        last_verified_at = NOW()
                    """
                ),
                {
                    "user_id": oauth_state.user_id,
                    "inat_user_id": inat_user_id,
                    "inat_login": inat_login,
                    "oauth_token": _encrypt(oauth_access_token),
                    "api_jwt": _encrypt(api_jwt),
                    "jwt_expires": datetime.now(timezone.utc) + timedelta(hours=API_JWT_CACHE_HOURS),
                },
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="That iNaturalist account is already connected to another SpriteDex user",
        ) from exc

    return {"connected": True, "inat_user_id": inat_user_id, "inat_login": inat_login}


@router.get("/status")
def connection_status(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT inat_user_id, inat_login, connected_at, last_verified_at
                FROM inaturalist_accounts
                WHERE user_id = :user_id
                """
            ),
            {"user_id": current_user.user_id},
        ).first()
    if row is None:
        return {"connected": False}
    return {"connected": True, **dict(row._mapping)}


@router.delete("/connection", status_code=204)
def disconnect(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM inaturalist_accounts WHERE user_id = :user_id"),
            {"user_id": current_user.user_id},
        )


@encounter_sync_router.post("/{encounter_id}/sync/inaturalist")
def sync_encounter(
    encounter_id: int,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    e.encounter_id,
                    e.inat_observation_id,
                    e.encountered_at,
                    ST_Y(e.location::geometry) AS latitude,
                    ST_X(e.location::geometry) AS longitude,
                    e.notes,
                    e.location_description,
                    s.inat_taxon_id
                FROM encounters e
                JOIN species s ON s.species_id = e.species_id
                WHERE e.encounter_id = :encounter_id
                  AND e.user_id = :user_id
                """
            ),
            {"encounter_id": encounter_id, "user_id": current_user.user_id},
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Encounter not found")

    api_jwt = get_valid_inat_api_jwt(current_user.user_id)

    if row.inat_observation_id:
        observation = _fetch_observation(api_jwt, row.inat_observation_id)
        return _apply_observation_to_encounter(encounter_id, current_user.user_id, observation)

    if not row.inat_taxon_id:
        raise HTTPException(status_code=409, detail="Encounter species is not linked to an iNaturalist taxon")

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE encounters
                SET inat_sync_status = 'pending', inat_sync_error = NULL
                WHERE encounter_id = :encounter_id AND user_id = :user_id
                """
            ),
            {"encounter_id": encounter_id, "user_id": current_user.user_id},
        )

    observation_payload = {
        "observation": {
            "taxon_id": row.inat_taxon_id,
            "observed_on_string": row.encountered_at.isoformat(),
            "latitude": row.latitude,
            "longitude": row.longitude,
            "description": row.notes or row.location_description or "Submitted from SpriteDex",
        }
    }

    try:
        response = httpx.post(
            f"{INAT_API_BASE}/observations",
            json=observation_payload,
            headers={"Authorization": f"Bearer {api_jwt}"},
            timeout=30,
        )
        response.raise_for_status()
        created = _response_first(response.json())
        observation_id = created.get("id")
        if not observation_id:
            raise HTTPException(status_code=502, detail="iNaturalist create response contained no observation ID")
        observation = _fetch_observation(api_jwt, int(observation_id))
        return _apply_observation_to_encounter(encounter_id, current_user.user_id, observation)
    except (httpx.HTTPError, ValueError, HTTPException) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else "iNaturalist observation sync failed"
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE encounters
                    SET inat_sync_status = 'failed',
                        inat_sync_error = :error
                    WHERE encounter_id = :encounter_id AND user_id = :user_id
                    """
                ),
                {
                    "error": str(detail)[:1000],
                    "encounter_id": encounter_id,
                    "user_id": current_user.user_id,
                },
            )
        if isinstance(exc, HTTPException):
            raise
        raise _http_error(exc, "observation sync") from exc
