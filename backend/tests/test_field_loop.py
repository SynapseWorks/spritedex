import io
import json

import respx
from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image
from sqlalchemy import text

from app import field_routes
from app.database import engine
from app.main import app

client = TestClient(app)


def _reset_database() -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM inaturalist_oauth_states"))
        connection.execute(text("DELETE FROM inaturalist_accounts"))
        connection.execute(text("DELETE FROM auth_sessions"))
        connection.execute(text("DELETE FROM auth_password_credentials"))
        connection.execute(text("DELETE FROM encounter_media"))
        connection.execute(text("DELETE FROM user_region_progress"))
        connection.execute(text("DELETE FROM user_region_species"))
        connection.execute(text("DELETE FROM encounter_regions"))
        connection.execute(text("DELETE FROM encounters"))
        connection.execute(text("DELETE FROM region_species"))
        connection.execute(text("DELETE FROM region_relationships"))
        connection.execute(text("DELETE FROM regions"))
        connection.execute(text("DELETE FROM species_notes"))
        connection.execute(text("DELETE FROM identification_candidates"))
        connection.execute(text("DELETE FROM species"))
        connection.execute(text("DELETE FROM app_users"))


def _register() -> tuple[dict, dict[str, str]]:
    response = client.post(
        "/api/auth/register",
        json={
            "email": "field@example.com",
            "password": "correct-horse-battery-staple",
            "display_name": "Field Explorer",
        },
    )
    assert response.status_code == 201, response.text
    tokens = response.json()
    return tokens, {"Authorization": f"Bearer {tokens['access_token']}"}


def _jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), (80, 120, 160)).save(buffer, format="JPEG")
    return buffer.getvalue()


