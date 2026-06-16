"""Tests API (TestClient) : santé, liste, sonde/pret, réveil, keepalive, recharge, auth.

Le parc de test (conftest) pointe des ports loopback FERMÉS → les sondes échouent vite
et hors-ligne, ce qui suffit à prouver le câblage et les verdicts honnêtes."""
import importlib

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True and data["service"] == "calcul"
    assert data["noeuds"] == 2
    assert set(data["etats"]) == {"muscle", "fixe"}


def test_lister_noeuds():
    r = client.get("/noeuds")
    assert r.status_code == 200
    noeuds = {n["id"]: n for n in r.json()["noeuds"]}
    assert noeuds["muscle"]["reveillable"] is True       # wakeping
    assert noeuds["fixe"]["reveillable"] is False         # aucun
    assert noeuds["fixe"]["endpoint"] == "http://127.0.0.1:59998"   # slash retiré


def test_pret_injoignable_mais_endormi():
    r = client.get("/noeuds/muscle/pret")
    assert r.status_code == 200
    data = r.json()
    assert data["pret"] is False and data["etat"] == "endormi"   # réveillable → endormi


def test_pret_noeud_fige_injoignable():
    r = client.get("/noeuds/fixe/pret")
    assert r.json()["etat"] == "injoignable"             # pas de réveil → injoignable


def test_pret_noeud_inconnu_404():
    assert client.get("/noeuds/fantome/pret").status_code == 404


def test_reveiller_echec_rapide():
    # methode_reveil=wakeping, timeout 0 → verdict négatif honnête sans boucler.
    r = client.post("/noeuds/muscle/reveiller")
    assert r.status_code == 200
    data = r.json()
    assert data["reveille"] is False and data["methode"] == "wakeping"
    assert data["id"] == "muscle"


def test_sonder_tous():
    r = client.post("/noeuds/sonder")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert set(data["sondes"]) == {"muscle", "fixe"}
    assert all(v is False for v in data["sondes"].values())


def test_lister_noeuds_ordre_priorite():
    # /noeuds reflète le parc ; muscle (priorité 10) avant fixe (50) à l'élection.
    noeuds = {n["id"]: n for n in client.get("/noeuds").json()["noeuds"]}
    assert noeuds["muscle"]["priorite"] == 10
    assert noeuds["muscle"]["modele_gateway"] == "ollama/llama3.3"


def test_muscle_aucun_dispo_hors_ligne():
    # Les deux nœuds pointent des ports fermés → aucun muscle, repli honnête.
    r = client.get("/muscle")
    assert r.status_code == 200
    data = r.json()
    assert data["disponible"] is False
    # Le pool reste listé, trié par priorité (muscle avant fixe).
    assert [n["id"] for n in data["noeuds"]] == ["muscle", "fixe"]


def test_recharger():
    r = client.post("/noeuds/recharger")
    assert r.status_code == 200 and r.json()["noeuds"] == 2


def test_auth_exigee_si_cle_configuree(monkeypatch):
    monkeypatch.setenv("API_KEYS", "secret-1")
    m = importlib.reload(main)
    c = TestClient(m.app)
    assert c.get("/sante").status_code == 200            # santé reste ouverte
    assert c.get("/noeuds").status_code == 401            # protégé sans clé
    assert c.get("/noeuds", headers={"X-API-Key": "secret-1"}).status_code == 200
    monkeypatch.setenv("API_KEYS", "")
    importlib.reload(main)                                # restaure pour les autres tests
