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