@respx.mock(assert_all_called=False)
def test_taxon_photo_discovery_and_idempotent_remote_photo_sync(tmp_path, monkeypatch) -> None:
    _reset_database()
    monkeypatch.setenv("SPRITEDEX_MEDIA_ROOT", str(tmp_path / "media"))
    _, headers = _register()
    user_id = client.get("/api/me", headers=headers).json()["user_id"]

    with engine.begin() as connection:
        region_id = connection.execute(
            text(
                """
                INSERT INTO regions (
                    name, slug, region_type, boundary,
                    status, visibility, is_playable
                ) VALUES (
                    'Field Test Region', 'field-test-region', 'custom',
                    ST_Multi(ST_GeomFromText(
                        'POLYGON((-79 43,-78 43,-78 44,-79 44,-79 43))', 4326
                    )),
                    'active', 'public', TRUE
                ) RETURNING region_id
                """
            )
        ).scalar_one()

    search_route = respx.get("https://api.inaturalist.org/v1/taxa").mock(
        return_value=Response(
            200,
            json={
                "results": [{
                    "id": 12727,
                    "name": "Turdus migratorius",
                    "preferred_common_name": "American Robin",
                    "rank": "species",
                    "iconic_taxon_name": "Aves",
                    "observations_count": 100000,
                    "default_photo": {"medium_url": "https://static.example/robin.jpg"},
                }]
            },
        )
    )
    detail_route = respx.get("https://api.inaturalist.org/v1/taxa/12727").mock(
        return_value=Response(
            200,
            json={
                "results": [{
                    "id": 12727,
                    "name": "Turdus migratorius",
                    "preferred_common_name": "American Robin",
                    "rank": "species",
                    "iconic_taxon_name": "Aves",
                    "default_photo": {"medium_url": "https://static.example/robin.jpg"},
                }]
            },
        )
    )

    search = client.get("/api/taxa/search", params={"q": "American Robin"})
    assert search.status_code == 200, search.text
    assert search.json()[0]["inat_taxon_id"] == 12727
    assert search.json()[0]["species_id"] is None
    assert search_route.called
    query = search_route.calls[0].request.url.params
    assert query["q"] == "American Robin"
    assert query["per_page"] == "10"
    assert query["is_active"] == "true"

    imported = client.post(
        "/api/taxa/import",
        headers=headers,
        json={"inat_taxon_id": 12727},
    )
    assert imported.status_code == 201, imported.text
    species_id = imported.json()["species_id"]
    assert imported.json()["rank"] == "species"
    assert detail_route.called

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO region_species (
                    region_id, species_id, dex_eligible, seasonal_active,
                    encounter_tier, public_tier, tier_confidence, encounter_score
                ) VALUES (
                    :region_id, :species_id, TRUE, TRUE,
                    'familiar', 'familiar', 'high', 10
                )
                """
            ),
            {"region_id": region_id, "species_id": species_id},
        )

    created = client.post(
        "/api/field/encounters",
        headers=headers,
        data={
            "metadata": json.dumps({
                "species_id": species_id,
                "latitude": 43.5,
                "longitude": -78.5,
                "notes": "First real field-loop robin",
            }),
            "caption": "Robin evidence",
            "sync_inaturalist": "false",
        },
        files={"photo": ("robin.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert created.status_code == 201, created.text
    first = created.json()
    encounter_id = first["encounter_id"]
    assert first["new_discovery"] is True
    assert first["region_ids"] == [region_id]
    assert first["regions"][0]["public_tier"] == "familiar"
    assert float(first["regions"][0]["points_awarded"]) == 10.0
    assert float(first["regions"][0]["completion_percent"]) == 100.0
    assert first["photo"]["content_type"] == "image/jpeg"

    photos = client.get(f"/api/encounters/{encounter_id}/photos", headers=headers)
    assert photos.status_code == 200
    assert len(photos.json()) == 1
    media_id = photos.json()[0]["media_id"]
    image_response = client.get(
        f"/api/encounters/{encounter_id}/photos/{media_id}/file",
        headers=headers,
    )
    assert image_response.status_code == 200
    assert image_response.headers["content-type"].startswith("image/jpeg")

    second = client.post(
        "/api/field/encounters",
        headers=headers,
        data={
            "metadata": json.dumps({
                "species_id": species_id,
                "latitude": 43.51,
                "longitude": -78.51,
                "notes": "Second robin should not mint discovery points",
            }),
            "sync_inaturalist": "false",
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["new_discovery"] is False
    assert float(second.json()["regions"][0]["points_awarded"]) == 0.0
    assert second.json()["regions"][0]["discovered_species_count"] == 1
    assert float(second.json()["regions"][0]["regional_score"]) == 10.0

    def fake_sync(encounter_id_arg, current_user):
        assert encounter_id_arg == encounter_id
        assert current_user.user_id == user_id
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE encounters
                    SET inat_observation_id = 987654, inat_sync_status = 'synced'
                    WHERE encounter_id = :encounter_id
                    """
                ),
                {"encounter_id": encounter_id},
            )
        return {"encounter_id": encounter_id, "inat_observation_id": 987654, "status": "synced"}

    monkeypatch.setattr(field_routes, "sync_encounter", fake_sync)
    monkeypatch.setattr(field_routes, "get_valid_inat_api_jwt", lambda _: "test-api-jwt")

    uuid_route = respx.get("https://api.inaturalist.org/v2/observations/987654").mock(
        return_value=Response(
            200,
            json={"results": [{
                "id": 987654,
                "uuid": "53411fc2-bdf0-434e-afce-4dac33970173",
            }]},
        )
    )
    photo_route = respx.post("https://api.inaturalist.org/v2/observation_photos").mock(
        return_value=Response(200, json={"id": 246210022})
    )

    synced = client.post(
        f"/api/field/encounters/{encounter_id}/sync/inaturalist",
        headers=headers,
    )
    assert synced.status_code == 200, synced.text
    assert synced.json()["photos"][0]["inat_observation_photo_id"] == 246210022
    assert uuid_route.call_count == 1
    assert uuid_route.calls[0].request.url.params["fields"] == "id,uuid"
    assert photo_route.call_count == 1

    synced_again = client.post(
        f"/api/field/encounters/{encounter_id}/sync/inaturalist",
        headers=headers,
    )
    assert synced_again.status_code == 200
    assert synced_again.json()["photos"] == []
    assert uuid_route.call_count == 1
    assert photo_route.call_count == 1

    with engine.connect() as connection:
        saved_media = connection.execute(
            text(
                """
                SELECT inat_observation_photo_id, inat_sync_status
                FROM encounter_media WHERE media_id = :media_id
                """
            ),
            {"media_id": media_id},
        ).one()
    assert saved_media.inat_observation_photo_id == 246210022
    assert saved_media.inat_sync_status == "synced"
