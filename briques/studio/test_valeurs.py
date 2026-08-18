"""Tests — valeur suggérée par le Script Doctor sur un chapitre (V1 saga familiale).

Calqué sur `test_cible_lecture.py` : `_demander` est monkeypatché, jamais de vrai appel
réseau. Repli honnête (`None`) sur tout échec — ne doit jamais bloquer la création d'un
chapitre."""
import asyncio

import studio as A


def _run(coro):
    return asyncio.run(coro)


def test_valeurs_est_une_liste_fixe_de_16():
    assert len(A.VALEURS) == 16
    assert "courage" in A.VALEURS
    assert "empathie" in A.VALEURS


def test_suggerer_valeur_retourne_une_cle_valide(monkeypatch):
    async def fake_demander(ag, tache):
        return '{"valeur":"courage"}'
    monkeypatch.setattr(A, "_demander", fake_demander)
    assert _run(A._suggerer_valeur("Un texte quelconque.")) == "courage"


def test_suggerer_valeur_repli_none_si_cle_hors_liste(monkeypatch):
    async def fake_demander(ag, tache):
        return '{"valeur":"inexistante"}'
    monkeypatch.setattr(A, "_demander", fake_demander)
    assert _run(A._suggerer_valeur("Un texte.")) is None


def test_suggerer_valeur_repli_none_si_llm_echoue(monkeypatch):
    async def fake_demander(ag, tache):
        raise RuntimeError("gateway indisponible")
    monkeypatch.setattr(A, "_demander", fake_demander)
    assert _run(A._suggerer_valeur("Un texte.")) is None


def test_suggerer_valeur_texte_vide_ne_sollicite_pas_le_llm(monkeypatch):
    appels = []

    async def fake_demander(ag, tache):
        appels.append(tache)
        return '{"valeur":"courage"}'
    monkeypatch.setattr(A, "_demander", fake_demander)
    assert _run(A._suggerer_valeur("")) is None
    assert appels == []
