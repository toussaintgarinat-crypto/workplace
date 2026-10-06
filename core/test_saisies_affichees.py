"""Données déposables SANS session puis affichées par le dashboard (revue S240, C-A) :
validées ou assainies côté serveur, en plus de l'échappement côté front.

$ cd core && python3 -m pytest test_saisies_affichees.py -v
"""
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import journal_conversations  # noqa: E402
import main  # noqa: E402
import projets  # noqa: E402

client = TestClient(main.app)


@pytest.mark.parametrize("couleur", ["red", "#12345", "#abc;background:url(x)",
                                     "#fff\"><img src=x onerror=alert(1)>", "javascript:x", 12])
def test_couleur_de_projet_invalide_refusee(couleur):
    with pytest.raises(ValueError):
        projets.creer(nom="x", couleur=couleur)
    p = projets.creer(nom="ok")
    with pytest.raises(ValueError):
        projets.modifier(p["id"], couleur=couleur)


@pytest.mark.parametrize("couleur", ["#abc", "#7C83FF", "#7c83ff80", None])
def test_couleur_de_projet_valide(couleur):
    p = projets.creer(nom="x", couleur=couleur)
    assert p["couleur"].startswith("#")


def test_route_projet_couleur_invalide_400():
    r = client.post("/assistant/projets", json={"nom": "x", "couleur": "'><script>alert(1)</script>"})
    assert r.status_code == 400
    p = client.post("/assistant/projets", json={"nom": "x"}).json()["projet"]
    r = client.patch(f"/assistant/projets/{p['id']}", json={"couleur": "red;x"})
    assert r.status_code == 400


def test_fil_assaini():
    f = journal_conversations.fil("web'\"<x>", "a');alert(1);// b")
    surface, _, interlocuteur = f.partition(":")
    for partie in (surface, interlocuteur):
        assert partie and all(c.isalnum() or c in "_.@+-" for c in partie), f
    assert len(journal_conversations.fil("w" * 500, "i" * 500)) <= 64 + 1 + 128


def test_fil_inchange_pour_les_valeurs_reelles():
    assert journal_conversations.fil("web", "conv-lq3x9abcde") == "web:conv-lq3x9abcde"
    assert journal_conversations.fil("telegram", "telegram-perso") == "telegram:telegram-perso"
    assert journal_conversations.fil("", "") == "web:inconnu"
    assert journal_conversations.fil("web", "marina@exemple.fr") == "web:marina@exemple.fr"
    # Revue S240, M8 : les numéros WhatsApp/SMS gardent leur « + » (sinon l'historique se
    # scinde entre l'ancien fil « +33… » et un nouveau « _33… »).
    assert journal_conversations.fil("whatsapp", "+33612345678") == "whatsapp:+33612345678"
