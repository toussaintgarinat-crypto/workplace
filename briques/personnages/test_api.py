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


def test_renommer_perso_garde_nom_origine():
    """Renommer un perso pour la série change le nom affiché mais fige le nom d'origine."""
    did = client.post("/distributions", json={"titre": "Saga"}).json()["id"]
    p = client.post(f"/distributions/{did}/personnages", json={"nom": "Lyssandre"}).json()
    assert p["nom"] == p["nom_naissance"] == "Lyssandre"   # origine captée à l'ajout
    maj = client.patch(f"/distributions/{did}/personnages/{p['id']}",
                       json={"nom": "Aria"}).json()         # nom de scène
    assert maj["nom"] == "Aria" and maj["nom_naissance"] == "Lyssandre"


def test_ajout_perso_depuis_fiche_avec_alias():
    """On peut ajouter un perso avec un nom de série distinct de son nom cosmique."""
    did = client.post("/distributions", json={"titre": "Saga"}).json()["id"]
    p = client.post(f"/distributions/{did}/personnages",
                    json={"nom": "Aria", "nom_naissance": "Lyssandre"}).json()
    assert p["nom"] == "Aria" and p["nom_naissance"] == "Lyssandre"


# ── Stateful : renommer une fiche enregistrée (nom de scène) ──────
def test_fiche_renommer_via_api():
    fid = client.post("/fiches", json={"nom": "Lyssandre",
                      "portrait": {"archetype": "Le Sage"}}).json()["id"]
    r = client.patch(f"/fiches/{fid}", json={"nom": "Aria"})
    assert r.status_code == 200
    body = r.json()
    assert body["nom"] == "Aria" and body["nom_naissance"] == "Lyssandre"
    # relecture : données intactes, nom d'origine conservé
    relu = client.get(f"/fiches/{fid}").json()
    assert relu["nom"] == "Aria" and relu["nom_naissance"] == "Lyssandre"
    assert relu["donnees"]["portrait"]["archetype"] == "Le Sage"


def test_fiche_renommer_404_et_vide():
    assert client.patch("/fiches/inexistant", json={"nom": "X"}).status_code == 404
    fid = client.post("/fiches", json={"nom": "Lyssandre"}).json()["id"]
    assert client.patch(f"/fiches/{fid}", json={"nom": "  "}).status_code == 422


# ── Stateful : ranger une fiche dans une catégorie libre (anti-scroll) ──
def test_fiche_categorie_a_l_enregistrement():
    fid = client.post("/fiches", json={"nom": "Maman", "categorie": "Famille"}).json()["id"]
    assert client.get(f"/fiches/{fid}").json()["categorie"] == "Famille"
    # exposée aussi dans le listage (sert au regroupement côté front)
    assert next(x for x in client.get("/fiches").json() if x["id"] == fid)["categorie"] == "Famille"


def test_fiche_ranger_via_api_et_retirer():
    fid = client.post("/fiches", json={"nom": "Bob"}).json()["id"]
    r = client.patch(f"/fiches/{fid}/categorie", json={"categorie": "Collègues"})
    assert r.status_code == 200 and r.json()["categorie"] == "Collègues"
    assert client.get(f"/fiches/{fid}").json()["categorie"] == "Collègues"
    # catégorie vide = retire le rangement
    assert client.patch(f"/fiches/{fid}/categorie", json={"categorie": ""}).json()["categorie"] == ""


def test_fiche_ranger_404():
    assert client.patch("/fiches/inexistant/categorie",
                        json={"categorie": "Famille"}).status_code == 404


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


def test_socle_manipulation_directe_servi():
    # S101 : socle partagé (menu contextuel + modale + cliquer-déposer) servi par la brique.
    r = client.get("/manipulation_directe.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    for marqueur in ("function sortable", "function attacherMenu", "demanderTexte"):
        assert marqueur in r.text


def test_front_charge_le_socle_partage():
    # Le front holistique (/atelier) consomme le socle (plus de copie inline du menu/modale).
    html = client.get("/atelier").text
    assert "/manipulation_directe.js" in html
    assert "function ouvrirModal" not in html   # copie inline retirée (dédup S101)


def test_front_branche_le_cliquer_deposer_categories():
    # S104 : glisser une fiche sur une catégorie (zone .cat-zone) la range via PATCH categorie.
    html = client.get("/atelier").text
    assert "brancherDndFiches" in html
    assert "cat-zone" in html and "zones:'.cat-zone'" in html
    assert "rangerFicheDirect" in html
