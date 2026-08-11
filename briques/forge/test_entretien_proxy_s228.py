"""S228 (revue finale, Finding C1a) — routes de proxy de l'entretien guidé.

Les capacités `forge_entretien_demarrer` / `forge_entretien_repondre` du manifeste
sont routées par le dispatch DYNAMIQUE du Cœur, qui tape sur CET adaptateur (port
5700), pas sur le core. Sans ces deux routes, les deux capacités étaient MORTES
(404 systématique) — exactement le motif que `tests/test_contrat_capacites.py`
surveille depuis S210 (`connexion_envoyer`).

Aucun réseau : `_appel_protege` est remplacé et capture (méthode, chemin, corps).
On vérifie surtout que le chemin transmis au core porte bien le préfixe `/api`
(les appelants le passent eux-mêmes dans cette brique) et que les erreurs du core
passent par `_json_ou_erreur` plutôt que de remonter brutes.
"""
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
    """Remplace `_appel_protege` et journalise ce que la route lui demande."""
    vus = []

    def _installer(reponse):
        async def _faux(client, methode, chemin, **kw):
            vus.append({"methode": methode, "chemin": chemin, "kw": kw})
            return reponse

        monkeypatch.setattr(main, "_appel_protege", _faux)
        return vus

    return _installer


def test_demarrer_proxifie_vers_le_core_avec_le_prefixe_api(client, appels):
    vus = appels(_Reponse(200, {
        "id": "e1", "ventureId": VID, "sectionCourante": "qualitatif.organisation",
        "statut": "en_cours", "question": "Comment votre entreprise est-elle organisée ?",
    }))
    r = client.post(f"/ventures/{VID}/entretien/demarrer")
    assert r.status_code == 200
    assert r.json()["ventureId"] == VID
    assert vus == [{"methode": "POST",
                    "chemin": f"/api/ventures/{VID}/entretien/demarrer",
                    "kw": {}}]


def test_repondre_transmet_le_message_tel_quel(client, appels):
    vus = appels(_Reponse(200, {
        "sectionCourante": "qualitatif.organisation", "sectionsCouvertes": [],
        "question": "Combien de salariés ?", "statut": "en_cours",
        "extractionEchouee": False, "syncErreur": None,
    }))
    r = client.post(f"/ventures/{VID}/entretien/repondre", json={"message": "SARL, 5 salariés"})
    assert r.status_code == 200
    assert r.json()["question"] == "Combien de salariés ?"
    assert vus[0]["methode"] == "POST"
    assert vus[0]["chemin"] == f"/api/ventures/{VID}/entretien/repondre"
    # Corps transmis tel quel : le core déclare déjà les mêmes noms de champs que le
    # manifeste (`message`) — aucun reshaping français ici, contrairement à /facturation.
    assert vus[0]["kw"]["json"] == {"message": "SARL, 5 salariés"}


def test_demarrer_mappe_une_erreur_du_core_en_502_lisible(client, appels):
    """Sans `_json_ou_erreur`, un 404 du core (venture d'autrui / inexistante)
    remonterait tel quel au Cœur avec un corps opaque."""
    appels(_Reponse(404, {}, texte="Not found"))
    r = client.post(f"/ventures/{VID}/entretien/demarrer")
    assert r.status_code == 502
    assert "404" in r.json()["detail"]


def test_repondre_mappe_une_erreur_du_core_en_502_lisible(client, appels):
    appels(_Reponse(500, {}, texte="boom"))
    r = client.post(f"/ventures/{VID}/entretien/repondre", json={"message": "x"})
    assert r.status_code == 502
    assert "500" in r.json()["detail"]


def test_les_deux_routes_existent_avec_la_forme_du_manifeste():
    """Garde-fou local (doublon assumé du filet repo-wide `test_contrat_capacites`) :
    le manifeste déclare `/ventures/{id}/entretien/...`, la route porte `{vid}` — seule
    la FORME du chemin doit correspondre, pas le nom du paramètre."""
    import re

    chemins = {
        (re.sub(r"\{[^}]*\}", "{}", r.path), tuple(sorted(r.methods)))
        for r in main.app.routes if hasattr(r, "path") and hasattr(r, "methods")
    }
    assert ("/ventures/{}/entretien/demarrer", ("POST",)) in chemins
    assert ("/ventures/{}/entretien/repondre", ("POST",)) in chemins
