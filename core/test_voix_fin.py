"""Fin du tour de parole en voix navigateur — persistance + bornes (config_assistant).

La logique de coupure vit côté front (Web Speech), mais le RÉGLAGE est persisté serveur :
'appui' (push-to-talk, défaut) vs 'silence' + délai borné 0,5–15 s. On prouve ici le
round-trip et les garde-fous. Autonome :
    $ cd core && python3 test_voix_fin.py
"""
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import config_assistant as C  # noqa: E402


def test_defaut_silence_5s():
    conf = C.charger()
    assert conf["voix_fin_mode"] == "silence", conf["voix_fin_mode"]
    assert conf["voix_silence_ms"] == 5000, conf["voix_silence_ms"]


def test_persistance_silence():
    C.definir_voix("webspeech", fin_mode="silence", silence_ms=2500)
    conf = C.charger()
    assert conf["voix_fin_mode"] == "silence"
    assert conf["voix_silence_ms"] == 2500


def test_mode_invalide_ignore():
    C.definir_voix("webspeech", fin_mode="silence", silence_ms=2500)
    C.definir_voix("webspeech", fin_mode="n_importe_quoi")
    assert C.charger()["voix_fin_mode"] == "silence"  # inchangé


def test_silence_borne_haut_et_bas():
    C.definir_voix("webspeech", silence_ms=99000)
    assert C.charger()["voix_silence_ms"] == 15000
    C.definir_voix("webspeech", silence_ms=10)
    assert C.charger()["voix_silence_ms"] == 500


def test_silence_ms_non_numerique_ignore():
    C.definir_voix("webspeech", silence_ms=2000)
    C.definir_voix("webspeech", silence_ms="abc")
    assert C.charger()["voix_silence_ms"] == 2000  # inchangé


def test_setter_voix_n_ecrase_pas_les_autres_champs():
    # Régler la fin de parole ne doit pas perdre le fournisseur/URL déjà en place.
    C.definir_voix("wakeword", wakeword_url="ws://localhost:5800/ecoute")
    C.definir_voix("wakeword", fin_mode="appui", silence_ms=4000)
    conf = C.charger()
    assert conf["voix_provider"] == "wakeword"
    assert conf["wakeword_url"] == "ws://localhost:5800/ecoute"
    assert conf["voix_fin_mode"] == "appui"


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
