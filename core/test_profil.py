"""Régression : les routes /profil (S114) référençaient PROFIL_PATH/PROFIL_DEFAUT_PATH sans
les définir → NameError, /profil en 500. On verrouille : GET rend le profil (défaut si aucun
enregistré), POST l'enregistre et GET le relit."""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


def test_get_profil_ne_plante_pas():
    r = client.get("/profil")
    assert r.status_code == 200
    d = r.json()
    assert "contenu" in d and "modifie" in d


def test_post_puis_get_profil_persiste():
    contenu = "# Profil test\n\nContact : 06 50 88 72 16 · test@example.fr"
    r = client.post("/profil", json={"contenu": contenu})
    assert r.status_code == 200 and r.json()["ok"] is True
    relu = client.get("/profil").json()
    assert relu["contenu"] == contenu and relu["modifie"] is True
