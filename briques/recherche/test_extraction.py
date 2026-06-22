"""Tests de la lecture de page — fonctions PURES (hors-ligne)."""
import pytest

import extraction as x


def test_valider_url_refuse_non_web():
    for mauvais in ("file:///etc/passwd", "data:text/html,x", "javascript:alert(1)", "", "pas une url"):
        with pytest.raises(x.ErreurLecture):
            x.valider_url(mauvais)
    assert x.valider_url("  https://ex.org/p  ") == "https://ex.org/p"


def test_extraire_texte_repli_basique_retire_balises_et_scripts():
    html = ("<html><head><style>.x{color:red}</style></head><body>"
            "<script>evil()</script><h1>Titre</h1><p>Bonjour le monde &amp; co.</p>"
            "</body></html>")
    texte, moteur = x.extraire_texte(html)
    assert "Bonjour le monde & co." in texte
    assert "evil()" not in texte and "color:red" not in texte
    assert moteur in ("trafilatura", "html_basique")


def test_titre_page():
    assert x.titre_page("<title>Mon &amp; titre</title>") == "Mon & titre"
    assert x.titre_page("<html>sans titre</html>") == ""


def test_extraire_liens_resout_absolu_dedup_et_filtre_schemas():
    html = ('<a href="/page1">P1</a>'
            '<a href="https://autre.fr/x">Externe</a>'
            '<a href="mailto:a@b.fr">Mail</a>'
            '<a href="#ancre">Ancre</a>'
            '<a href="page1">Doublon</a>')
    liens = x.extraire_liens(html, "https://site.fr/dossier/", limite=10)
    urls = [l["url"] for l in liens]
    assert "https://site.fr/page1" in urls          # relatif absolu résolu
    assert "https://autre.fr/x" in urls
    assert all("mailto" not in u for u in urls)      # mailto écarté
    assert all("#" not in u for u in urls)           # ancre écartée
    assert len(urls) == len(set(urls))               # dédupliqué


def test_extraire_liens_respecte_la_limite():
    html = "".join(f'<a href="https://s.fr/{i}">{i}</a>' for i in range(30))
    assert len(x.extraire_liens(html, "https://s.fr/", limite=5)) == 5


def test_max_octets_defaut(monkeypatch):
    monkeypatch.delenv("RECHERCHE_MAX_OCTETS", raising=False)
    assert x.max_octets() == 3 * 1024 * 1024
    monkeypatch.setenv("RECHERCHE_MAX_OCTETS", "1000")
    assert x.max_octets() == 1000
