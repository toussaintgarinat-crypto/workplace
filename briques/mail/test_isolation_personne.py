"""Isolation PAR PERSONNE quand le Cœur présente sa MAIL_KEY (S185, motif agenda S182 /
ecoute S184) : deux personnes du même foyer, même MAIL_KEY, boîtes/brouillons étanches.

Distinct de `test_isolation.py` (tenants EXTERNES, chacun avec SA propre clé API) : ici
c'est LA MÊME clé (`MAIL_KEY`) pour tout le foyer, l'isolation vient de `X-User-Id`.
"""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _mail_key(monkeypatch):
    monkeypatch.setenv("MAIL_KEY", "cle-coeur")
    yield


def _entetes(utilisateur):
    return {"X-API-Key": "cle-coeur", "X-User-Id": utilisateur}


def test_deux_personnes_meme_cle_boites_isolees():
    msg_claire = client.get("/mail", headers=_entetes("claire")).json()["messages"][0]
    # Le même id sous une autre personne (même MAIL_KEY) n'existe pas.
    assert client.get(f"/mail/{msg_claire['id']}", headers=_entetes("marina")).status_code == 404
    assert client.get(f"/mail/{msg_claire['id']}", headers=_entetes("claire")).status_code == 200


def test_brouillon_dune_personne_invisible_pour_lautre():
    msg = client.get("/mail", headers=_entetes("claire")).json()["messages"][0]
    cree = client.post("/mail/brouillon", json={"message_id": msg["id"]},
                       headers=_entetes("claire")).json()
    ids_marina = [b["id"] for b in
                  client.get("/brouillons", headers=_entetes("marina")).json()["brouillons"]]
    assert cree["brouillon"]["id"] not in ids_marina
    ids_claire = [b["id"] for b in
                  client.get("/brouillons", headers=_entetes("claire")).json()["brouillons"]]
    assert cree["brouillon"]["id"] in ids_claire


def test_sans_x_user_id_replie_sur_perso():
    a = client.get("/mail", headers={"X-API-Key": "cle-coeur"}).json()["messages"][0]
    b = client.get("/mail", headers=_entetes("perso")).json()["messages"][0]
    assert a["id"] == b["id"]


def test_tenant_externe_toujours_par_cle_hors_mail_key():
    # Une clé qui n'est PAS MAIL_KEY reste isolée par empreinte de clé (motif historique,
    # inchangé) même avec un X-User-Id fourni (ignoré : ce n'est pas le Cœur qui appelle).
    r_avec = client.get("/mail", headers={"X-API-Key": "tenant-externe", "X-User-Id": "claire"})
    r_sans = client.get("/mail", headers={"X-API-Key": "tenant-externe"})
    assert r_avec.json()["messages"][0]["id"] == r_sans.json()["messages"][0]["id"]
