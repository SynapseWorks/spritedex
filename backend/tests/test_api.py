from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import engine
from app.main import app

client = TestClient(app)


def setup_module() -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM user_region_progress"))
        connection.execute(text("DELETE FROM user_region_species"))
        connection.execute(text("DELETE FROM encounter_regions"))
        connection.execute(text("DELETE FROM encounters"))
        connection.execute(text("DELETE FROM region_species"))
        connection.execute(text("DELETE FROM region_relationships"))
        connection.execute(text("DELETE FROM regions"))
        connection.execute(text("DELETE FROM species_notes"))
        connection.execute(text("DELETE FROM identification_candidates"))
        connection.execute(text("DELETE FROM encounter_media"))
        connection.execute(text("DELETE FROM species"))
        connection.execute(text("DELETE FROM app_users"))

        user_id = connection.execute(
            text("INSERT INTO app_users (display_name) VALUES ('API Tester') RETURNING user_id")
        ).scalar_one()
        species_id = connection.execute(
            text(
                """
                INSERT INTO species (
                    common_name,
                    scientific_name,
                    category,
                    inat_taxon_id,
                    iconic_taxon_name
                ) VALUES (
                    'American Robin',
                    'Turdus migratorius',
                    'Bird',
                    12727,
                    'Aves'
                )
                RETURNING species_id
                """
            )
        ).scalar_one()
        region_id = connection.execute(
            text(
                """
                INSERT INTO regions (
                    name,
                    slug,
                    region_type,
                    boundary,
                    status,
                    visibility,
                    is_playable
                ) VALUES (
                    'API Test Region',
                    'api-test-region',
                    'custom',
                    ST_Multi(ST_GeomFromText(
                        'POLYGON((-79 43,-78 43,-78 44,-79 44,-79 43))',
                        4326
                    )),
                    'active',
                    'public',
                    TRUE
                )
                RETURNING region_id
                """
            )
        ).scalar_one()
        connection.execute(
            text(
                """
                INSERT INTO region_species (
                    region_id,
                    species_id,
                    dex_eligible,
                    seasonal_active,
                    encounter_tier,
                    public_tier,
                    tier_confidence,
                    encounter_score
                ) VALUES (
                    :region_id,
                    :species_id,
                    TRUE,
                    TRUE,
                    'familiar',
                    'familiar',
                    'high',
                    10
                )
                """
            ),
            {"region_id": region_id, "species_id": species_id},
        )

    app.state.test_user_id = user_id
    app.state.test_species_id = species_id
    app.state.test_region_id = region_id


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_region_species_and_encounter_loop() -> None:
    region_id = app.state.test_region_id
    species_id = app.state.test_species_id
    user_id = app.state.test_user_id

    regions = client.get("/api/regions")
    assert regions.status_code == 200
    assert any(region["region_id"] == region_id for region in regions.json())

    at_point = client.get(
        "/api/regions/at",
        params={"latitude": 43.5, "longitude": -78.5},
    )
    assert at_point.status_code == 200
    assert [region["region_id"] for region in at_point.json()] == [region_id]

    dex = client.get(f"/api/regions/{region_id}/dex")
    assert dex.status_code == 200
    assert dex.json()[0]["common_name"] == "American Robin"
    assert dex.json()[0]["public_tier"] == "familiar"

    species = client.get(f"/api/species/{species_id}")
    assert species.status_code == 200
    assert species.json()["common_name"] == "American Robin"
    assert species.json()["scientific_name"] == "Turdus migratorius"
    assert species.json()["inat_taxon_id"] == 12727

    created = client.post(
        "/api/encounters",
        json={
            "species_id": species_id,
            "user_id": user_id,
            "latitude": 43.5,
            "longitude": -78.5,
            "notes": "Integration-test robin",
        },
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["region_ids"] == [region_id]

    encounter = client.get(f"/api/encounters/{payload['encounter_id']}")
    assert encounter.status_code == 200
    assert encounter.json()["common_name"] == "American Robin"
    assert encounter.json()["regions"][0]["region_id"] == region_id

    with engine.connect() as connection:
        progress = connection.execute(
            text(
                """
                SELECT discovered_species_count, eligible_species_count,
                       completion_percent, regional_score
                FROM user_region_progress
                WHERE user_id = :user_id AND region_id = :region_id
                """
            ),
            {"user_id": user_id, "region_id": region_id},
        ).first()

    assert progress is not None
    assert progress.discovered_species_count == 1
    assert progress.eligible_species_count == 1
    assert float(progress.completion_percent) == 100.0
    assert float(progress.regional_score) == 10.0
