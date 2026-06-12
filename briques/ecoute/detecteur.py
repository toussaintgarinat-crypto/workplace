"""Détecteur de mot-clé en *flux continu* (S42) — le cœur de la brique « ecoute ».

Le POC S41 (`poc/detection.py`) faisait défiler un fichier WAV entier par fenêtres
de 80 ms et retenait le score max. Ici on fait la même chose, mais sur un **flux**
qui arrive par morceaux (WebSocket) : on accumule les échantillons PCM 16 kHz mono
int16 dans un tampon, et dès qu'on a 1280 échantillons (= 80 ms, le pas attendu par
openWakeWord) on appelle `predict`. C'est exactement la boucle de `score_max`, mais
sans connaître la fin du flux.

Garde-fous portés du POC :
- **seuil 0.5** (défaut openWakeWord) ;
- **fenêtre de réfraction** après un réveil (anti-rafale : un « hey jarvis » ne doit
  pas déclencher 5 fois en 400 ms) ;
- openWakeWord est **Python/ONNX (CPU)**, modèles ~1 Mo → pas de GPU.

Le détecteur ne connaît NI le réseau NI WebSocket : il prend des octets, rend des
événements. `main.py` le branche sur le flux. Cette séparation rend la détection
testable hors ligne (cf. `test_detecteur.py`) avec les mêmes échantillons que le POC.
"""
from __future__ import annotations

import os

import numpy as np
from openwakeword.model import Model

# Un modèle openWakeWord = un nom. Par défaut le `hey_jarvis` pré-entraîné (l'assistant
# s'appelle déjà « le Jarvis »), prouvé sur notre infra au POC S41. Le palier payant S43
# remplacera ce nom par un modèle entraîné sur la marque du client (même mécanique).
MOT_DEFAUT = os.getenv("WAKEWORD_MODELE", "hey_jarvis_v0.1")
SEUIL_DEFAUT = float(os.getenv("WAKEWORD_SEUIL", "0.5"))
PAS = 1280  # échantillons par appel à predict (80 ms @ 16 kHz) — imposé par openWakeWord


class Detecteur:
    """Avale du PCM 16 kHz mono int16 et signale chaque réveil.

    Usage :
        d = Detecteur()
        for evt in d.alimenter(octets_pcm):
            ...  # evt = {"mot": ..., "score": ...}
    """

    def __init__(self, mot: str = MOT_DEFAUT, seuil: float = SEUIL_DEFAUT,
                 refraction_pas: int = 12):
        self.mot = mot
        self.seuil = seuil
        # Nombre de fenêtres « muettes » imposées après un réveil (12 × 80 ms ≈ 1 s).
        self.refraction_pas = refraction_pas
        self._modele = Model(wakeword_models=[mot], inference_framework="onnx")
        self._tampon = np.empty(0, dtype=np.int16)
        self._reste = b""  # octet orphelin si un bloc WS coupe au milieu d'un int16
        self._refraction = 0

    def reset(self):
        """Repart à zéro (nouvelle connexion / nouveau flux)."""
        self._modele.reset()
        self._tampon = np.empty(0, dtype=np.int16)
        self._reste = b""
        self._refraction = 0

    def alimenter(self, pcm: bytes) -> list[dict]:
        """Ajoute un bloc d'octets PCM et renvoie la liste des réveils détectés.

        `pcm` = int16 little-endian (le format brut d'un flux micro 16 kHz mono).
        Un bloc WS peut tomber sur un nombre IMPAIR d'octets (coupé au milieu d'un
        échantillon) : on garde l'octet orphelin pour le prochain bloc. Un bloc peut
        aussi contenir 0, 1 ou plusieurs fenêtres de 80 ms ; on en traite autant que
        le tampon le permet, on garde le reste pour le prochain bloc."""
        brut = self._reste + pcm
        n_pair = len(brut) - (len(brut) % 2)
        self._reste = brut[n_pair:]
        bloc = np.frombuffer(brut[:n_pair], dtype=np.int16)
        if bloc.size:
            self._tampon = np.concatenate([self._tampon, bloc])
        reveils: list[dict] = []
        while self._tampon.size >= PAS:
            fenetre = self._tampon[:PAS]
            self._tampon = self._tampon[PAS:]
            pred = self._modele.predict(fenetre)
            score = float(pred[self.mot])
            if self._refraction > 0:
                self._refraction -= 1
                continue
            if score >= self.seuil:
                reveils.append({"mot": self.mot, "score": round(score, 4)})
                self._refraction = self.refraction_pas
        return reveils
