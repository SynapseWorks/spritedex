from urllib.parse import parse_qs, urlparse

import respx
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import text

from app.database import engine
from app.main import app

client = TestClient(app)


def _register(email: str) -> tuple[dict, dict[str, str]]:
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "correct-horse-battery-staple",
            "display_name": "iNat Tester",
        },
    )
    assert response.status_code == 201, response.text
    tokens = response.json()
    return tokens, {"Authorization": f"Bearer {tokens['access_token']}"}


def _seed_region_and_species() -> tuple[int, int, int]:
    with engine.begin() as connection:
        first_species = connection.execute(
            text(
                """
                INSERT INTO species (
                    common_name, scientific_name, category,
                    inat_taxon_id, iconic_taxon_name
                ) VALUES (
                    'Test Chickadee', 'Poecile testus', 'Bird', 555001, 'Aves'
                ) RETURNING species_id
                """
            )
        ).scalar_one()
        second_species = connection.execute(
            text(
                """
                INSERT INTO species (
                    common_name, scientific_name, category,
                    inat_taxon_id, iconic_taxon_name
                ) VALUES (
                    'Test Sparrow', 'Passer testus', 'Bird', 555002, 'Aves'
                ) RETURNING species_id
                """
            )
        ).scalar_one()
        region_id = connection.execute(
            text(
                """
                INSERT INTO regions (
                    name, slug, region_type, boundary,
                    status, visibility, is_playable
                ) VALUES (
                    'iNat Test Region',
                    'inat-test-region',
                    'custom',
                    ST_Multi(ST_GeomFromText(
                        'POLYGON((-77 43,-76 43,-76 44,-77 44,-77 43))', 4326
                    )),
                    'active', 'public', TRUE
                ) RETURNING region_id
                """
            )
        ).scalar_one()
        for species_id, tier, score in (
            (first_species, "familiar", 10),
            (second_species, "notable", 20),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO region_species (
                        region_id, species_id, dex_eligible, seasonal_active,
                        encounter_tier, public_tier, tier_confidence, encounter_score
                    ) VALUES (
                        :region_id, :species_id, TRUE, TRUE,
                        :tier, :tier, 'high', :score
                    )
                    """
                ),
                {
                    "region_id": region_id,
                    "species_id": species_id,
                    "tier": tier,
                    "score": score,
                },
            )
    return region_id, first_species, second_species


@respx.mock
def test_inaturalist_oauth_sync_reconciliation_and_failure_recovery() -> None:
    region_id, first_species, second_species = _seed_region_and_species()
    _, headers = _register("inat-integration@example.com")

    me = client.get("/api/me", headers=headers).json()
    user_id = me["user_id"]

    # Start OAuth: the raw CSRF state goes to the browser, but only its digest is stored.
    connect = client.get("/api/inaturalist/connect", headers=headers)
    assert connect.status_code == 200
    authorization_url = connect.json()["authorization_url"]
    parsed = urlparse(authorization_url)
    state = parse_qs(parsed.query)["state"][0]
    assert parsed.netloc == "www.inaturalist.org"

    with engine.connect() as connection:
        stored_states = connection.execute(
            text("SELECT state_hash FROM inaturalist_oauth_states WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).scalars().all()
    assert state not in stored_states

    respx.post("https://www.inaturalist.org/oauth/token").mock(
        return_value=Response(200, json={"access_token": "oauth-secret-token", "scope": "write"})
    )
    respx.get("https://www.inaturalist.org/users/api_token").mock(
        return_value=Response(200, json={"api_token": "inat-api-jwt"})
    )
    respx.get(
        "https://api.inaturalist.org/v2/users/me",
        params={"fields": "id,login"},
    ).mock(
        return_value=Response(200, json={"results": [{"id": 424242, "login": "sprite_explorer"}]})
    )

    callback = client.get(
        "/api/inaturalist/callback",
        params={"code": "authorization-code", "state": state},
    )
    assert callback.status_code == 200, callback.text
    assert callback.json()["inat_user_id"] == 424242

    status = client.get("/api/inaturalist/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["connected"] is True
    assert status.json()["inat_login"] == "sprite_explorer"

    with engine.connect() as connection:
        encrypted_oauth = connection.execute(
            text(
                "SELECT oauth_access_token_encrypted FROM inaturalist_accounts WHERE user_id = :user_id"
            ),
            {"user_id": user_id},
        ).scalar_one()
    assert encrypted_oauth != "oauth-secret-token"
    assert "oauth-secret-token" not in encrypted_oauth

    encounter = client.post(
        "/api/encounters",
        headers=headers,
        json={
            "species_id": first_species,
            "latitude": 43.5,
            "longitude": -76.5,
            "notes": "Test observation from SpriteDex",
        },
    )
    assert encounter.status_code == 201
    encounter_id = encounter.json()["encounter_id"]
    assert encounter.json()["region_ids"] == [region_id]

    create_route = respx.post("https://api.inaturalist.org/v2/observations").mock(
        return_value=Response(200, json={"results": [{"id": 987654}]})
    )
    lookup_url = "https://api.inaturalist.org/v2/observations/987654"
    lookup_route = respx.get(
        lookup_url,
        params={
            "fields": "id,quality_grade,taxon.id,taxon.name,taxon.preferred_common_name,taxon.iconic_taxon_name"
        },
    ).mock(
        return_value=Response(
            200,
            json={
                "results": [
                    {
                        "id": 987654,
                        "quality_grade": "needs_id",
                        "taxon": {
                            "id": 555001,
                            "name": "Poecile testus",
                            "preferred_common_name": "Test Chickadee",
                            "iconic_taxon_name": "Aves",
                        },
                    }
                ]
            },
        )
    )

    synced = client.post(
        f"/api/encounters/{encounter_id}/sync/inaturalist",
        headers=headers,
    )
    assert synced.status_code == 200, synced.text
    assert synced.json()["inat_observation_id"] == 987654
    assert synced.json()["quality_grade"] == "needs_id"
    assert create_route.called
    assert lookup_route.called

    with engine.connect() as connection:
        saved = connection.execute(
            text(
                """
                SELECT inat_observation_id, inat_sync_status, inat_quality_grade
                FROM encounters WHERE encounter_id = :encounter_id
                """
            ),
            {"encounter_id": encounter_id},
        ).first()
    assert saved.inat_observation_id == 987654
    assert saved.inat_sync_status == "synced"
    assert saved.inat_quality_grade == "needs_id"

    # Community identification changes later. A second sync should reconcile the
    # encounter and remove the old species from the user's discovered set.
    lookup_route.mock(
        return_value=Response(
            200,
            json={
                "results": [
                    {
                        "id": 987654,
                        "quality_grade": "research",
                        "taxon": {
                            "id": 555002,
                            "name": "Passer testus",
                            "preferred_common_name": "Test Sparrow",
                            "iconic_taxon_name": "Aves",
                        },
                    }
                ]
            },
        )
    )
    reconciled = client.post(
        f"/api/encounters/{encounter_id}/sync/inaturalist",
        headers=headers,
    )
    assert reconciled.status_code == 200
    assert reconciled.json()["species_id"] == second_species
    assert reconciled.json()["quality_grade"] == "research"

    with engine.connect() as connection:
        current_species = connection.execute(
            text("SELECT species_id FROM encounters WHERE encounter_id = :encounter_id"),
            {"encounter_id": encounter_id},
        ).scalar_one()
        discoveries = connection.execute(
            text(
                """
                SELECT species_id FROM user_region_species
                WHERE user_id = :user_id AND region_id = :region_id
                ORDER BY species_id
                """
            ),
            {"user_id": user_id, "region_id": region_id},
        ).scalars().all()
    assert current_species == second_species
    assert discoveries == [second_species]

    # A remote failure must not delete the local encounter. Use a fresh encounter
    # so the endpoint attempts a create instead of reconciling an existing link.
    failed_encounter = client.post(
        "/api/encounters",
        headers=headers,
        json={
            "species_id": first_species,
            "latitude": 43.55,
            "longitude": -76.55,
        },
    ).json()["encounter_id"]
    create_route.mock(return_value=Response(503, json={"error": "temporary"}))
    failed_sync = client.post(
        f"/api/encounters/{failed_encounter}/sync/inaturalist",
        headers=headers,
    )
    assert failed_sync.status_code == 502
    with engine.connect() as connection:
        still_local = connection.execute(
            text(
                "SELECT inat_sync_status FROM encounters WHERE encounter_id = :encounter_id"
            ),
            {"encounter_id": failed_encounter},
        ).scalar_one()
    assert still_local == "failed"

    disconnected = client.delete("/api/inaturalist/connection", headers=headers)
    assert disconnected.status_code == 204
    assert client.get("/api/inaturalist/status", headers=headers).json() == {"connected": False}
