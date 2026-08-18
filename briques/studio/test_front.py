"""Tests — front Studio servi PAR la brique (S53).

Le Hub Créations d'Oria embarque ce front en iframe (comme Personnages/Images). On vérifie
ici que la brique sert bien sa propre page (sans Oria, sans DB, sans auth) et qu'elle parle
à SA propre API (port 6060) — pas aux routes `/atelier` d'Oria."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_racine_sert_le_front_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<title>Studio" in r.text


def test_alias_atelier_sert_le_meme_front():
    # Le Hub Oria pointe l'iframe sur /atelier (parité avec la brique Personnages).
    assert client.get("/atelier").text == client.get("/").text


def test_front_parle_a_la_brique_pas_a_oria():
    html = client.get("/").text
    # Appelle ses propres endpoints relatifs…
    assert "/series" in html and "/proposer" in html and "/episode" in html
    # …et surtout JAMAIS le préfixe /atelier d'Oria dans les appels fetch (découplage S51).
    assert "/atelier/series" not in html


def test_front_couvre_le_flux_complet():
    html = client.get("/").text
    for marqueur in ("Co-création de la bible", "Distribution", "Chapitres",
                     "Structure du livre", "Arbre des choix"):
        assert marqueur in html


def test_front_ecoute_la_synergie_personnages():
    # Import d'un personnage poussé par l'atelier Personnages (postMessage), composition.
    html = client.get("/").text
    assert "personnage:export" in html and "/personnages/importer" in html


def test_socle_manipulation_directe_servi():
    # S101 : socle partagé (menu contextuel + modale + cliquer-déposer) servi par la brique.
    r = client.get("/manipulation_directe.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    for marqueur in ("function sortable", "function attacherMenu", "window.__mdSocle"):
        assert marqueur in r.text


def test_front_charge_le_socle_partage():
    # Le front consomme le socle (plus de copie inline du menu/modale).
    html = client.get("/").text
    assert '/manipulation_directe.js' in html
    # La copie inline a bien été retirée (dédup S101).
    assert "function ouvrirMenu" not in html


def test_front_branche_le_cliquer_deposer_series():
    # S104 : le front câble le sortable pour réordonner les séries (+ persistance).
    html = client.get("/").text
    assert "brancherDndSeries" in html
    assert "/series/reordonner" in html


def test_reordonner_series_persiste_l_ordre():
    """S104 — POST /series/reordonner range les séries ; /series suit la nouvelle suite."""
    ids = [client.post("/series", json={"titre": t}).json()["id"]
           for t in ("Un", "Deux", "Trois")]
    nouvel_ordre = list(reversed(ids))
    r = client.post("/series/reordonner", json={"ids": nouvel_ordre})
    assert r.status_code == 200 and r.json()["ordonnees"] == 3
    listed = [s["id"] for s in client.get("/series").json() if s["id"] in ids]
    assert listed == nouvel_ordre


def test_front_expose_le_panneau_profils_lecteurs():
    html = client.get("/").text
    assert "Profils lecteurs" in html
    assert "creerProfil" in html and "chargerProfils" in html
    assert "/profils" in html


def test_front_expose_le_selecteur_lire_pour():
    html = client.get("/").text
    assert "Lire pour" in html
    assert "lirePour" in html
    assert "/adapte" in html and "profil_id" in html
