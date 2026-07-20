"""Tests — habillage.py (cartes de titre + sous-titres incrustés, ffmpeg mocké, aucun réseau)."""
import types

import habillage as H


# ── Fonctions pures (aucun ffmpeg requis) ───────────────────────────────────

def test_temps_srt_formate():
    assert H._temps_srt(0) == "00:00:00,000"
    assert H._temps_srt(65.5) == "00:01:05,500"
    assert H._temps_srt(3661.001) == "01:01:01,001"


def test_construire_srt_ignore_segments_invalides():
    srt = H.construire_srt([
        {"debut": 0, "fin": 2, "texte": "Bonjour"},
        {"debut": 5, "fin": 3, "texte": "fin avant début, ignoré"},
        {"debut": 6, "fin": 8, "texte": "  "},               # texte vide, ignoré
        {"debut": 9, "fin": 11, "texte": "Au revoir"},
    ])
    assert "1\n00:00:00,000 --> 00:00:02,000\nBonjour" in srt
    assert "2\n00:00:09,000 --> 00:00:11,000\nAu revoir" in srt
    assert "ignoré" not in srt


def test_construire_srt_vide_si_rien_dexploitable():
    assert H.construire_srt([]) == ""
    assert H.construire_srt([{"debut": 0, "fin": 0, "texte": "x"}]) == ""


def test_echapper_drawtext():
    assert H._echapper_drawtext("11:30 - c'est l'heure") == "11\\:30 - c’est l’heure"
    assert H._echapper_drawtext("100% sûr") == "100\\% sûr"


def test_carte_titre_texte_vide_leve():
    try:
        H.carte_titre("")
    except ValueError:
        pass
    else:
        raise AssertionError("texte vide aurait dû lever ValueError")


def test_sous_titrer_sans_segment_exploitable_leve():
    try:
        H.sous_titrer(b"MP4DATA", [])
    except ValueError:
        pass
    else:
        raise AssertionError("segments vides auraient dû lever ValueError")


# ── Appels ffmpeg (subprocess mocké) ────────────────────────────────────────

def test_disponible_suit_shutil_which(monkeypatch):
    monkeypatch.setattr(H.shutil, "which", lambda _b: "/usr/bin/ffmpeg")
    assert H.disponible() is True
    monkeypatch.setattr(H.shutil, "which", lambda _b: None)
    assert H.disponible() is False


def test_carte_titre_leve_si_ffmpeg_absent(monkeypatch):
    monkeypatch.setattr(H.shutil, "which", lambda _b: None)
    try:
        H.carte_titre("Chapitre 1")
    except RuntimeError as e:
        assert "ffmpeg introuvable" in str(e)
    else:
        raise AssertionError("ffmpeg absent aurait dû lever RuntimeError")


def test_carte_titre_appelle_ffmpeg_avec_drawtext(monkeypatch):
    monkeypatch.setattr(H.shutil, "which", lambda _b: "/usr/bin/ffmpeg")

    def fake_run(cmd, capture_output=None, timeout=None):
        assert any("drawtext" in c for c in cmd)
        assert "Chapitre 1" in " ".join(cmd)
        return types.SimpleNamespace(returncode=0, stdout=b"MP4BYTES", stderr=b"")

    monkeypatch.setattr(H.subprocess, "run", fake_run)
    assert H.carte_titre("Chapitre 1", sous_titre="La rencontre") == b"MP4BYTES"


def test_carte_titre_leve_si_ffmpeg_echoue(monkeypatch):
    monkeypatch.setattr(H.shutil, "which", lambda _b: "/usr/bin/ffmpeg")
    monkeypatch.setattr(H.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=1, stdout=b"", stderr=b"erreur ffmpeg"))
    try:
        H.carte_titre("Chapitre 1")
    except RuntimeError as e:
        assert "ffmpeg a échoué" in str(e)
    else:
        raise AssertionError("échec ffmpeg aurait dû lever RuntimeError")


def test_sous_titrer_appelle_ffmpeg_avec_subtitles(monkeypatch):
    monkeypatch.setattr(H.shutil, "which", lambda _b: "/usr/bin/ffmpeg")

    def fake_run(cmd, capture_output=None, timeout=None):
        assert any("subtitles=" in c for c in cmd)
        return types.SimpleNamespace(returncode=0, stdout=b"MP4SOUSTITRE", stderr=b"")

    monkeypatch.setattr(H.subprocess, "run", fake_run)
    resultat = H.sous_titrer(b"MP4DATA", [{"debut": 0, "fin": 2, "texte": "Bonjour"}])
    assert resultat == b"MP4SOUSTITRE"
