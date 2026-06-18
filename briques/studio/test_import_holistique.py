"""Tests — choisir un personnage CRÉÉ dans l'atelier holistique (5900) depuis le Studio.

Le Studio liste « mes personnages enregistrés » (fiches de la brique sœur) et les ajoute à
la distribution avec un NOM DE SCÈNE, tout en gardant le nom cosmique d'origine
(`nom_naissance`). La brique 5900 est mockée (`composition`) → aucun réseau.
"""
from fastapi.testclient import TestClient

import main as M

client = TestClient(M.app)


def _serie():
    return client.post("/series", json={"titre": "Saga"}).json()["id"]


# ── Helpers purs : dérivation depuis le portrait holistique ──────
def test_description_portrait_depuis_forces_et_faiblesse():
    d = M._description_portrait({"forces": ["courage", "ruse", "loyauté", "trop"],
                                 "faiblesse": "orgueil"})
    assert d == "Forces : courage · ruse · loyauté — à travailler : orgueil"
    assert M._description_portrait({}) == ""


def test_empreinte_texte_aplati_dicts_et_strings():
    out = M._empreinte_texte([{"cle": "Soleil", "valeur": "Vierge", "sens": "x"},
                              {"cle": "Lune"}, "texte brut", {"cle": "", "valeur": ""}])
    assert out == ["Soleil : Vierge", "Lune", "texte brut"]


# ── GET /personnages-holistiques : liste + repli honnête ─────────
def test_lister_personnages_holistiques(monkeypatch):
    async def faux(): return [{"id": "f1", "nom": "Aria", "nom_naissance": "Lyssandre",
                               "archetype": "Le Sage", "cree_le": "2026-06-17"}]
    monkeypatch.setattr(M.composition, "lister_fiches_holistiques", faux)
    r = client.get("/personnages-holistiques").json()
    assert r["disponible"] is True and r["fiches"][0]["nom"] == "Aria"


def test_lister_personnages_holistiques_repli_si_atelier_absent(monkeypatch):
    async def ko(): return None
    monkeypatch.setattr(M.composition, "lister_fiches_holistiques", ko)
    r = client.get("/personnages-holistiques").json()
    assert r["disponible"] is False and r["fiches"] == []


# ── POST .../importer-fiche : nom de scène + nom d'origine gardé ──
def test_importer_fiche_avec_nom_de_scene(monkeypatch):
    async def faux(fid):
        assert fid == "f1"
        return {"id": "f1", "nom": "Lyssandre", "nom_naissance": "Lyssandre",
                "archetype": "Le Sage", "donnees": {"portrait": {
                    "archetype": "Le Sage", "forces": ["courage", "ruse"], "faiblesse": "orgueil"},
                    "empreinte": [{"cle": "Soleil", "valeur": "Vierge"}]}}
    monkeypatch.setattr(M.composition, "lire_fiche_holistique", faux)
    sid = _serie()
    p = client.post(f"/series/{sid}/personnages/importer-fiche",
                    json={"fiche_id": "f1", "nom": "Aria"}).json()
    assert p["nom"] == "Aria"                       # nom de scène appliqué
    assert p["nom_naissance"] == "Lyssandre"        # nom cosmique d'origine gardé
    assert p["archetype"] == "Le Sage"
    assert p["empreinte"] == ["Soleil : Vierge"]
    assert "Forces : courage · ruse" in p["description"]
    assert p["source"] == "personnages"


def test_importer_fiche_sans_nom_reprend_celui_de_la_fiche(monkeypatch):
    async def faux(fid):
        return {"id": "f1", "nom": "Lyssandre", "nom_naissance": "Lyssandre", "donnees": {}}
    monkeypatch.setattr(M.composition, "lire_fiche_holistique", faux)
    sid = _serie()
    p = client.post(f"/series/{sid}/personnages/importer-fiche",
                    json={"fiche_id": "f1"}).json()
    assert p["nom"] == "Lyssandre" and p["nom_naissance"] == "Lyssandre"


def test_importer_fiche_502_si_atelier_injoignable(monkeypatch):
    async def ko(fid): return None
    monkeypatch.setattr(M.composition, "lire_fiche_holistique", ko)
    sid = _serie()
    r = client.post(f"/series/{sid}/personnages/importer-fiche", json={"fiche_id": "x"})
    assert r.status_code == 502


# ── Renommer un perso DANS la série : garde le nom d'origine ─────
def test_renommer_perso_serie_garde_nom_origine(monkeypatch):
    async def faux(fid):
        return {"id": "f1", "nom": "Lyssandre", "nom_naissance": "Lyssandre", "donnees": {}}
    monkeypatch.setattr(M.composition, "lire_fiche_holistique", faux)
    sid = _serie()
    p = client.post(f"/series/{sid}/personnages/importer-fiche", json={"fiche_id": "f1"}).json()
    maj = client.patch(f"/series/{sid}/personnages/{p['id']}", json={"nom": "Vorn"}).json()
    assert maj["nom"] == "Vorn" and maj["nom_naissance"] == "Lyssandre"


def test_renommer_perso_manuel_backfill_nom_origine():
    """Un perso ajouté à la main garde son nom comme origine, même renommé ensuite."""
    sid = _serie()
    p = client.post(f"/series/{sid}/personnages", json={"nom": "Lyssandre"}).json()
    assert p["nom_naissance"] == "Lyssandre"
    maj = client.patch(f"/series/{sid}/personnages/{p['id']}", json={"nom": "Aria"}).json()
    assert maj["nom"] == "Aria" and maj["nom_naissance"] == "Lyssandre"
