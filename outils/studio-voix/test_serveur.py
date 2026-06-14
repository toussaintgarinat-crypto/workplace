"""Test S45 du serveur voix : _voix_par_langue parse `say -v ?` et range les voix par
langue — monolingues uniquement (prononciation fiable), voix « nouveauté » écartées,
préférences en tête. `say` est monkeypatché → tourne sans macOS."""
import subprocess

import serveur

SAMPLE = """Thomas              fr_FR    # Bonjour, je m'appelle Thomas.
Amélie              fr_CA    # Bonjour, je m'appelle Amélie.
Samantha            en_US    # Hi, my name is Samantha.
Daniel              en_GB    # Hi, my name is Daniel.
Albert              en_US    # joke voice
Flo (Enhanced)      fr_CA    # multilingue
Flo (Enhanced)      en_US    # multilingue
Mónica              es_ES    # Hola, me llamo Mónica.
Majed               ar_001   # مرحبا
Kyoko               ja_JP    # こんにちは
Tingting            zh_CN    # 你好
"""


def test_voix_par_langue(monkeypatch):
    class R:
        stdout = SAMPLE
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    par = serveur._voix_par_langue()

    # FR : voix « propres » en tête (PREF), multilingue Flo écartée
    assert par["fr"][:2] == ["Thomas", "Amélie"]
    assert "Flo" not in par["fr"]
    # EN : préférence Samantha en tête, voix nouveauté Albert exclue, Flo (multi) écartée
    assert par["en"][0] == "Samantha"
    assert "Daniel" in par["en"]
    assert "Albert" not in par["en"]
    assert "Flo" not in par["en"]
    # Autres langues : monolingues bien rangées
    assert par["es"] == ["Mónica"]
    assert par["ar"] == ["Majed"]
    assert par["ja"] == ["Kyoko"]
    assert par["zh"] == ["Tingting"]


def test_repli_fr_si_say_absent(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("say introuvable")
    monkeypatch.setattr(subprocess, "run", boom)
    assert serveur._voix_par_langue() == {"fr": ["Thomas"]}
