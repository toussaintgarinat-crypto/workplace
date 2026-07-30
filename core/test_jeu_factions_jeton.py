"""Jeton signé Cœur→jeu-factions (S217) — côté émission (core/jeu_factions_jeton.py). La
vérification (côté brique, process séparé) est testée dans
briques/jeu-factions/test_jeton.py."""
import jeu_factions_jeton as jfj


def test_sans_cle_configuree_aucun_jeton(monkeypatch):
    monkeypatch.delenv("JEU_FACTIONS_KEY", raising=False)
    assert jfj.emettre("claire") is None


def test_avec_cle_jeton_porte_lutilisateur_et_une_signature(monkeypatch):
    monkeypatch.setenv("JEU_FACTIONS_KEY", "cle-coeur-jeu-factions")
    jeton = jfj.emettre("claire")
    assert jeton is not None
    utilisateur, expire, signature = jeton.split(":")
    assert utilisateur == "claire"
    assert expire.isdigit()
    assert len(signature) == 64  # hex sha256


def test_deux_personnes_jetons_distincts(monkeypatch):
    monkeypatch.setenv("JEU_FACTIONS_KEY", "cle-coeur-jeu-factions")
    assert jfj.emettre("claire") != jfj.emettre("marina")
