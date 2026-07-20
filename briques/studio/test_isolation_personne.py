"""Isolation PAR PERSONNE quand le Cœur présente sa STUDIO_KEY (S187, motif mail S185 /
memoire S186) : deux personnes du même foyer, même STUDIO_KEY, séries étanches.

Distinct de `test_auth.py` (dialecte BYO — chaque client externe a SA propre clé) : ici
c'est LA MÊME clé (`STUDIO_KEY`) pour tout le foyer, l'isolation vient de `X-User-Id`.
"""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _studio_key(monkeypatch):
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    yield


def _entetes(utilisateur):
    return {"X-API-Key": "cle-coeur", "X-User-Id": utilisateur}


def _creer_serie(utilisateur, titre="Ma série"):
    r = client.post("/series", json={"titre": titre}, headers=_entetes(utilisateur))
    assert r.status_code == 200
    return r.json()


def test_serie_de_claire_invisible_pour_marina():
    serie = _creer_serie("claire")
    assert client.get(f"/series/{serie['id']}", headers=_entetes("marina")).status_code == 404
    assert client.get(f"/series/{serie['id']}", headers=_entetes("claire")).status_code == 200


def test_serie_de_claire_absente_de_la_liste_de_marina():
    serie = _creer_serie("claire")
    ids_marina = [s["id"] for s in client.get("/series", headers=_entetes("marina")).json()]
    assert serie["id"] not in ids_marina
    ids_claire = [s["id"] for s in client.get("/series", headers=_entetes("claire")).json()]
    assert serie["id"] in ids_claire


def test_sous_routes_404_pour_un_autre_proprietaire():
    serie = _creer_serie("claire")
    sid = serie["id"]
    entetes_marina = _entetes("marina")
    assert client.get(f"/series/{sid}/personnages", headers=entetes_marina).status_code == 404
    assert client.get(f"/series/{sid}/episodes", headers=entetes_marina).status_code == 404
    assert client.post(f"/series/{sid}/cycles", json={"titre": "C"},
                       headers=entetes_marina).status_code == 404
    assert client.delete(f"/series/{sid}", headers=entetes_marina).status_code == 404
    # La série existe toujours pour sa propriétaire (pas vraiment supprimée par le 404 ci-dessus).
    assert client.get(f"/series/{sid}", headers=_entetes("claire")).status_code == 200


def test_sans_x_user_id_replie_sur_perso():
    a = _creer_serie("perso", titre="A")
    ids_sans_entete = [s["id"] for s in
                       client.get("/series", headers={"X-API-Key": "cle-coeur"}).json()]
    assert a["id"] in ids_sans_entete


def test_reordonner_ignore_silencieusement_les_series_dautrui():
    serie_claire = _creer_serie("claire")
    serie_marina = _creer_serie("marina")
    r = client.post("/series/reordonner",
                    json={"ids": [serie_marina["id"], serie_claire["id"]]},
                    headers=_entetes("claire"))
    assert r.status_code == 200
    # Seul l'ordre de la série de claire a pu être posé (celle de marina est ignorée).
    s = client.get(f"/series/{serie_claire['id']}", headers=_entetes("claire")).json()
    assert s.get("ordre") == 0
    s_marina = client.get(f"/series/{serie_marina['id']}", headers=_entetes("marina")).json()
    assert s_marina.get("ordre") is None


def test_serie_legacy_cree_par_public_visible_sous_perso():
    # Simule une série créée AVANT ce sprint (mode ouvert historique, cree_par="public").
    import studio as S
    serie = {
        "id": "legacy1", "titre": "Ancienne série", "world_id": None, "cible": None,
        "langue": "fr", "bible": {}, "personnages": [], "episodes": [],
        "cree_par": "public", "cree_le": "2026-01-01T00:00:00+00:00",
    }
    S._normaliser(serie)
    S._save(serie)
    r = client.get("/series/legacy1", headers=_entetes("perso"))
    assert r.status_code == 200
    assert client.get("/series/legacy1", headers=_entetes("claire")).status_code == 404


def test_dialecte_byo_toujours_isole_par_cle_hors_studio_key(monkeypatch):
    monkeypatch.setattr(main, "API_KEYS", {"clef-client-a", "clef-client-b"})
    r = client.post("/series", json={"titre": "Client A"},
                    headers={"X-API-Key": "clef-client-a"})
    sid = r.json()["id"]
    assert client.get(f"/series/{sid}",
                      headers={"X-API-Key": "clef-client-b"}).status_code == 404
    assert client.get(f"/series/{sid}",
                      headers={"X-API-Key": "clef-client-a"}).status_code == 200
