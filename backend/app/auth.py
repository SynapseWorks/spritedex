import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel, EmailStr, Field
from pwdlib import PasswordHash
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .database import engine

router = APIRouter(prefix="/api/auth", tags=["auth"])
me_router = APIRouter(prefix="/api/me", tags=["me"])

password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 30
ALGORITHM = "HS256"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32)


class AuthTokens(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str


class CurrentUser(BaseModel):
    user_id: int
    email: EmailStr
    display_name: str


def _secret_key() -> str:
    value = os.getenv("SPRITEDEX_JWT_SECRET")
    if not value:
        raise RuntimeError(
            "SPRITEDEX_JWT_SECRET is required. Generate one with `openssl rand -hex 32`."
        )
    return value


def _refresh_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_access_token(user_id: int, session_id: uuid.UUID) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "type": "access",
        "iat": now,
        "exp": expires,
    }
    token = jwt.encode(payload, _secret_key(), algorithm=ALGORITHM)
    return token, ACCESS_TOKEN_EXPIRE_MINUTES * 60


def _create_session(connection: Any, user_id: int) -> AuthTokens:
    session_id = uuid.uuid4()
    refresh_token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    connection.execute(
        text(
            """
            INSERT INTO auth_sessions (
                session_id, user_id, refresh_token_hash, expires_at
            ) VALUES (
                :session_id, :user_id, :refresh_token_hash, :expires_at
            )
            """
        ),
        {
            "session_id": session_id,
            "user_id": user_id,
            "refresh_token_hash": _refresh_digest(refresh_token),
            "expires_at": expires_at,
        },
    )
    access_token, expires_in = _new_access_token(user_id, session_id)
    return AuthTokens(
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=refresh_token,
    )


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> CurrentUser:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise credentials_error
        user_id = int(payload["sub"])
        session_id = uuid.UUID(payload["sid"])
    except (InvalidTokenError, KeyError, ValueError, TypeError) as exc:
        raise credentials_error from exc

    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT u.user_id, u.email, u.display_name
                FROM app_users u
                JOIN auth_sessions s ON s.user_id = u.user_id
                WHERE u.user_id = :user_id
                  AND s.session_id = :session_id
                  AND u.is_active = TRUE
                  AND u.email IS NOT NULL
                  AND s.revoked_at IS NULL
                  AND s.expires_at > NOW()
                """
            ),
            {"user_id": user_id, "session_id": session_id},
        ).first()
    if row is None:
        raise credentials_error
    return CurrentUser(**dict(row._mapping))


@router.post("/register", response_model=AuthTokens, status_code=201)
def register(payload: RegisterRequest) -> AuthTokens:
    normalized_email = str(payload.email).strip().lower()
    hashed = password_hash.hash(payload.password)
    try:
        with engine.begin() as connection:
            user_id = connection.execute(
                text(
                    """
                    INSERT INTO app_users (display_name, email)
                    VALUES (:display_name, :email)
                    RETURNING user_id
                    """
                ),
                {"display_name": payload.display_name.strip(), "email": normalized_email},
            ).scalar_one()
            connection.execute(
                text(
                    """
                    INSERT INTO auth_password_credentials (user_id, password_hash)
                    VALUES (:user_id, :password_hash)
                    """
                ),
                {"user_id": user_id, "password_hash": hashed},
            )
            return _create_session(connection, user_id)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="An account with that email already exists") from exc


@router.post("/token", response_model=AuthTokens)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> AuthTokens:
    normalized_email = form.username.strip().lower()
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT u.user_id, u.is_active, c.password_hash
                FROM app_users u
                JOIN auth_password_credentials c ON c.user_id = u.user_id
                WHERE LOWER(u.email) = :email
                """
            ),
            {"email": normalized_email},
        ).first()

    if row is None or not row.is_active or not password_hash.verify(form.password, row.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    with engine.begin() as connection:
        return _create_session(connection, row.user_id)


@router.post("/refresh", response_model=AuthTokens)
def refresh(payload: RefreshRequest) -> AuthTokens:
    digest = _refresh_digest(payload.refresh_token)
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT session_id, user_id
                FROM auth_sessions
                WHERE refresh_token_hash = :digest
                  AND revoked_at IS NULL
                  AND expires_at > NOW()
                FOR UPDATE
                """
            ),
            {"digest": digest},
        ).first()
        if row is None:
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

        new_refresh = secrets.token_urlsafe(48)
        connection.execute(
            text(
                """
                UPDATE auth_sessions
                SET refresh_token_hash = :new_digest,
                    last_used_at = NOW(),
                    expires_at = :expires_at
                WHERE session_id = :session_id
                """
            ),
            {
                "new_digest": _refresh_digest(new_refresh),
                "expires_at": datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
                "session_id": row.session_id,
            },
        )
        access_token, expires_in = _new_access_token(row.user_id, row.session_id)
        return AuthTokens(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=new_refresh,
        )


@router.post("/logout", status_code=204)
def logout(payload: RefreshRequest) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE auth_sessions
                SET revoked_at = COALESCE(revoked_at, NOW())
                WHERE refresh_token_hash = :digest
                """
            ),
            {"digest": _refresh_digest(payload.refresh_token)},
        )


@me_router.get("")
def me(current_user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    return current_user


@me_router.get("/regions")
def my_regions(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    p.region_id,
                    r.name,
                    r.slug,
                    r.region_type,
                    p.discovered_species_count,
                    p.eligible_species_count,
                    p.completion_percent,
                    p.regional_score,
                    p.first_encounter_at,
                    p.last_encounter_at
                FROM user_region_progress p
                JOIN regions r ON r.region_id = p.region_id
                WHERE p.user_id = :user_id
                ORDER BY p.last_encounter_at DESC NULLS LAST, r.name
                """
            ),
            {"user_id": current_user.user_id},
        )
        return [dict(row._mapping) for row in rows]


@me_router.get("/regions/{region_id}/dex")
def my_region_dex(
    region_id: int,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    rs.region_id,
                    s.species_id,
                    s.common_name,
                    s.scientific_name,
                    s.category,
                    rs.public_tier,
                    rs.dex_eligible,
                    rs.seasonal_active,
                    (urs.species_id IS NOT NULL) AS discovered,
                    urs.first_observed_at,
                    urs.last_observed_at,
                    urs.encounter_count,
                    urs.regional_points
                FROM region_species rs
                JOIN species s ON s.species_id = rs.species_id
                LEFT JOIN user_region_species urs
                  ON urs.region_id = rs.region_id
                 AND urs.species_id = rs.species_id
                 AND urs.user_id = :user_id
                WHERE rs.region_id = :region_id
                  AND rs.dex_eligible = TRUE
                ORDER BY COALESCE(s.common_name, s.scientific_name), s.species_id
                """
            ),
            {"user_id": current_user.user_id, "region_id": region_id},
        )
        return [dict(row._mapping) for row in rows]
