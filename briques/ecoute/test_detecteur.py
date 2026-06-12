"""Tests hors ligne du détecteur en flux (S42).

On rejoue les échantillons WAV du POC S41 (`poc/echantillons/`) MAIS en les
découpant en petits blocs d'octets, comme le fera le flux WebSocket — c'est ça
qu'on doit prouver : que la détection « par morceaux » donne le même verdict que
la passe d'un fichier entier du POC. Positifs « hey jarvis » → au moins un réveil ;
négatifs (dont parole FR et « hey google » phonétiquement proche) → zéro réveil.

Limite assumée (mesurée au POC, cf. DECISION.md) : `pos_alex` (voix robotique 0,6 s)
n'atteint pas le seuil avec le modèle pré-entraîné → exclu des positifs ici ; il sera
rattrapé par un modèle entraîné par nom (palier S43). On ne triche pas : on documente.

Lance : `cd briques/ecoute && poc/.venv/bin/python -m pytest test_detecteur.py -v`
(le venv du POC porte openwakeword 0.6 + onnxruntime, Python 3.11).
"""
import glob
import os
import wave

import pytest

from detecteur import Detecteur

ICI = os.path.dirname(os.path.abspath(__file__))
ECH = os.path.join(ICI, "poc", "echantillons")

# Positifs attendus (réveil) — on EXCLUT pos_alex (limite connue du pré-entraîné, S43).
POSITIFS_FIABLES = {"pos_daniel", "pos_phrase", "pos_samantha"}


def _pcm_16k_mono(chemin: str) -> bytes:
    with wave.open(chemin, "rb") as w:
        assert w.getframerate() == 16000, f"{chemin}: pas 16 kHz"
        assert w.getnchannels() == 1, f"{chemin}: pas mono"
        return w.readframes(w.getnframes())


def _reveils_en_flux(chemin: str, taille_bloc_octets: int = 533) -> int:
    """Streame le WAV par blocs de taille NON alignée sur 1280 (533 octets ≈ 266
    échantillons) pour prouver que le tampon recolle les fenêtres à travers les blocs."""
    pcm = _pcm_16k_mono(chemin)
    d = Detecteur()
    total = 0
    for i in range(0, len(pcm), taille_bloc_octets):
        total += len(d.alimenter(pcm[i : i + taille_bloc_octets]))
    return total


def _fichiers():
    return sorted(glob.glob(os.path.join(ECH, "*.wav")))


def test_echantillons_presents():
    assert _fichiers(), "Échantillons POC manquants — lance poc/synthese.sh"


@pytest.mark.parametrize("nom", sorted(POSITIFS_FIABLES))
def test_positif_reveille(nom):
    chemin = os.path.join(ECH, nom + ".wav")
    assert os.path.exists(chemin), f"{nom}.wav manquant"
    assert _reveils_en_flux(chemin) >= 1, f"{nom} aurait dû réveiller"


@pytest.mark.parametrize("chemin", [f for f in _fichiers()
                                    if os.path.basename(f).startswith("neg_")])
def test_negatif_silencieux(chemin):
    assert _reveils_en_flux(chemin) == 0, f"{os.path.basename(chemin)} a faussement réveillé"


def test_refraction_anti_rafale():
    """Un positif ne doit produire qu'UN réveil malgré plusieurs fenêtres au-dessus du
    seuil (la réfraction évite la rafale qui spammerait /assistant/chat)."""
    chemin = os.path.join(ECH, "pos_phrase.wav")
    assert _reveils_en_flux(chemin) == 1


def test_reset_repart_a_zero():
    d = Detecteur()
    pcm = _pcm_16k_mono(os.path.join(ECH, "pos_daniel.wav"))
    n1 = sum(len(d.alimenter(pcm[i:i + 533])) for i in range(0, len(pcm), 533))
    d.reset()
    n2 = sum(len(d.alimenter(pcm[i:i + 533])) for i in range(0, len(pcm), 533))
    assert n1 >= 1 and n2 >= 1, "après reset, le flux doit redétecter"
