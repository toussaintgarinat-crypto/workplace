"""Extraction du corps HTML (le bug : les emails HTML-only revenaient vides).

On teste `_extrait_corps` à froid sur de vrais objets `email.message` construits à la main :
  • email texte seul       → corps texte, pas de HTML
  • email HTML seul         → corps_html conservé + extrait dérivé du HTML (plus jamais vide)
  • email multipart (2 vues)→ on garde LES DEUX, extrait depuis le text/plain
La route /static/purify.min.js doit servir DOMPurify vendu en local (offline).
"""
from email.message import EmailMessage

from fastapi.testclient import TestClient

import main
from fournisseurs import _extrait_corps, _strip_tags


def _texte_seul() -> EmailMessage:
    m = EmailMessage()
    m["Subject"] = "Bonjour"
    m.set_content("Coucou,\n\nÀ bientôt.\nMarina")
    return m


def _html_seul() -> EmailMessage:
    m = EmailMessage()
    m["Subject"] = "Newsletter"
    # Beaucoup d'emails marketing n'ont QUE du HTML : c'est le cas qui revenait vide.
    m.set_content("<html><body><h1>Soldes</h1><p>-50% sur <b>tout</b> !</p></body></html>",
                  subtype="html")
    return m


def _multipart() -> EmailMessage:
    m = EmailMessage()
    m["Subject"] = "Facture"
    m.set_content("Votre facture de juin est prête. Montant : 49 €.")
    m.add_alternative("<html><body><p>Votre facture de juin est prête. "
                      "Montant : <b>49 €</b>.</p></body></html>", subtype="html")
    return m


def test_texte_seul_pas_de_html():
    corps, corps_html, extrait = _extrait_corps(_texte_seul())
    assert "Coucou" in corps
    assert corps_html == ""
    assert "Coucou" in extrait


def test_html_seul_conserve_et_extrait_non_vide():
    corps, corps_html, extrait = _extrait_corps(_html_seul())
    assert corps == ""                         # pas de text/plain
    assert "<h1>Soldes</h1>" in corps_html      # le HTML est GARDÉ pour l'affichage
    assert "Soldes" in extrait and "-50%" in extrait  # extrait dérivé du HTML, plus jamais vide
    assert "<" not in extrait                   # l'extrait, lui, est nettoyé des balises


def test_multipart_garde_les_deux_vues():
    corps, corps_html, extrait = _extrait_corps(_multipart())
    assert "facture de juin" in corps           # text/plain préservé
    assert "<b>49 €</b>" in corps_html          # text/html préservé
    assert "facture de juin" in extrait         # extrait depuis le plain (privilégié)


def test_strip_tags_retire_script_et_balises():
    sale = "<style>.x{}</style><script>alert(1)</script><p>Texte&nbsp;net</p>"
    assert _strip_tags(sale) == "Texte net"


def test_route_dompurify_servie_en_local():
    r = TestClient(main.app).get("/static/purify.min.js")
    assert r.status_code == 200
    assert "DOMPurify" in r.text
    assert "javascript" in r.headers["content-type"]
