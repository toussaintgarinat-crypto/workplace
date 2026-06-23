"""Lecture de page : extraction PURE (sans réseau) + garde-fous d'URL."""
import pytest

import extraction


HTML = """
<html><head><title>Ma &amp; Page</title></head>
<body>
  <script>var x = 1;</script>
  <nav>menu</nav>
  <p>Contenu utile éditorial.</p>
  <a href="/interne">Lien interne</a>
  <a href="https://ext.test/page">Lien externe</a>
  <a href="mailto:x@y.z">mail</a>
  <a href="#ancre">ancre</a>
</body></html>
"""


def test_titre_decode_les_entites():
    assert extraction.titre_page(HTML) == "Ma & Page"


def test_extraire_texte_retire_scripts_et_balises():
    texte, moteur = extraction.extraire_texte(HTML)
    assert "Contenu utile éditorial." in texte
    assert "var x = 1" not in texte
    assert moteur in ("trafilatura", "html_basique")


def test_extraire_liens_absolus_et_filtre_les_non_web():
    liens = extraction.extraire_liens(HTML, "https://site.test/dir/")
    urls = [l["url"] for l in liens]
    assert "https://site.test/interne" in urls       # relatif → absolu
    assert "https://ext.test/page" in urls
    assert all(not u.startswith("mailto:") for u in urls)   # mailto ignoré
    assert all("#" not in u for u in urls)                  # ancre ignorée


def test_valider_url_refuse_les_schemas_non_web():
    for mauvais in ("file:///etc/passwd", "data:text/html,x", "javascript:alert(1)", "pas une url"):
        with pytest.raises(extraction.ErreurLecture):
            extraction.valider_url(mauvais)
    assert extraction.valider_url("https://ok.test/x") == "https://ok.test/x"
