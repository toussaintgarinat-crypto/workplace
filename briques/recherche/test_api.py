"""Tests de l'API — TestClient, mode repli honnête (aucun moteur joignable, hors-ligne)."""
from fastapi.testclient import TestClient

import main

c = TestClient(main.app)


def test_sante_aucun_moteur_configure():
    r = c.get("/sante")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert set(d["fournisseurs"]) == {"searxng", "duckduckgo", "tavily"}
    assert d["configures"] == [] and d["actif"] is None   # conftest a tout neutralisé


def test_fournisseurs_catalogue():
    d = c.get("/fournisseurs").json()
    noms = {f["nom"] for f in d["fournisseurs"]}
    assert noms == {"searxng", "duckduckgo", "tavily"}
    assert all(f["configure"] is False for f in d["fournisseurs"])


def test_rechercher_sans_moteur_rend_note_honnete():
    r = c.post("/rechercher", json={"requete": "logiciel libre"})
    assert r.status_code == 200
    d = r.json()
    assert d["resultats"] == [] and d["backend"] is None and d["nb"] == 0
    assert "Aucun moteur" in d["note"]      # honnête : on le DIT, pas de faux liens


def test_rechercher_requete_vide_422():
    assert c.post("/rechercher", json={"requete": "   "}).status_code == 422


def test_lire_page_url_invalide_422():
    r = c.post("/lire-page", json={"url": "file:///etc/passwd"})
    assert r.status_code == 422
    assert "URL invalide" in r.json()["detail"]


def test_fournisseur_force_indisponible_rend_note():
    # On force un moteur précis non configuré → note honnête, pas d'appel réseau.
    d = c.post("/rechercher", json={"requete": "x", "fournisseur": "tavily"}).json()
    assert d["resultats"] == [] and d["backend"] is None
