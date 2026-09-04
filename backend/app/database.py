import os

from sqlalchemy import create_engine


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


DATABASE_URL = _normalize_database_url(
    os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/spritedex",
    )
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
