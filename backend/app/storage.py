import hashlib
import io
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
SUPPORTED_FORMATS = {"JPEG", "PNG", "HEIF"}


@dataclass(frozen=True)
class StoredImage:
    storage_provider: str
    storage_key: str
    content_type: str
    size_bytes: int
    sha256: str
    original_filename: str | None


class LocalMediaStorage:
    provider = "local"

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or os.getenv("SPRITEDEX_MEDIA_ROOT", "var/media")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        if self.root not in candidate.parents:
            raise ValueError("Invalid media storage key")
        return candidate

    def save(
        self,
        *,
        data: bytes,
        user_id: int,
        encounter_id: int,
        extension: str,
        content_type: str,
        original_filename: str | None,
    ) -> StoredImage:
        digest = hashlib.sha256(data).hexdigest()
        key = f"users/{user_id}/encounters/{encounter_id}/{uuid.uuid4().hex}.{extension}"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_bytes(data)
        temp.replace(path)
        return StoredImage(
            storage_provider=self.provider,
            storage_key=key,
            content_type=content_type,
            size_bytes=len(data),
            sha256=digest,
            original_filename=original_filename,
        )

    def read(self, storage_key: str) -> bytes:
        return self._path(storage_key).read_bytes()

    def path_for(self, storage_key: str) -> Path:
        return self._path(storage_key)

    def delete(self, storage_key: str) -> None:
        try:
            self._path(storage_key).unlink(missing_ok=True)
        except OSError:
            pass


class SupabaseMediaStorage:
    """Private server-side Supabase Storage adapter.

    SpriteDex performs authorization in FastAPI and uses a server-only service-role
    credential for object operations. The credential must never be exposed to the
    React client. The bucket remains private.
    """

    provider = "supabase"

    def __init__(self) -> None:
        self.base_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        self.service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        self.bucket = os.getenv("SPRITEDEX_MEDIA_BUCKET", "encounter-media").strip()
        if not self.base_url or not self.service_key or not self.bucket:
            raise RuntimeError(
                "Supabase media storage requires SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, "
                "and SPRITEDEX_MEDIA_BUCKET"
            )

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        # The service-role credential is server-only. Authorization bypasses Storage
        # RLS for this trusted backend; apikey is included for gateway compatibility.
        headers = {
            "Authorization": f"Bearer {self.service_key}",
            "apikey": self.service_key,
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _encoded(self, storage_key: str) -> str:
        return quote(storage_key, safe="/")

    def save(
        self,
        *,
        data: bytes,
        user_id: int,
        encounter_id: int,
        extension: str,
        content_type: str,
        original_filename: str | None,
    ) -> StoredImage:
        digest = hashlib.sha256(data).hexdigest()
        key = f"users/{user_id}/encounters/{encounter_id}/{uuid.uuid4().hex}.{extension}"
        url = f"{self.base_url}/storage/v1/object/{quote(self.bucket, safe='')}/{self._encoded(key)}"
        response = httpx.post(
            url,
            content=data,
            headers={**self._headers(content_type), "x-upsert": "false"},
            timeout=45,
        )
        response.raise_for_status()
        return StoredImage(
            storage_provider=self.provider,
            storage_key=key,
            content_type=content_type,
            size_bytes=len(data),
            sha256=digest,
            original_filename=original_filename,
        )

    def read(self, storage_key: str) -> bytes:
        url = (
            f"{self.base_url}/storage/v1/object/authenticated/"
            f"{quote(self.bucket, safe='')}/{self._encoded(storage_key)}"
        )
        response = httpx.get(url, headers=self._headers(), timeout=45)
        response.raise_for_status()
        return response.content

    def delete(self, storage_key: str) -> None:
        url = f"{self.base_url}/storage/v1/object/{quote(self.bucket, safe='')}"
        try:
            response = httpx.request(
                "DELETE",
                url,
                json={"prefixes": [storage_key]},
                headers=self._headers("application/json"),
                timeout=30,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            # Cleanup is best-effort when a DB insert fails after the object upload.
            pass


def normalize_image(data: bytes) -> tuple[bytes, str, str]:
    if not data:
        raise ValueError("Photo is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Photo exceeds the 20 MB V1 limit")

    try:
        with Image.open(io.BytesIO(data)) as probe:
            image_format = (probe.format or "").upper()
            width, height = probe.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError("Photo dimensions are too large")
            probe.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Uploaded file is not a supported image") from exc

    if image_format not in SUPPORTED_FORMATS:
        raise ValueError("V1 supports JPEG, PNG, HEIC and HEIF photos")

    if image_format == "HEIF":
        try:
            with Image.open(io.BytesIO(data)) as image:
                image = ImageOps.exif_transpose(image)
                if image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=92, optimize=True)
                normalized = output.getvalue()
        except OSError as exc:
            raise ValueError("Could not decode HEIC/HEIF photo") from exc
        return normalized, "jpg", "image/jpeg"

    if image_format == "PNG":
        return data, "png", "image/png"
    return data, "jpg", "image/jpeg"


def get_media_storage(provider: str | None = None):
    resolved = (provider or os.getenv("SPRITEDEX_MEDIA_PROVIDER", "local")).strip().lower()
    if resolved == "local":
        return LocalMediaStorage()
    if resolved == "supabase":
        return SupabaseMediaStorage()
    raise RuntimeError(f"Unsupported SPRITEDEX_MEDIA_PROVIDER: {resolved}")
