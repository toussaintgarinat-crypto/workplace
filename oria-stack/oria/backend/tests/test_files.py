"""Tests upload/listage/suppression de fichiers — vérifie la sérialisation DateTime."""
import pytest
from sqlalchemy import text
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from conftest import TestSessionLocal

ROOM_ID     = "room-test-fake-001"
BUILDING_ID = "building-test-fake-001"
WORLD_ID    = "world-test-fake-001"

FILE_CONTENT = b"Contenu de test pour upload."
FILE_TUPLE   = ("test.txt", FILE_CONTENT, "text/plain")


@pytest.fixture(autouse=True)
def clean_files():
    yield
    session = TestSessionLocal()
    try:
        session.execute(text("DELETE FROM files"))
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


class TestRoomFiles:
    def test_upload_fichier_room(self, client):
        r = client.post(
            f"/api/files/upload/{ROOM_ID}",
            files={"file": FILE_TUPLE},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["nom"] == "test.txt"
        assert data["room_id"] == ROOM_ID
        assert data["taille"] == len(FILE_CONTENT)
        assert data["type_mime"] == "text/plain"

    def test_created_at_est_format_iso(self, client):
        r = client.post(
            f"/api/files/upload/{ROOM_ID}",
            files={"file": FILE_TUPLE},
        )
        assert r.status_code == 200
        created_at = r.json()["created_at"]
        assert created_at is not None
        # ISO 8601 : "2026-04-24T12:00:00" ou similaire
        assert "T" in created_at or "-" in created_at

    def test_lister_fichiers_room(self, client):
        client.post(f"/api/files/upload/{ROOM_ID}", files={"file": FILE_TUPLE})
        client.post(f"/api/files/upload/{ROOM_ID}", files={"file": ("autre.txt", b"autre", "text/plain")})
        r = client.get(f"/api/files/room/{ROOM_ID}")
        assert r.status_code == 200
        files = r.json()
        assert len(files) == 2
        assert all("created_at" in f for f in files)

    def test_lister_fichiers_room_vide(self, client):
        r = client.get(f"/api/files/room/{ROOM_ID}")
        assert r.status_code == 200
        assert r.json() == []

    def test_supprimer_fichier(self, client):
        r = client.post(f"/api/files/upload/{ROOM_ID}", files={"file": FILE_TUPLE})
        fid = r.json()["id"]
        r = client.delete(f"/api/files/{fid}")
        assert r.status_code == 200
        assert client.get(f"/api/files/room/{ROOM_ID}").json() == []


class TestBuildingFiles:
    def test_upload_fichier_building(self, client):
        r = client.post(
            f"/api/files/upload/building/{BUILDING_ID}",
            files={"file": FILE_TUPLE},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["building_id"] == BUILDING_ID
        assert data["nom"] == "test.txt"

    def test_lister_fichiers_building(self, client):
        client.post(f"/api/files/upload/building/{BUILDING_ID}", files={"file": FILE_TUPLE})
        r = client.get(f"/api/files/building/{BUILDING_ID}")
        assert r.status_code == 200
        assert len(r.json()) == 1


class TestWorldFiles:
    def test_upload_fichier_world(self, client):
        r = client.post(
            f"/api/files/upload/world/{WORLD_ID}",
            files={"file": FILE_TUPLE},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["world_id"] == WORLD_ID

    def test_lister_fichiers_world(self, client):
        client.post(f"/api/files/upload/world/{WORLD_ID}", files={"file": FILE_TUPLE})
        r = client.get(f"/api/files/world/{WORLD_ID}")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_created_at_trié_desc(self, client):
        client.post(f"/api/files/upload/world/{WORLD_ID}", files={"file": ("a.txt", b"a", "text/plain")})
        client.post(f"/api/files/upload/world/{WORLD_ID}", files={"file": ("b.txt", b"b", "text/plain")})
        files = client.get(f"/api/files/world/{WORLD_ID}").json()
        # Le plus récent est en premier (order_by created_at desc)
        assert files[0]["nom"] == "b.txt"
