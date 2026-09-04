# SpriteDex Frontend

SpriteDex V1 is a mobile-first React/Vite web client backed by the real FastAPI/PostGIS service.

## V1 screens

- Home — nearby/pilot Region, personal totals, recent encounters
- Find — phone camera/photo, iNaturalist taxon search, GPS capture, field notes, New Discovery result
- Regional Dex — active Regional Dex, discovered state, encounter tier, species detail
- Map — privacy-first in-browser plot of the signed-in user's own encounter coordinates
- Profile — personal totals, Region progress, iNaturalist connection status

## Stack

- React
- Vite
- native browser Geolocation API
- native phone file/camera capture
- same-origin FastAPI API access

The V1 map deliberately does not send private encounter coordinates to a third-party map provider. A richer basemap can be added later behind explicit privacy/product decisions.

## Local development

Start PostgreSQL/PostGIS and FastAPI using the repository development instructions, then:

```bash
cd frontend
npm install
npm run dev
```

Vite listens on `0.0.0.0:5173` and proxies `/api` and `/health` to FastAPI at `127.0.0.1:8000`.

To test from a phone on the same network, expose the development site through an HTTPS-capable local tunnel or use the deployed V1 environment. Mobile browsers generally require a secure context for reliable camera/geolocation access.

## Production build

```bash
npm run build
```

The static production bundle is written to `frontend/dist/` and is intended to be served from the same public origin as the API through the V1 deployment layer.

## Design direction

The existing prototype's dark ecological field-terminal language is preserved and refined for touch use: calm, immersive, exploratory, scientific, solarpunk, and field-ready.

## Post-V1

- richer cartographic basemap
- offline/PWA caching
- audio identification
- AR/wearables
- social/community features
