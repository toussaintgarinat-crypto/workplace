"""Catalogue des noms d'éveil (S43) — le **palier gratuit** des paliers commerciaux.

openWakeWord = *un modèle ONNX = un nom*. Le palier gratuit, c'est la liste des
modèles **réellement embarqués** dans l'image (pré-téléchargés au build, cf.
`Dockerfile`) que le client peut choisir sans rien entraîner.

Honnêteté (≠ marketing) : le plan parlait de « 5-6 noms ». openWakeWord ne livre que
**4 modèles qui sont des noms d'éveil** (`alexa`, `hey_jarvis`, `hey_mycroft`,
`hey_rhasspy`). `timer`/`weather`/`silero_vad`/`embedding`/`melspectrogram` ne sont
PAS des noms d'éveil (commandes ou modèles internes) — les présenter comme des choix
serait mentir. On expose donc 4 noms gratuits honnêtes ; au-delà = palier payant
(entraînement par marque, cf. `commandes.py`).

Module **pur** (aucune I/O, aucun réseau) → testable hors ligne.
"""
from __future__ import annotations

# Noms d'éveil pré-entraînés livrés avec la brique (modèles dans l'image).
# `modele` = identifiant openWakeWord (le fichier <modele>.onnx vit dans ses resources).
# `langue` = langue d'entraînement des voix Piper du modèle (anglais pour tous les
# pré-entraînés communautaires — d'où le palier payant pour un nom FR de marque).
CATALOGUE_GRATUIT: list[dict] = [
    {
        "modele": "hey_jarvis_v0.1",
        "label": "Hey Jarvis",
        "langue": "en",
        "defaut": True,
        "note": "Le défaut historique (l'assistant s'appelle « le Jarvis »), prouvé au POC S41.",
    },
    {
        "modele": "alexa_v0.1",
        "label": "Alexa",
        "langue": "en",
        "defaut": False,
        "note": "Pré-entraîné openWakeWord.",
    },
    {
        "modele": "hey_mycroft_v0.1",
        "label": "Hey Mycroft",
        "langue": "en",
        "defaut": False,
        "note": "Pré-entraîné openWakeWord.",
    },
    {
        "modele": "hey_rhasspy_v0.1",
        "label": "Hey Rhasspy",
        "langue": "en",
        "defaut": False,
        "note": "Pré-entraîné openWakeWord.",
    },
]

_MODELES_GRATUITS = {n["modele"] for n in CATALOGUE_GRATUIT}


def est_gratuit(modele: str) -> bool:
    """Vrai si `modele` est un nom du palier gratuit (modèle embarqué)."""
    return modele in _MODELES_GRATUITS


def nom_defaut() -> str:
    """Le modèle proposé par défaut (le seul marqué `defaut`)."""
    for n in CATALOGUE_GRATUIT:
        if n.get("defaut"):
            return n["modele"]
    return CATALOGUE_GRATUIT[0]["modele"]


def trouver(modele: str) -> dict | None:
    """Fiche catalogue d'un modèle gratuit, ou None s'il n'en est pas un."""
    for n in CATALOGUE_GRATUIT:
        if n["modele"] == modele:
            return n
    return None
