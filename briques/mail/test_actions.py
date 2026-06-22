"""Actions d'écriture sur un message en mode MOCK (boîte simulée, sans réseau) :
marquer lu / non lu, déplacer vers un dossier, supprimer (retrait de la boîte unifiée).

En mock il n'y a pas de serveur : l'effet réel est porté par le cache local. Le `mode`
renvoyé doit être « simule » (jamais « reel » : on ne ment pas sur ce qui s'est passé).

Chaque test utilise SA PROPRE clé API → son propre tenant, donc un seed mock frais et
indépendant : les mutations d'un test ne polluent jamais ni les autres tests ni le tenant
« public » utilisé par le parcours de lecture.
"""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _h(cle):
    return {"X-API-Key": cle}


def _premier_id(h):
    return client.get("/mail", headers=h).json()["messages"][0]["id"]


def test_marquer_lu_puis_non_lu():
    h = _h("t-marquer")
    # On prend un message NON lu pour voir l'état basculer.
    mid = client.get("/mail", params={"non_lus": True}, headers=h).json()["messages"][0]["id"]

    r = client.post(f"/mail/{mid}/lu", headers=h)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True and j["lu"] is True and j["mode"] == "simule"
    assert client.get(f"/mail/{mid}", headers=h).json()["lu"] is True

    # Re-marquer non lu remet le drapeau à zéro.
    r = client.post(f"/mail/{mid}/lu", json={"lu": False}, headers=h)
    assert r.status_code == 200 and r.json()["lu"] is False
    assert client.get(f"/mail/{mid}", headers=h).json()["lu"] is False


def test_supprimer_retire_de_la_boite():
    h = _h("t-supprimer")
    mid = _premier_id(h)
    avant = client.get("/mail", headers=h).json()["total"]

    r = client.delete(f"/mail/{mid}", headers=h)
    assert r.status_code == 200
    j = r.json()
    assert j["supprime"] is True and j["mode"] == "simule"

    assert client.get(f"/mail/{mid}", headers=h).status_code == 404        # plus lisible
    apres = client.get("/mail", headers=h).json()
    assert apres["total"] == avant - 1                                     # retiré de l'unifiée
    assert all(m["id"] != mid for m in apres["messages"])


def test_deplacer_change_le_dossier():
    h = _h("t-deplacer")
    mid = _premier_id(h)
    r = client.post(f"/mail/{mid}/deplacer", json={"dossier": "Archive"}, headers=h)
    assert r.status_code == 200
    j = r.json()
    assert j["dossier"] == "Archive" and j["mode"] == "simule"
    assert client.get(f"/mail/{mid}", headers=h).json()["dossier"] == "Archive"


def test_deplacer_sans_dossier_refuse():
    h = _h("t-deplacer-vide")
    mid = _premier_id(h)
    assert client.post(f"/mail/{mid}/deplacer", json={"dossier": "   "}, headers=h).status_code == 400


def test_actions_sur_message_inexistant_404():
    h = _h("t-404")
    assert client.post("/mail/inexistant/lu", headers=h).status_code == 404
    assert client.post("/mail/inexistant/deplacer", json={"dossier": "X"}, headers=h).status_code == 404
    assert client.delete("/mail/inexistant", headers=h).status_code == 404


def test_isolation_un_tenant_ne_supprime_pas_chez_un_autre():
    # Le message d'Alice est invisible/intouchable pour Bob (cloisonnement par clé API).
    a, b = _h("cle-alice"), _h("cle-bob")
    mid = client.get("/mail", headers=a).json()["messages"][0]["id"]
    # Bob ne peut ni le lire ni le supprimer.
    assert client.delete(f"/mail/{mid}", headers=b).status_code == 404
    # Alice le voit toujours (Bob n'a rien pu faire).
    assert client.get(f"/mail/{mid}", headers=a).status_code == 200
