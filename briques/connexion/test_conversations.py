"""Tests de l'historique persisté par interlocuteur (séparation + fenêtre bornée)."""
import conversations as C


def test_vide_au_depart():
    assert C.charger("telegram", "neuf") == []


def test_ajouter_et_charger():
    C.ajouter("telegram", "u1", "user", "salut")
    C.ajouter("telegram", "u1", "assistant", "bonjour")
    fil = C.charger("telegram", "u1")
    assert [m["role"] for m in fil] == ["user", "assistant"]
    assert fil[0]["content"] == "salut"


def test_separation_par_interlocuteur():
    C.ajouter("telegram", "a", "user", "A")
    C.ajouter("telegram", "b", "user", "B")
    assert C.charger("telegram", "a")[-1]["content"] == "A"
    assert C.charger("telegram", "b")[-1]["content"] == "B"


def test_fenetre_bornee(monkeypatch):
    monkeypatch.setenv("CONNEXION_HISTORIQUE_MAX", "4")
    for i in range(10):
        C.ajouter("telegram", "borne", "user", str(i))
    fil = C.charger("telegram", "borne")
    assert len(fil) == 4
    assert [m["content"] for m in fil] == ["6", "7", "8", "9"]


def test_effacer():
    C.ajouter("telegram", "z", "user", "x")
    C.effacer("telegram", "z")
    assert C.charger("telegram", "z") == []
