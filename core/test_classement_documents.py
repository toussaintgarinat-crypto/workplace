"""S212 — ce que l'assistant demande arrive intact sur `PATCH /documents/{id}/classement`.

Pourquoi ce fichier existe. Le backlog du sprint affirmait qu'« aucune capacité ne déclare
`PATCH /classement` ni `GET /dossiers` : tout le rangement est inaccessible en conversation ».
Vérification faite, c'est faux — les deux sont câblés en dur depuis S6 (`outils.py` →
`outils_domaines/documents.py`), à la manière d'avant S134/S168. Ajouter les mêmes gestes au
`manifest.json` de l'ETL aurait donné à l'assistant **deux outils jumeaux** pour la même
chose, et rouvert le défaut que S210 vient de fermer.

Ce qui manquait pour de vrai, c'est la preuve du chemin. `test_etl_cle_service.py` vérifie
que la clé est portée, jamais que le CORPS est le bon : un `confirme` qui fuit dans le
classement, ou un `tags` perdu en route, passaient tous les deux au vert. Or c'est
exactement le genre d'écart muet que S210 a trouvé sur onze capacités.

Le round-trip côté brique (classer → retrouver dans son dossier) est prouvé à part, dans
`briques/etl/test_classement.py`.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))

import outils  # noqa: E402
import outils_domaines.documents as documents  # noqa: E402


class _FauxClient:
    """Capture méthode, url ET corps JSON — c'est le corps qu'on vient mesurer ici."""

    def __init__(self):
        self.appels = []

    async def patch(self, url, **k):
        self.appels.append(("PATCH", url, k.get("json")))
        return SimpleNamespace(status_code=200, json=lambda: {"id": "d1"}, text="")

    async def get(self, url, **k):
        self.appels.append(("GET", url, None))
        return SimpleNamespace(status_code=200, json=lambda: {"projets": {}, "categories": {}},
                               text="")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _dispatch(nom, args, faux):
    registre = SimpleNamespace(briques={"etl": {"port": 5200}})
    return _run(documents.dispatch(nom, args, registre, faux))


def _base_locale(monkeypatch):
    monkeypatch.setattr(documents, "_base", lambda registre, nom: f"http://{nom}")


# ── Les deux outils existent bel et bien, et sont exposés au LLM ──────────────

def test_les_outils_de_rangement_sont_bien_offerts_a_l_assistant():
    """La prémisse du backlog, vérifiée plutôt que crue."""
    noms = {o["function"]["name"] for o in outils.OUTILS}
    assert {"classer_document", "lister_dossiers"} <= noms


def test_classer_document_est_une_action_gardee():
    """Un rangement modifie l'état : il passe par le gate de confirmation, comme une action."""
    assert "classer_document" in outils.OUTILS_ACTION


# ── Le corps envoyé à la brique ──────────────────────────────────────────────

def test_le_classement_demande_arrive_entier(monkeypatch):
    _base_locale(monkeypatch)
    faux = _FauxClient()

    _dispatch("classer_document", {
        "doc_id": "d1", "categorie": "devis", "projet": "Toiture Martin",
        "tags": ["urgent", "2026"], "entreprise_id": "liv-42",
        "resume": "Devis toiture.", "confirme": True}, faux)

    methode, url, corps = faux.appels[0]
    assert (methode, url) == ("PATCH", "http://etl/documents/d1/classement")
    assert corps == {"categorie": "devis", "projet": "Toiture Martin",
                     "tags": ["urgent", "2026"], "entreprise_id": "liv-42",
                     "resume": "Devis toiture."}


def test_confirme_ne_fuit_pas_dans_le_classement(monkeypatch):
    """`confirme` est un drapeau du gate, pas une métadonnée du document.

    S'il passait, il serait fusionné tel quel dans `metadonnees.classement` et resterait
    collé au document pour toujours — le modèle `Classement` de la brique ne le refuse pas,
    il l'ignore ; c'est donc ici que ça se joue.
    """
    _base_locale(monkeypatch)
    faux = _FauxClient()

    _dispatch("classer_document", {"doc_id": "d1", "projet": "P", "confirme": True}, faux)

    assert "confirme" not in faux.appels[0][2]
    assert "doc_id" not in faux.appels[0][2], "le doc_id est dans l'URL, pas dans le corps"


def test_sans_confirmation_aucun_appel_ne_part(monkeypatch):
    """Le gate humain : tant que l'utilisateur n'a pas dit oui, la brique ne bouge pas."""
    _base_locale(monkeypatch)
    faux = _FauxClient()

    reponse = _dispatch("classer_document", {"doc_id": "d1", "categorie": "devis"}, faux)

    assert faux.appels == []
    assert "confirmation_requise" in reponse


def test_lister_dossiers_interroge_bien_la_route_dossiers(monkeypatch):
    _base_locale(monkeypatch)
    faux = _FauxClient()

    _dispatch("lister_dossiers", {}, faux)

    assert faux.appels[0][:2] == ("GET", "http://etl/dossiers")
