"""Tests — valeur suggérée sur les 3 chemins de création d'un chapitre (production
normale, express, matérialisation d'un nœud d'arbre). Toute la chaîne d'agents passe par
`agents._gateway_answer` — motif `test_audio_profil.py` : on mocke ce point unique plutôt
que chaque agent."""
from fastapi.testclient import TestClient

import main
import studio as S

client = TestClient(main.app)


def _mock_agents(monkeypatch, valeur='{"valeur":"courage"}'):
    async def fake_gw(url, model, systeme, tache):
        if "valeur humaine" in tache:
            return valeur
        return "Script généré."
    monkeypatch.setattr(main.agents, "_gateway_answer", fake_gw)


def test_faire_episode_suggere_une_valeur(monkeypatch):
    _mock_agents(monkeypatch)
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    r = client.post(f"/series/{sid}/episode", json={})
    assert r.status_code == 200
    assert r.json()["valeur_suggeree"] == "courage"
    assert r.json()["valeur"] == "courage"


def test_faire_episode_valeur_hors_liste_devient_none(monkeypatch):
    _mock_agents(monkeypatch, valeur='{"valeur":"inexistante"}')
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    r = client.post(f"/series/{sid}/episode", json={})
    assert r.json()["valeur_suggeree"] is None
    assert r.json()["valeur"] is None


def test_episode_express_suggere_une_valeur(monkeypatch):
    _mock_agents(monkeypatch)
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    r = client.post(f"/series/{sid}/express", json={})
    assert r.status_code == 200
    assert r.json()["episode"]["valeur_suggeree"] == "courage"


def test_jouer_noeud_suggere_une_valeur(monkeypatch):
    _mock_agents(monkeypatch)
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    serie = S._load(sid)
    serie["arbre"] = {"id": "n1", "niveau": 1, "synopsis": "S", "choix": ["A", "B"], "enfants": []}
    S._save(serie)
    client.post(f"/series/{sid}/arbre/n1/jouer", json={})
    ep = S._load(sid)["episodes"][0]
    assert ep["valeur_suggeree"] == "courage"


def test_jouer_noeud_idempotent_ne_re_suggere_pas(monkeypatch):
    """Rejouer un nœud déjà matérialisé ne doit ni relancer d'appel LLM de suggestion, ni
    écraser une valeur déjà retenue par le parent."""
    _mock_agents(monkeypatch)
    sid = client.post("/series", json={"titre": "T"}).json()["id"]
    serie = S._load(sid)
    serie["arbre"] = {"id": "n1", "niveau": 1, "synopsis": "S", "choix": ["A", "B"], "enfants": []}
    S._save(serie)
    client.post(f"/series/{sid}/arbre/n1/jouer", json={})

    serie = S._load(sid)
    serie["episodes"][0]["valeur"] = "empathie"  # le parent a changé la valeur retenue
    S._save(serie)

    client.post(f"/series/{sid}/arbre/n1/jouer", json={})  # relecture (déjà écrit)
    assert S._load(sid)["episodes"][0]["valeur"] == "empathie"


def test_get_valeurs_liste_les_16_cles():
    r = client.get("/valeurs")
    assert r.status_code == 200
    assert len(r.json()) == 16
    assert {"cle": "courage", "label": "Courage"} in r.json()
