"""Tests de la facturation (S43) — **mode mock** uniquement (sans clé Stripe, hors ligne).

On prouve la dégradation honnête : sans clé, aucune prétention d'encaissement ; et le
webhook refuse d'agir sans secret (on ne réintroduit pas le trou du mock non signé, S21).
Le chemin LIVE (vrai SDK + signature) se prouve en intégration avec une clé sk_test_.
"""
import pytest

import paiement


@pytest.fixture(autouse=True)
def sans_cle(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)


def test_etat_mock_sans_cle():
    e = paiement.etat()
    assert e["configure"] is False and e["mode"] == "mock"


def test_checkout_mock_ne_pretend_pas_encaisser():
    commande = {"id": "abc", "nom_marque": "Acme", "modele": "acme",
                "prix_cents": 4900, "devise": "eur"}
    r = paiement.creer_checkout(commande)
    assert r["mode"] == "mock"
    assert r["session_id"].startswith("cs_mock_")
    assert "aucun encaissement" in r["message"].lower()


def test_webhook_refuse_sans_secret():
    with pytest.raises(ValueError) as e:
        paiement.verifier_webhook(b"{}", "sig")
    assert str(e.value) == "non_configure"


def test_masque_ne_revele_pas_la_cle(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_abcdefghijklmnop")
    e = paiement.etat()
    assert e["mode"] == "test"
    assert "abcdefghijkl" not in e["indice_cle"]  # corps masqué
