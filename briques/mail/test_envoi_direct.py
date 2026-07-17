"""Envoi DIRECT (pas un brouillon) — `POST /mail/envoyer`, socle du digest S178.

Sert à envoyer un email HTML directement (le digest construit son propre HTML). Honnêteté
identique au reste de la brique : sans boîte réelle connectée, l'envoi est SIMULÉ (mode="simule"),
rien ne part réellement.
"""
from fastapi.testclient import TestClient

import main


def test_envoyer_direct_simule_sans_boite():
    c = TestClient(main.app)
    r = c.post("/mail/envoyer", json={"a": "x@example.org", "sujet": "Digest",
                                      "corps": "texte", "corps_html": "<b>hi</b>"})
    assert r.status_code == 200
    assert r.json()["mode"] == "simule" and r.json()["envoye"] is True


def test_envoi_html_alternative():
    from envoi import envoyer
    # compte None ⇒ simulé, mais l'appel ne doit pas lever avec corps_html.
    res = envoyer(None, a="x@example.org", sujet="s", corps="t", corps_html="<b>h</b>")
    assert res["mode"] == "simule"
