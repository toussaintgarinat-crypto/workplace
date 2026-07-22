"""Tests — rendu_pdf.py.

WeasyPrint dlopen des libs natives (Pango/Cairo/GDK-Pixbuf) au moment où on l'appelle
pour de vrai — indisponibles sur une machine de dev sans ces paquets système (constaté :
ce Mac ne les a pas). `_rendu_html_vers_pdf` isole cet appel ; ces tests le mockent, comme
`test_habillage.py` mocke `subprocess.run` pour ffmpeg. La preuve d'un VRAI PDF valide se
fait dans Docker (le Dockerfile installe ces libs), cf. plan Task 5.
"""
import rendu_pdf as P


def test_construire_html_convertit_markdown():
    html = P.construire_html("Mon titre", "# Bonjour\n\nUn **texte**.")
    assert "<h1>Bonjour</h1>" in html
    assert "<strong>texte</strong>" in html
    assert "Mon titre" in html


def test_generer_titre_vide_leve():
    try:
        P.generer("", "contenu")
    except ValueError as e:
        assert "titre" in str(e).lower()
    else:
        raise AssertionError("titre vide aurait dû lever ValueError")


def test_generer_markdown_vide_leve():
    try:
        P.generer("Titre", "   ")
    except ValueError as e:
        assert "markdown" in str(e).lower()
    else:
        raise AssertionError("markdown vide aurait dû lever ValueError")


def test_generer_theme_inconnu_leve():
    try:
        P.generer("Titre", "# x", theme="neon")
    except ValueError as e:
        assert "thème" in str(e).lower() or "theme" in str(e).lower()
    else:
        raise AssertionError("thème inconnu aurait dû lever ValueError")


def test_generer_appelle_le_rendu_avec_le_theme_choisi(monkeypatch):
    appels = {}

    def faux_rendu(html, css):
        appels["html"] = html
        appels["css"] = css
        return b"PDFBYTES"

    monkeypatch.setattr(P, "_rendu_html_vers_pdf", faux_rendu)
    resultat = P.generer("Mon Tome", "# Chapitre 1", theme="rapport")
    assert resultat == b"PDFBYTES"
    assert "Mon Tome" in appels["html"] and "Chapitre 1" in appels["html"]
    assert appels["css"] == P._CSS_PAR_THEME["rapport"]
