"""S230 : proxys internes GET/PATCH /ventures/{vid} — utilisés par le mappeur best-effort
de la brique `connecteurs` (pas par le Cœur/l'assistant : absents du manifeste, comme
POST /sources côté connecteurs). Même style que test_entretien_proxy_s228.py : aucun
réseau, `_appel_protege` est remplacé et journalisé."""
import pytest
from fastapi.testclient import TestClient

import main

VID = "11111111-1111-1111-1111-111111111111"


class _Reponse:
    def __init__(self, status=200, payload=None, texte=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = texte

    def json(self):
        return self._payload


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def appels(monkeypatch):
    vus = []

    def _installer(reponse):
        async def _faux(client, methode, chemin, **kw):
            vus.append({"methode": methode, "chemin": chemin, "kw": kw})
            return reponse

        monkeypatch.setattr(main, "_appel_protege", _faux)
        return vus

    return _installer


def test_get_venture_proxifie_vers_le_core(client, appels):
    vus = appels(_Reponse(200, {"id": VID, "auditId": "audit-1",
                                "profilEntreprise": {"clients": {"nb": 0}}}))
    r = client.get(f"/ventures/{VID}")
    assert r.status_code == 200
    assert r.json()["auditId"] == "audit-1"
    assert vus == [{"methode": "GET", "chemin": f"/api/ventures/{VID}", "kw": {}}]


def test_patch_venture_transmet_le_corps_tel_quel(client, appels):
    vus = appels(_Reponse(200, {"id": VID, "profilEntreprise": {"clients": {"nb": 3}}}))
    r = client.patch(f"/ventures/{VID}", json={"profilEntreprise": {"clients": {"nb": 3}}})
    assert r.status_code == 200
    assert vus[0]["kw"]["json"] == {"profilEntreprise": {"clients": {"nb": 3}}}


def test_get_venture_mappe_une_erreur_du_core_en_502(client, appels):
    appels(_Reponse(404, {}, texte="Not found"))
    r = client.get(f"/ventures/{VID}")
    assert r.status_code == 502


def test_ces_deux_routes_ne_sont_pas_dans_le_manifeste():
    """Même principe que `POST /sources` côté connecteurs : lire/écrire une venture par
    id n'est pas une capacité assistant — seul le mappeur best-effort de `connecteurs`
    les appelle."""
    import json
    from pathlib import Path
    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    chemins = {c["chemin"] for c in manifest.get("capacites", [])}
    assert "/ventures/{vid}" not in chemins
    assert "/ventures/{id}" not in chemins
