"""Tests de la correspondance multi-utilisateur : consentement, liaison, mode ouvert."""
import correspondance as K


def test_inconnu_non_autorise_et_code():
    r = K.resoudre("telegram", "inconnu1", "Bob")
    assert r["autorise"] is False
    assert r["statut"] == "en_attente"
    assert r["nouveau"] is True
    assert r["code"]                                  # un code de liaison est attribué
    # 2ᵉ passage : plus « nouveau », même code, toujours en attente
    r2 = K.resoudre("telegram", "inconnu1", "Bob")
    assert r2["nouveau"] is False and r2["code"] == r["code"]


def test_lier_puis_autorise():
    K.resoudre("telegram", "u2", "Alice")
    K.lier("telegram", "u2", "alice@workplace")
    r = K.resoudre("telegram", "u2", "Alice")
    assert r["autorise"] is True
    assert r["utilisateur"] == "alice@workplace"
    assert r["statut"] == "lie"


def test_lier_par_code():
    r = K.resoudre("whatsapp", "33611", "Léa")
    e = K.lier_par_code(r["code"], "lea@workplace")
    assert e is not None and e["utilisateur"] == "lea@workplace"
    assert K.resoudre("whatsapp", "33611")["autorise"] is True
    assert K.lier_par_code("ZZZZZZ", "x") is None


def test_delier():
    K.lier("discord", "d1", "u")
    assert K.delier("discord", "d1") is True
    assert K.resoudre("discord", "d1")["autorise"] is False
    assert K.delier("discord", "absent") is False


def test_mode_ouvert(monkeypatch):
    monkeypatch.setenv("CONNEXION_OUVERT", "1")
    monkeypatch.setenv("CONNEXION_UTILISATEUR_DEFAUT", "patron")
    r = K.resoudre("telegram", "ouvert1", "Qui")
    assert r["autorise"] is True
    assert r["statut"] == "ouvert"
    assert r["utilisateur"] == "patron"
