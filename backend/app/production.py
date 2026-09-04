from __future__ import annotations

import logging
import os
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("spritedex.requests")


class RequestSafetyMiddleware:
    """Small single-instance V1 request guard.

    The free V1 deployment runs one application instance, so an in-memory limiter is
    sufficient as a first abuse barrier. It deliberately does not log request bodies,
    query strings, GPS coordinates, tokens, or uploaded filenames.
    """

    def __init__(self, app, requests_per_minute: int = 180) -> None:
        self.app = app
        self.general_limit = requests_per_minute
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _client_key(self, request: Request) -> str:
        trust_proxy = os.getenv("SPRITEDEX_TRUST_PROXY_HEADERS", "false").lower() == "true"
        if trust_proxy:
            forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            if forwarded:
                return forwarded
        return request.client.host if request.client else "unknown"

    def _rate_group(self, path: str) -> tuple[str, int]:
        if path.startswith("/api/auth/"):
            return "auth", 20
        if path.startswith("/api/taxa/search"):
            return "taxa", 60
        if path.startswith("/api/inaturalist/connect") or path.startswith("/api/inaturalist/callback"):
            return "oauth", 30
        return "general", self.general_limit

    def _max_body_bytes(self, path: str) -> int:
        if path.startswith("/api/field/encounters") or "/photos" in path:
            # V1 images are validated at 20 MB; leave room for multipart framing.
            return 25 * 1024 * 1024
        return 2 * 1024 * 1024

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        now = time.monotonic()
        group, limit = self._rate_group(request.url.path)
        key = f"{self._client_key(request)}:{group}"

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self._max_body_bytes(request.url.path):
                    response = JSONResponse(
                        {"detail": "Request body is too large."},
                        status_code=413,
                        headers={"X-Request-ID": request_id},
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                pass

        with self._lock:
            bucket = self._requests[key]
            cutoff = now - 60
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                response = JSONResponse(
                    {"detail": "Too many requests. Try again shortly."},
                    status_code=429,
                    headers={"Retry-After": "60", "X-Request-ID": request_id},
                )
                await response(scope, receive, send)
                return
            bucket.append(now)

        started = time.monotonic()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
                headers.append((b"permissions-policy", b"geolocation=(self), camera=(self)"))
                headers.append((b"cross-origin-opener-policy", b"same-origin"))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                "request id=%s method=%s path=%s status=%s duration_ms=%s",
                request_id,
                request.method,
                request.url.path,
                status_code,
                duration_ms,
            )


def configure_production(app: FastAPI) -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    app.add_middleware(
        RequestSafetyMiddleware,
        requests_per_minute=int(os.getenv("SPRITEDEX_REQUESTS_PER_MINUTE", "180")),
    )

    repo_root = Path(__file__).resolve().parents[2]
    frontend_dist = Path(os.getenv("SPRITEDEX_FRONTEND_DIST", repo_root / "frontend" / "dist"))
    if frontend_dist.is_dir():
        # Routers are registered before this mount in main.py, so /api and /health
        # retain priority while all other paths become the mobile web application.
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
