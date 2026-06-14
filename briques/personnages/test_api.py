"""Tests d'API (TestClient). LLM mocké → aucun réseau. DB temporaire (conftest)."""
import llm
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["service"] == "personnages"
    assert "casting_voix" in r.json()["modules"]


# ── Stateless : casting (pur, sans LLM) ──────────────────────────
def test_casting_stable():
    body = {
        "personnages": [{"nom": "Aria"}, {"nom": "Vorn"}],
        "repliques": [{"perso": "ARIA"}, {"perso": "VORN"}, {"perso": "NARRATEUR"}],
        "langue": "fr", "pool_voix": ["v_alice", "v_bob", "v_cara"],
    }
    r = client.post("/casting", json=body)
    assert r.status_code == 200
    cast = r.json()["casting"]
    assert cast["ARIA"] == "v_alice" and cast["VORN"] == "v_bob"
    assert cast["NARRATEUR"] in ("v_cara",)        # voix libre, pas une figée


# ── Stateless : proposer (LLM mocké) ─────────────────────────────
def test_proposer_avec_voix(monkeypatch):
    async def faux_llm(premisse, langue, combien, deja, conf):
        return [{"nom": "Aria", "role": "héroïne", "description": "brave"},
                {"nom": "Vorn", "role": "antagoniste", "description": "froid"}]
    monkeypatch.setattr(llm, "proposer_distribution", faux_llm)
    r = client.post("/distribution/proposer",
                    json={"premisse": "un désert", "voix_dispo": ["v1", "v2", "v3"]})
    assert r.status_code == 200
    data = r.json()
    assert len(data["personnages"]) == 2
    assert data["casting_suggere"]["Aria"] == "v1"   # voix suggérée stable


def test_proposer_llm_ko_renvoie_502(monkeypatch):
    async def boom(*a):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(llm, "proposer_distribution", boom)
    r = client.post("/distribution/proposer", json={"premisse": "x"})
    assert r.status_code == 502


# ── Stateful : cycle de vie d'une distribution ───────────────────
def test_cycle_stateful_complet():
    # créer
    did = client.post("/distributions", json={"titre": "Ma saga", "langue": "fr"}).json()["id"]
    # ajouter deux personnages
    client.post(f"/distributions/{did}/personnages", json={"nom": "Aria", "role": "héroïne"})
    p2 = client.post(f"/distributions/{did}/personnages", json={"nom": "Vorn"}).json()
    # lire
    d = client.get(f"/distributions/{did}").json()
    assert len(d["personnages"]) == 2
    # caster avec la distribution stockée → voix persistées
    r = client.post(f"/distributions/{did}/casting", json={
        "repliques": [{"perso": "ARIA"}, {"perso": "VORN"}],
        "langue": "fr", "pool_voix": ["v_alice", "v_bob"]})
    assert r.json()["casting"]["ARIA"] == "v_alice"
    # la voix figée est bien re-persistée
    d2 = client.get(f"/distributions/{did}").json()
    aria = next(p for p in d2["personnages"] if p["nom"] == "Aria")
    assert aria["voix"]["fr"] == "v_alice"
    # supprimer un perso
    client.delete(f"/distributions/{did}/personnages/{p2['id']}")
    assert len(client.get(f"/distributions/{did}").json()["personnages"]) == 1
    # supprimer la distribution
    assert client.delete(f"/distributions/{did}").status_code == 204
    assert client.get(f"/distributions/{did}").status_code == 404


def test_404_sur_distribution_inconnue():
    assert client.get("/distributions/inexistant").status_code == 404


# ── Holistique (S49) : descendant & montant, sans LLM ────────────
def test_sante_expose_holistique():
    j = client.get("/sante").json()
    assert "holistique" in j["modules"]
    assert "maya_tzolkin" in j["traditions"]


def test_portrait_descendant():
    r = client.post("/holistique/portrait", json={
        "prenoms": "Aria", "nom": "Solis", "date_naissance": "1990-09-05",
        "heure_naissance": "14:30", "latitude": 43.6, "longitude": 1.44, "utc_offset": 2.0})
    assert r.status_code == 200
    data = r.json()
    assert data["traditions"]["signe_solaire"]["nom"] == "Vierge"
    assert data["traditions"]["maya"]["glyphe"]
    p = data["portrait"]
    assert p["archetype"] and len(p["forces"]) == 3
    assert p["pierre_equilibrage"]["compense"] == p["faiblesse"]
    # empreinte expliquée : chaque tradition vient avec son sens
    emp = data["empreinte"]
    assert emp and all(e["valeur"] and e["sens"] for e in emp)
    assert any(e["cle"] == "Égypte" for e in emp)


def test_portrait_fiche_insuffisante_422():
    assert client.post("/holistique/portrait", json={"prenoms": "X"}).status_code == 422


def test_recherche_inverse_montant():
    r = client.post("/holistique/recherche-inverse",
                    json={"description": "guerrier colérique mais spirituel", "combien": 3})
    assert r.status_code == 200
    data = r.json()
    assert data["signes"] and len(data["signes"]) <= 3
    assert data["archetype"]
    assert data["source_analyse"] == "lexique"      # reconnu localement, pas d'appel LLM


def test_recherche_inverse_filet_llm(monkeypatch):
    """Si le lexique ne reconnaît rien, on bascule sur le LLM (mocké ici)."""
    async def faux_cible(description, axes, conf=None):
        return {"Sagesse": 3, "Discrétion": 2}
    monkeypatch.setattr(llm, "cibler_via_llm", faux_cible)
    r = client.post("/holistique/recherche-inverse",
                    json={"description": "un être totalement ineffable et abscons"})
    assert r.status_code == 200
    data = r.json()
    assert data["source_analyse"] == "llm"
    assert data["signes"] and data["cible"].get("Sagesse")


def test_recherche_inverse_llm_ko_reste_honnete(monkeypatch):
    """Si le LLM échoue aussi, on retombe honnêtement sur « aucun trait » (pas d'invention)."""
    async def boom(*a, **k):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(llm, "cibler_via_llm", boom)
    r = client.post("/holistique/recherche-inverse", json={"description": "xyzzy qwerty zzz"})
    assert r.status_code == 200
    data = r.json()
    assert data["source_analyse"] == "lexique" and data["signes"] == []
