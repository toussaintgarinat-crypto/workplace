"""Tests des fournisseurs TTS : registre/ordre/disponibilité (hors réseau, déterministe)."""
import asyncio
import types

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


# ── Conversion WAV → Ogg/Opus (bulle vocale Telegram) ─────────────────────────

def test_vers_opus_via_ffmpeg(monkeypatch):
    monkeypatch.setattr(F.shutil, "which", lambda _b: "/usr/bin/ffmpeg")

    def fake_run(cmd, input=None, capture_output=None, timeout=None):
        assert "libopus" in cmd                    # on demande bien de l'Opus
        return types.SimpleNamespace(returncode=0, stdout=b"OGGOPUS", stderr=b"")

    monkeypatch.setattr(F.subprocess, "run", fake_run)
    assert F._vers_opus(b"WAVDATA") == b"OGGOPUS"


def test_vers_opus_repli_si_ffmpeg_absent(monkeypatch):
    monkeypatch.setattr(F.shutil, "which", lambda _b: None)
    assert F._vers_opus(b"WAVDATA") is None        # repli honnête : pas de conversion


def _faux_run_piper(ogg_ok: bool):
    """Simule piper (écrit un WAV) + ffmpeg (rend de l'Opus, ou échoue)."""
    def run(cmd, input=None, capture_output=None, timeout=None):
        if cmd[0].endswith("ffmpeg"):
            return types.SimpleNamespace(returncode=0 if ogg_ok else 1,
                                         stdout=b"OGG" if ogg_ok else b"", stderr=b"")
        out = cmd[cmd.index("--output_file") + 1]
        with open(out, "wb") as f:
            f.write(b"WAV")
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    return run


def test_piper_convertit_wav_en_ogg(monkeypatch, tmp_path):
    modele = tmp_path / "fr.onnx"; modele.write_bytes(b"x")
    monkeypatch.setenv("PIPER_VOICE", str(modele))
    monkeypatch.setattr(F.shutil, "which", lambda b: "/usr/bin/" + b)
    monkeypatch.setattr(F.subprocess, "run", _faux_run_piper(ogg_ok=True))
    audio, fmt = asyncio.run(F.Piper().synthetiser("Bonjour", None, None, "opus"))
    assert fmt == "ogg" and audio == b"OGG"        # bulle vocale Telegram


def test_piper_garde_wav_si_ffmpeg_absent(monkeypatch, tmp_path):
    modele = tmp_path / "fr.onnx"; modele.write_bytes(b"x")
    monkeypatch.setenv("PIPER_VOICE", str(modele))
    monkeypatch.setattr(F.shutil, "which", lambda b: None if b == "ffmpeg" else "/usr/bin/" + b)
    monkeypatch.setattr(F.subprocess, "run", _faux_run_piper(ogg_ok=False))
    audio, fmt = asyncio.run(F.Piper().synthetiser("Bonjour", None, None, "opus"))
    assert fmt == "wav" and audio == b"WAV"        # repli honnête
