"""Tests — `_adapter_cible` : adaptation de REGISTRE (vocabulaire/longueur/intensité) par
tranche d'âge, à la lecture, calquée sur `_traduire` (repli honnête, jamais de blocage).
Ne teste JAMAIS un vrai appel réseau : `_gateway_answer` est monkeypatché (S51/S231)."""
import asyncio

import studio as A


def _run(coro):
    return asyncio.run(coro)


def test_texte_vide_no_op():
    out, ok = _run(A._adapter_cible("", "7-9"))
    assert out == "" and ok is True


def test_cible_inconnue_no_op():
    out, ok = _run(A._adapter_cible("Bonjour le monde.", "pas-une-cible"))
    assert out == "Bonjour le monde." and ok is True


def test_adaptation_succes(monkeypatch):
    async def fake_gw(url, model, systeme, tache):
        return "Version simplifiée pour tout-petit."
    monkeypatch.setattr(A, "_gateway_answer", fake_gw)
    out, ok = _run(A._adapter_cible("Une histoire un peu complexe pour un tout-petit.", "0-3"))
    assert ok is True
    assert out == "Version simplifiée pour tout-petit."


def test_adaptation_reponse_vide_repli(monkeypatch):
    async def fake_gw(*a):
        return "   "
    monkeypatch.setattr(A, "_gateway_answer", fake_gw)
    out, ok = _run(A._adapter_cible("Texte original.", "7-9"))
    assert ok is False and out == "Texte original."


def test_adaptation_longueur_incoherente_repli(monkeypatch):
    # Réponse ridiculement plus courte que l'original → garde-fou anti-troncature.
    async def fake_gw(*a):
        return "Court."
    monkeypatch.setattr(A, "_gateway_answer", fake_gw)
    original = "Un texte de référence assez long pour que le ratio de longueur déclenche le garde-fou anti-troncature de l'adaptation."
    out, ok = _run(A._adapter_cible(original, "7-9"))
    assert ok is False and out == original


def test_adaptation_gateway_injoignable_repli(monkeypatch):
    async def fake_gw(*a):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(A, "_gateway_answer", fake_gw)
    out, ok = _run(A._adapter_cible("Texte original.", "7-9"))
    assert ok is False and out == "Texte original."
