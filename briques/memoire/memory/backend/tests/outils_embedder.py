"""Embedder simulé pour les tests (S238).

Aucun test ne doit joindre un vrai Gateway. Par défaut l'embedder est EN PANNE (fixture
autouse du conftest) ; un test qui veut des vecteurs active l'embedder factice : un sac de
mots haché sur 384 dimensions, déterministe, avec quelques synonymes pour simuler une
proximité de sens que le lexical ne voit pas (« automobile » ≈ « voiture »).
"""
import hashlib
import math
import re

from app.llm.client import LLMClient

SYNONYMES_FACTICES = {"automobile": "voiture", "vehicule": "voiture", "véhicule": "voiture"}


def vecteur_factice(texte: str) -> list[float]:
    v = [0.0] * 384
    for mot in re.findall(r"\w+", texte.lower()):
        mot = SYNONYMES_FACTICES.get(mot, mot)
        v[int(hashlib.sha256(mot.encode()).hexdigest(), 16) % 384] += 1.0
    norme = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norme for x in v]


def activer_embedder_factice(monkeypatch) -> None:
    async def _embed(self, text: str) -> list[float]:
        return vecteur_factice(text)

    monkeypatch.setattr(LLMClient, "embed", _embed)


def couper_embedder(monkeypatch) -> None:
    async def _panne(self, text: str) -> list[float]:
        raise ConnectionError("Gateway injoignable (simulé)")

    monkeypatch.setattr(LLMClient, "embed", _panne)
