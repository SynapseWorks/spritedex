import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path("docs/data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

params = {
    "place_id": "6883",
    "quality_grade": "research",
    "per_page": "20",
    "order_by": "observed_on",
    "order": "desc",
    "photos": "true"
}

url = "https://api.inaturalist.org/v1/observations?" + urllib.parse.urlencode(params)

request = urllib.request.Request(
    url,
    headers={
        "User-Agent": "SpriteDex prototype data sync"
    }
)

with urllib.request.urlopen(request, timeout=30) as response:
    payload = json.loads(response.read().decode("utf-8"))

observations = []

for item in payload.get("results", []):
    taxon = item.get("taxon") or {}

    photos = item.get("photos") or []
    photo_url = None

    if photos:
        photo_url = photos[0].get("url")
        if photo_url:
            photo_url = photo_url.replace("square", "medium")

    coordinates = item.get("geojson", {}).get("coordinates") if item.get("geojson") else [None, None]
    longitude = coordinates[0] if coordinates and len(coordinates) > 0 else None
    latitude = coordinates[1] if coordinates and len(coordinates) > 1 else None

    observations.append({
        "id": item.get("id"),
        "observedOn": item.get("observed_on"),
        "createdAt": item.get("created_at"),
        "uri": item.get("uri"),
        "placeGuess": item.get("place_guess"),
        "latitude": latitude,
        "longitude": longitude,
        "photoUrl": photo_url,
        "taxon": {
            "id": taxon.get("id"),
            "name": taxon.get("name"),
            "preferredCommonName": taxon.get("preferred_common_name"),
            "rank": taxon.get("rank"),
            "iconicTaxonName": taxon.get("iconic_taxon_name")
        }
    })

output = {
    "source": "iNaturalist API",
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "query": params,
    "count": len(observations),
    "observations": observations
}

(OUTPUT_DIR / "inat-ontario-observations.json").write_text(
    json.dumps(output, indent=2),
    encoding="utf-8"
)

sync_status = {
    "lastSync": datetime.now(timezone.utc).isoformat(),
    "status": "success",
    "source": "iNaturalist API starter fetch"
}

(OUTPUT_DIR / "sync-status.json").write_text(
    json.dumps(sync_status, indent=2),
    encoding="utf-8"
)
