"""Front autoporté : page servie, assets vendorés, souveraineté (pas de CDN)."""
import re

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

# Seules sorties réseau tolérées côté front : tuiles OSM/IGN et géocodage BAN.
DOMAINES_TOLERES = ("tile.openstreetmap.org", "data.geopf.fr", "api-adresse.data.gouv.fr")


def test_la_page_carte_est_servie():
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "GeoHub" in r.text


def test_la_page_est_publique_les_donnees_restent_gardees():
    # Sans clé la page s'affiche : c'est /objets qui porte l'auth, pas le HTML statique.
    assert client.get("/").status_code == 200


def test_assets_leaflet_vendores_et_servis():
    for chemin in ("/static/leaflet.js", "/static/leaflet.css",
                   "/static/leaflet.markercluster.js", "/static/MarkerCluster.css"):
        assert client.get(chemin).status_code == 200, chemin


def test_souverainete_aucun_cdn_dans_le_front():
    html = client.get("/").text
    externes = re.findall(r"https?://([a-z0-9.-]+)", html, flags=re.I)
    inconnus = {d for d in externes if d not in DOMAINES_TOLERES}
    assert not inconnus, f"Domaines externes inattendus dans front.html : {inconnus}"


def test_le_front_porte_les_commandes_de_veille():
    """S164 : bouton 🔄 (relance l'ingestion), barre de recherche unifiée (points par
    nom via /recherche + lieux via BAN) et panneau des zones (créer/voir/supprimer)."""
    html = client.get("/").text
    assert "/ingestion/executer" in html and 'id="btn-veille"' in html
    assert "/recherche?q=" in html and 'id="recherche"' in html
    assert 'id="zone-form"' in html and 'id="z-mode"' in html   # communes/CP OU lat-lon+rayon
    assert '"/zones"' in html


def test_le_front_ne_duplique_pas_les_regles_de_fraicheur():
    # La couleur vient du champ `fraicheur` calculé serveur : aucun « 30 » ou « 90 »
    # magique en JS (les libellés du panneau, eux, ont le droit d'exister).
    html = client.get("/").text
    assert "o.fraicheur" in html
