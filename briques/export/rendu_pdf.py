"""Rendu PDF DÉTERMINISTE (WeasyPrint) — Markdown → HTML thémé → PDF.

Le thème est un CSS EMBARQUÉ choisi par nom ('livre' ou 'rapport'), jamais un CSS fourni
par l'appelant (pas de surface d'injection libre, cf. design S194).

WeasyPrint est importé PARESSEUSEMENT à l'intérieur de `_rendu_html_vers_pdf` (pas au
niveau module) : ses libs natives (Pango/Cairo/GDK-Pixbuf) ne sont dlopen qu'à cet
instant, jamais au simple `import rendu_pdf`. Ça permet aux tests offline de mocker
`_rendu_html_vers_pdf` sans que ces libs système soient installées sur la machine qui
lance pytest (même logique que `habillage.py` avec `shutil.which("ffmpeg")`).
"""
from __future__ import annotations

import markdown as _markdown

THEMES = {"livre", "rapport"}

_CSS_LIVRE = """
@page { size: A5; margin: 2.5cm 2cm; }
body { font-family: Georgia, 'Times New Roman', serif; font-size: 11pt; line-height: 1.5; }
h1 { page-break-before: always; font-size: 20pt; }
"""

_CSS_RAPPORT = """
@page { size: A4; margin: 2cm; @bottom-center { content: counter(page); } }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10pt; line-height: 1.4; }
h1 { font-size: 18pt; border-bottom: 1px solid #333; }
"""

_CSS_PAR_THEME = {"livre": _CSS_LIVRE, "rapport": _CSS_RAPPORT}


def construire_html(titre: str, markdown_src: str) -> str:
    """Markdown → document HTML complet (pure, testable sans WeasyPrint)."""
    corps = _markdown.markdown(markdown_src or "", extensions=["extra"])
    return f"<html><head><meta charset='utf-8'><title>{titre}</title></head><body>{corps}</body></html>"


def _rendu_html_vers_pdf(html: str, css_str: str) -> bytes:
    from weasyprint import CSS, HTML   # import paresseux : natif, mocké en test offline
    return HTML(string=html).write_pdf(stylesheets=[CSS(string=css_str)])


def generer(titre: str, markdown_src: str, theme: str = "livre") -> bytes:
    if not (titre or "").strip():
        raise ValueError("Le titre est vide.")
    if not (markdown_src or "").strip():
        raise ValueError("Le contenu Markdown est vide.")
    if theme not in THEMES:
        raise ValueError(f"Thème inconnu : {theme!r} (attendu : {sorted(THEMES)}).")
    html = construire_html(titre, markdown_src)
    return _rendu_html_vers_pdf(html, _CSS_PAR_THEME[theme])
