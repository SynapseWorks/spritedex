import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path("docs/data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Starter taxa search: common Ontario nature categories.
# This is still API-scale, not bulk dataset-scale.
queries = ["yarrow", "garlic mustard", "dandelion", "monarch", "american robin"]

taxa = []

for query in queries:
    params = {
        "q": query,
        "per_page": "5"
    }

    url = "https://api.inaturalist.org/v1/taxa?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "SpriteDex prototype taxa sync"}
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    for item in payload.get("results", []):
        taxa.append({
            "id": item.get("id"),
            "name": item.get("name"),
            "rank": item.get("rank"),
            "preferredCommonName": item.get("preferred_common_name"),
            "iconicTaxonName": item.get("iconic_taxon_name"),
            "wikipediaUrl": item.get("wikipedia_url"),
            "matchedTerm": query
        })

output = {
    "source": "iNaturalist Taxa API",
    "generatedAt": datetime.now(timezone.utc).isoformat(),
    "queries": queries,
    "count": len(taxa),
    "taxa": taxa
}

(OUTPUT_DIR / "inat-ontario-taxa.json").write_text(
    json.dumps(output, indent=2),
    encoding="utf-8"
)
