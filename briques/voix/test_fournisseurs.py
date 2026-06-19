"""Tests des fournisseurs TTS : registre/ordre/disponibilité (hors réseau, déterministe)."""
import fournisseurs as F


def test_registre_quatre_fournisseurs():
    assert set(F.REGISTRE) == {"piper", "openai", "elevenlabs", "gateway"}


def test_ordre_souverain_en_tete():
    assert F.ordre()[0] == "piper"
    assert F.ordre() == ["piper", "openai", "elevenlabs", "gateway"]


def test_ordre_env(monkeypatch):
    monkeypatch.setenv("VOIX_PROVIDERS", "elevenlabs, openai")
    assert F.ordre() == ["elevenlabs", "openai"]


def test_disponibles_vide_par_defaut():
    # conftest a coupé Piper et purgé toutes les clés → repli placeholder honnête.
    assert F.disponibles() == []


def test_openai_disponible(monkeypatch):
    assert F.REGISTRE["openai"].disponible() is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert F.REGISTRE["openai"].disponible() is True


def test_elevenlabs_disponible(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-x")
    assert F.REGISTRE["elevenlabs"].disponible() is True


def test_gateway_disponible(monkeypatch):
    monkeypatch.setenv("GATEWAY_KEY", "gw-x")
    assert F.REGISTRE["gateway"].disponible() is True


def test_piper_disponible_demande_binaire_et_modele(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_LOCAL", "1")           # réactive le souverain pour ce test
    modele = tmp_path / "fr.onnx"
    modele.write_bytes(b"onnx")
    monkeypatch.setenv("PIPER_VOICE", str(modele))
    # binaire absent → indisponible
    monkeypatch.setattr(F.shutil, "which", lambda _b: None)
    assert F.REGISTRE["piper"].disponible() is False
    # binaire présent + modèle → disponible
    monkeypatch.setattr(F.shutil, "which", lambda _b: "/usr/bin/piper")
    assert F.REGISTRE["piper"].disponible() is True
    # sans modèle → indisponible même avec le binaire
    monkeypatch.delenv("PIPER_VOICE")
    assert F.REGISTRE["piper"].disponible() is False
