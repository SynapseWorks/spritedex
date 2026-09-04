from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import engine
from app.main import app

client = TestClient(app)


def setup_module() -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM auth_sessions"))
        connection.execute(text("DELETE FROM auth_password_credentials"))
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

    app.state.test_species_id = species_id
    app.state.test_region_id = region_id


def _register(email: str, display_name: str = "API Tester") -> dict:
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "correct-horse-battery-staple",
            "display_name": display_name,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _auth_header(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def test_health_and_public_catalogue_routes() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}

    region_id = app.state.test_region_id
    species_id = app.state.test_species_id

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
    assert species.json()["scientific_name"] == "Turdus migratorius"


def test_authentication_and_private_encounter_loop() -> None:
    region_id = app.state.test_region_id
    species_id = app.state.test_species_id

    assert client.get("/api/me").status_code == 401
    assert client.post(
        "/api/encounters",
        json={"species_id": species_id, "latitude": 43.5, "longitude": -78.5},
    ).status_code == 401

    registration = _register("explorer@example.com", "Explorer One")
    headers = _auth_header(registration["access_token"])

    me = client.get("/api/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "explorer@example.com"
    user_id = me.json()["user_id"]

    duplicate = client.post(
        "/api/auth/register",
        json={
            "email": "EXPLORER@example.com",
            "password": "another-secure-password",
            "display_name": "Duplicate",
        },
    )
    assert duplicate.status_code == 409

    wrong_login = client.post(
        "/api/auth/token",
        data={"username": "explorer@example.com", "password": "wrong-password"},
    )
    assert wrong_login.status_code == 401

    login = client.post(
        "/api/auth/token",
        data={
            "username": "explorer@example.com",
            "password": "correct-horse-battery-staple",
        },
    )
    assert login.status_code == 200

    created = client.post(
        "/api/encounters",
        headers=headers,
        json={
            "species_id": species_id,
            "latitude": 43.5,
            "longitude": -78.5,
            "notes": "Authenticated integration-test robin",
        },
    )
    assert created.status_code == 201, created.text
    encounter_id = created.json()["encounter_id"]
    assert created.json()["region_ids"] == [region_id]

    encounter = client.get(f"/api/encounters/{encounter_id}", headers=headers)
    assert encounter.status_code == 200
    assert encounter.json()["user_id"] == user_id
    assert encounter.json()["regions"][0]["region_id"] == region_id

    listed = client.get("/api/encounters", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["encounter_id"] == encounter_id

    my_regions = client.get("/api/me/regions", headers=headers)
    assert my_regions.status_code == 200
    assert my_regions.json()[0]["discovered_species_count"] == 1
    assert float(my_regions.json()[0]["completion_percent"]) == 100.0

    my_dex = client.get(f"/api/me/regions/{region_id}/dex", headers=headers)
    assert my_dex.status_code == 200
    assert my_dex.json()[0]["discovered"] is True
    assert my_dex.json()[0]["encounter_count"] == 1

    second = _register("second@example.com", "Explorer Two")
    second_headers = _auth_header(second["access_token"])
    assert client.get(f"/api/encounters/{encounter_id}", headers=second_headers).status_code == 404

    with engine.connect() as connection:
        owner = connection.execute(
            text("SELECT user_id FROM encounters WHERE encounter_id = :encounter_id"),
            {"encounter_id": encounter_id},
        ).scalar_one()
    assert owner == user_id

    refreshed = client.post(
        "/api/auth/refresh",
        json={"refresh_token": registration["refresh_token"]},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != registration["refresh_token"]
    refreshed_headers = _auth_header(refreshed.json()["access_token"])
    assert client.get("/api/me", headers=refreshed_headers).status_code == 200

    logout = client.post(
        "/api/auth/logout",
        json={"refresh_token": refreshed.json()["refresh_token"]},
    )
    assert logout.status_code == 204
    assert client.get("/api/me", headers=refreshed_headers).status_code == 401
