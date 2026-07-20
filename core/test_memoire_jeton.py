"""Jeton signé Cœur→mémoire (S186) — côté émission (core/memoire_jeton.py). La vérification
(côté brique, process séparé) est testée dans briques/memoire/test_spa_personne.py."""
import memoire_jeton as mj


def test_sans_cle_configuree_aucun_jeton(monkeypatch):
    monkeypatch.delenv("MEMOIRE_KEY", raising=False)
    assert mj.emettre("claire") is None


def test_avec_cle_jeton_porte_lutilisateur_et_une_signature(monkeypatch):
    monkeypatch.setenv("MEMOIRE_KEY", "cle-coeur-memoire")
    jeton = mj.emettre("claire")
    assert jeton is not None
    utilisateur, expire, signature = jeton.split(":")
    assert utilisateur == "claire"
    assert expire.isdigit()
    assert len(signature) == 64  # hex sha256


def test_deux_personnes_jetons_distincts(monkeypatch):
    monkeypatch.setenv("MEMOIRE_KEY", "cle-coeur-memoire")
    assert mj.emettre("claire") != mj.emettre("marina")
