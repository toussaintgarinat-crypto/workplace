#!/usr/bin/env python3
"""S41 POC openWakeWord — preuve de détection (hors ligne, reproductible).

Charge le modèle pré-entraîné `hey_jarvis` d'openWakeWord et le fait défiler sur
chaque WAV de ./echantillons par fenêtres de 80 ms (1280 éch. @ 16 kHz, le pas
attendu par le modèle). On retient le score MAX atteint sur le fichier et on le
compare à un seuil. C'est exactement la boucle qu'exécutera la future brique
`ecoute` (S42), sauf qu'ici l'audio vient de fichiers au lieu d'un flux WebSocket.

But : prouver que le moteur de détection openWakeWord tourne sur notre infra et
distingue le mot-clé du reste — l'un des deux risques go/no-go du plan S41.
"""
import glob
import os
import sys
import wave

import numpy as np
from openwakeword.model import Model

ICI = os.path.dirname(os.path.abspath(__file__))
SEUIL = 0.5  # seuil par défaut openWakeWord (proba)


def lire_wav_16k_mono(chemin: str) -> np.ndarray:
    with wave.open(chemin, "rb") as w:
        assert w.getframerate() == 16000, f"{chemin}: pas 16 kHz"
        assert w.getnchannels() == 1, f"{chemin}: pas mono"
        brut = w.readframes(w.getnframes())
    return np.frombuffer(brut, dtype=np.int16)


def score_max(modele: Model, audio: np.ndarray, mot: str) -> float:
    modele.reset()
    pic = 0.0
    for i in range(0, len(audio) - 1280, 1280):
        pred = modele.predict(audio[i : i + 1280])
        pic = max(pic, float(pred[mot]))
    return pic


def main() -> int:
    mot = "hey_jarvis_v0.1"
    modele = Model(wakeword_models=[mot], inference_framework="onnx")
    fichiers = sorted(glob.glob(os.path.join(ICI, "echantillons", "*.wav")))
    if not fichiers:
        print("Aucun échantillon. Lance d'abord ./synthese.sh", file=sys.stderr)
        return 2

    print(f"Modèle : {mot}   seuil : {SEUIL}\n")
    print(f"{'fichier':<22}{'attendu':<10}{'score':>8}  verdict")
    print("-" * 56)
    erreurs = 0
    for f in fichiers:
        nom = os.path.basename(f)
        attendu = "POSITIF" if nom.startswith("pos_") else "négatif"
        s = score_max(modele, lire_wav_16k_mono(f), mot)
        detecte = s >= SEUIL
        ok = (detecte and attendu == "POSITIF") or (not detecte and attendu == "négatif")
        if not ok:
            erreurs += 1
        verdict = ("🔔 détecté" if detecte else "— silence") + ("" if ok else "  ❌ ERREUR")
        print(f"{nom:<22}{attendu:<10}{s:>8.3f}  {verdict}")

    print("-" * 56)
    print(f"{'OK ✅ aucune erreur' if erreurs == 0 else f'{erreurs} erreur(s) ❌'}")
    return 0 if erreurs == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
