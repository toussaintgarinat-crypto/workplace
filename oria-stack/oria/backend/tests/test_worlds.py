"""Tests CRUD des worlds Oria."""
import pytest
from sqlalchemy import text
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from conftest import TestSessionLocal, TEST_USER


@pytest.fixture(autouse=True)
def clean_worlds():
    yield
    session = TestSessionLocal()
    try:
        session.execute(text("DELETE FROM members"))
        session.execute(text("DELETE FROM worlds"))
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


WORLD_PAYLOAD = {
    "nom": "Mon Monde Test",
    "description": "Un monde pour les tests",
    "emoji": "🌍",
    "couleur": "#5865F2",
}


def create_world(client, payload=None):
    r = client.post("/api/worlds/", json=payload or WORLD_PAYLOAD)
    assert r.status_code == 200, r.text
    return r.json()


class TestWorldCRUD:
    def test_créer_world_retourne_id_et_nom(self, client):
        data = create_world(client)
        assert "id" in data
        assert data["nom"] == "Mon Monde Test"
        assert data["emoji"] == "🌍"

    def test_lister_worlds_retourne_le_world_créé(self, client):
        create_world(client)
        r = client.get("/api/worlds/")
        assert r.status_code == 200
        worlds = r.json()
        assert len(worlds) == 1
        assert worlds[0]["nom"] == "Mon Monde Test"

    def test_lister_worlds_vide_initialement(self, client):
        r = client.get("/api/worlds/")
        assert r.status_code == 200
        assert r.json() == []

    def test_obtenir_world_existant(self, client):
        w = create_world(client)
        r = client.get(f"/api/worlds/{w['id']}")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == w["id"]
        assert data["nom"] == "Mon Monde Test"
        assert "buildings" in data
        assert "membres" in data

    def test_obtenir_world_inexistant_retourne_erreur(self, client):
        r = client.get("/api/worlds/monde-qui-nexiste-pas")
        assert r.status_code == 404

    def test_modifier_world_nom(self, client):
        w = create_world(client)
        r = client.patch(f"/api/worlds/{w['id']}", json={"nom": "Monde Renommé"})
        assert r.status_code == 200
        assert r.json()["nom"] == "Monde Renommé"

    def test_modifier_world_emoji_et_couleur(self, client):
        w = create_world(client)
        r = client.patch(f"/api/worlds/{w['id']}", json={"emoji": "🏰", "couleur": "#FF5733"})
        assert r.status_code == 200
        data = r.json()
        assert data["emoji"] == "🏰"
        assert data["couleur"] == "#FF5733"

    def test_supprimer_world(self, client):
        w = create_world(client)
        r = client.delete(f"/api/worlds/{w['id']}")
        assert r.status_code in (200, 204)
        after = client.get(f"/api/worlds/{w['id']}").json()
        # Après suppression, le GET retourne {"erreur": ...} (comportement router)
        assert "erreur" in after or after.get("id") is None

    def test_créer_plusieurs_worlds(self, client):
        create_world(client, {**WORLD_PAYLOAD, "nom": "World A"})
        create_world(client, {**WORLD_PAYLOAD, "nom": "World B"})
        r = client.get("/api/worlds/")
        assert len(r.json()) == 2


class TestWorldPermissions:
    def test_modifier_world_non_propriétaire_retourne_403(self, client):
        from main import app
        from routers.auth import get_current_user as gcu

        w = create_world(client)

        app.dependency_overrides[gcu] = lambda: {
            "id": "autre-user-xyz-456",
            "nom": "Autre User",
            "avatar_emoji": "👻",
        }
        r = client.patch(f"/api/worlds/{w['id']}", json={"nom": "Hack"})
        app.dependency_overrides[gcu] = lambda: TEST_USER

        assert r.status_code == 403

    def test_supprimer_world_non_propriétaire_retourne_403(self, client):
        from main import app
        from routers.auth import get_current_user as gcu

        w = create_world(client)

        app.dependency_overrides[gcu] = lambda: {
            "id": "autre-user-xyz-456",
            "nom": "Autre User",
            "avatar_emoji": "👻",
        }
        r = client.delete(f"/api/worlds/{w['id']}")
        app.dependency_overrides[gcu] = lambda: TEST_USER

        assert r.status_code == 403
