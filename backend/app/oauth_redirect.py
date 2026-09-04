import os
from urllib.parse import urlencode

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response


class InaturalistCallbackRedirectMiddleware(BaseHTTPMiddleware):
    """Optionally return a successful OAuth callback to the SpriteDex web client.

    API/tests keep the existing JSON response when SPRITEDEX_APP_URL is unset.
    Production can set SPRITEDEX_APP_URL to the public same-origin app URL.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        app_url = os.getenv("SPRITEDEX_APP_URL", "").strip().rstrip("/")
        if (
            app_url
            and request.url.path == "/api/inaturalist/callback"
            and 200 <= response.status_code < 300
        ):
            query = urlencode({"inat": "connected"})
            return RedirectResponse(f"{app_url}/?{query}", status_code=303)
        return response
