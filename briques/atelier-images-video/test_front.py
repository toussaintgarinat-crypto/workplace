"""Tests — front de l'atelier-images-video servi PAR la brique (motif atelier-veille/
test_front.py)."""
import re

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_racine_sert_le_front_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<title>Atelier Images & Vidéo</title>" in r.text


def test_alias_atelier_sert_le_meme_front():
    assert client.get("/atelier").text == client.get("/").text


def test_workplace_css_servi():
    r = client.get("/workplace.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]


def test_front_utilise_le_prefixe_api_base_du_proxy_coeur():
    html = client.get("/").text
    assert "window.ATELIER_IV_API_BASE" in html
    assert "const API_BASE = window.ATELIER_IV_API_BASE || '';" in html


def test_front_couvre_la_generation_libre():
    html = client.get("/").text
    for marqueur in ("genererImage", "genererVideo", "/images/generer", "/video/generer",
                     "chargerFournisseurs"):
        assert marqueur in html


def test_front_couvre_les_synergies_studio():
    html = client.get("/").text
    for marqueur in ("chargerSeries", "genererPortrait", "genererAnimation",
                     "genererCouverture", "genererTeaser", "/studio/series"):
        assert marqueur in html


def test_front_couvre_la_galerie():
    html = client.get("/").text
    for marqueur in ("chargerGalerie", "ajouterGalerie", "supprimerGalerie", "/galerie"):
        assert marqueur in html


def test_front_couvre_les_presets_localstorage():
    html = client.get("/").text
    for marqueur in ("sauverPreset", "chargerPreset", "localStorage", "atelier_iv_presets_"):
        assert marqueur in html


def test_front_prefixe_les_urls_de_media_avec_api_base():
    """`/fichiers/images/...` est relatif à CETTE brique. Sous le proxy Cœur (page servie
    sous API_BASE), un chemin absolu utilisé tel quel comme src retombe à la racine du
    domaine au lieu de rester sous le proxy → image cassée (motif déjà rencontré pour les
    appels API, cf. api()). afficherResultatMedia() et le rendu de la galerie doivent tous
    deux passer l'URL du média par mediaUrl() avant de l'injecter en src."""
    html = client.get("/").text
    assert "function mediaUrl(" in html

    m = re.search(r"const media = medium === 'image' \? `<img[^`]*`[^;]*;", html)
    assert m, "construction de <img>/<video> dans afficherResultatMedia() introuvable"
    assert "mediaUrl(url)" in m.group(0)

    m = re.search(r"const media = meta\.url \? \(s\.room === 'video'.*?\) : '';", html, re.DOTALL)
    assert m, "construction de <img>/<video> dans chargerGalerie() introuvable"
    assert "mediaUrl(meta.url)" in m.group(0)


def test_front_echappe_l_onclick_ajoutergalerie_contre_injection_html():
    """JSON.stringify() n'échappe pas les apostrophes : injecté brut dans un attribut
    onclick='...' délimité par apostrophes, un titre/prompt contenant une apostrophe
    (ex. « L'Estafette ») romprait l'attribut HTML (injection d'attribut). Le helper
    jsonAttr() doit être utilisé à la place pour les 5 arguments stringifiés de
    ajouterGalerie(), à l'intérieur de afficherResultatMedia()."""
    html = client.get("/").text
    assert "function jsonAttr(" in html

    # Non-greedy jusqu'à la première séquence ")'>" : l'attribut contient des parenthèses
    # imbriquées (jsonAttr(medium), jsonAttr(titre)...) qui ne sont jamais suivies de "'>"
    # avant la fin réelle de l'attribut onclick.
    m = re.search(r"onclick='ajouterGalerie\(.*?\)'>", html)
    assert m, "attribut onclick='ajouterGalerie(...)' introuvable dans le front"
    ligne_onclick = m.group(0)

    assert "JSON.stringify" not in ligne_onclick
    assert ligne_onclick.count("jsonAttr(") == 5


def test_front_echappe_les_autres_onclicks_synergies_contre_injection_html():
    """Les onclick handlers de synergies (genererPortrait, genererAnimation,
    genererCouverture, genererTeaser, supprimerGalerie) doivent aussi utiliser
    jsonAttr() pour les arguments stringifiés (id, p.id, s.id) qui pourraient
    contenir des apostrophes si jamais on en acceptait en input."""
    html = client.get("/").text

    # genererPortrait : deux arguments string (id, p.id)
    m = re.search(r'onclick="genererPortrait\([^"]*\)"', html, re.DOTALL)
    assert m, "onclick='genererPortrait(...)' introuvable"
    ligne = m.group(0)
    assert "jsonAttr(" in ligne
    assert "esc(" not in ligne

    # genererAnimation : deux arguments string (id, p.id)
    m = re.search(r'onclick="genererAnimation\([^"]*\)"', html, re.DOTALL)
    assert m, "onclick='genererAnimation(...)' introuvable"
    ligne = m.group(0)
    assert "jsonAttr(" in ligne
    assert "esc(" not in ligne

    # genererCouverture : un argument string (id), un entier (e.n)
    m = re.search(r'onclick="genererCouverture\([^"]*\)"', html, re.DOTALL)
    assert m, "onclick='genererCouverture(...)' introuvable"
    ligne = m.group(0)
    assert "jsonAttr(" in ligne
    assert "esc(" not in ligne

    # genererTeaser : un argument string (id), un entier (e.n)
    m = re.search(r'onclick="genererTeaser\([^"]*\)"', html, re.DOTALL)
    assert m, "onclick='genererTeaser(...)' introuvable"
    ligne = m.group(0)
    assert "jsonAttr(" in ligne
    assert "esc(" not in ligne

    # supprimerGalerie : un argument string (s.id)
    m = re.search(r'onclick="supprimerGalerie\([^"]*\)"', html, re.DOTALL)
    assert m, "onclick='supprimerGalerie(...)' introuvable"
    ligne = m.group(0)
    assert "jsonAttr(" in ligne
    assert "esc(" not in ligne
