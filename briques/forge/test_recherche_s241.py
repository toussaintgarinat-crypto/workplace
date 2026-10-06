"""S241 — proxy de recherche de l'adaptateur Forge (aucun réseau)."""
import pytest
from fastapi.testclient import TestClient

import main


class _Reponse:
    status_code = 200

    def json(self):
        return {"mode": "lexical", "resultats": [{"id": "d1", "source": "document"}]}


@pytest.fixture
def appels(monkeypatch):
    vus = []

    async def _faux(client, methode, chemin, **kw):
        vus.append((methode, chemin, kw.get("params"), main._JETON_UTILISATEUR.get()))
        return _Reponse()

    monkeypatch.setattr(main, "_appel_protege", _faux)
    return vus


def test_relaie_vers_la_recherche_hybride(appels):
    r = TestClient(main.app).get("/documents/chercher", params={"q": " toiture ", "limite": 500})
    assert r.status_code == 200
    assert r.json() == {"mode": "lexical", "resultats": [{"id": "d1", "source": "document"}],
                        "identite": "service"}
    assert appels == [("GET", "/api/recherche/hybride", {"q": "toiture", "limite": 50}, None)]


def test_identite_utilisateur_quand_un_jeton_est_fourni(appels):
    r = TestClient(main.app).get("/documents/chercher", params={"q": "x", "sources": "kb"},
                                 headers={"X-Forge-User-Token": "Bearer JWT-A"})
    assert r.json()["identite"] == "utilisateur"
    assert appels[0][2] == {"q": "x", "limite": 10, "sources": "kb"} and appels[0][3] == "JWT-A"


def test_requete_vide_refusee(appels):
    assert TestClient(main.app).get("/documents/chercher", params={"q": "  "}).status_code == 422
    assert appels == []
