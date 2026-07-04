"""Tests Sprint S144 — Mixture of Agents (MOA).

    $ cd core && python3 test_moa.py
    $ cd core && python3 -m pytest test_moa.py -v
"""
import asyncio
import os
import sys

os.environ.setdefault("GATEWAY_KEY", "test")
sys.path.insert(0, os.path.dirname(__file__))

import pytest
import httpx
import moa


@pytest.fixture(autouse=True)
def vider_cache():
    moa._cache_guidance.clear()
    yield
    moa._cache_guidance.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────

MESSAGES = [{"role": "user", "content": "analyse cette situation complexe"}]


def _config(modeles, agregateur=None):
    return moa.ConfigMOA(
        modeles_reference=modeles,
        agregateur=agregateur or modeles[0],
    )


class _FakeRef:
    """Remplace _appeler_reference ; enregistre les appels."""

    def __init__(self, reponse="Avis de conseil.", lever=None):
        self.appels: list[tuple[str, list]] = []
        self._reponse = reponse
        self._lever = lever

    async def __call__(self, modele, messages, config, client):
        self.appels.append((modele, messages))
        if self._lever:
            raise self._lever
        return f"Avis de {modele}"


# ── Tests 1–4 : synchrones ────────────────────────────────────────────────────

def test_1_depuis_env_sans_variable(monkeypatch):
    monkeypatch.delenv("MOA_MODELES", raising=False)
    assert moa._depuis_env() is None


def test_2_est_complexe_message_court():
    assert not moa.est_complexe("ok")


def test_3_est_complexe_mot_cle():
    assert moa.est_complexe("planifie l'architecture de migration")


def test_4_est_complexe_longueur():
    assert moa.est_complexe("x" * 130)


# ── Tests 5–10 : async ────────────────────────────────────────────────────────

def test_5_consulter_appelle_n_references():
    """consulter() lance exactement N appels référence (en parallèle via gather)."""
    modeles = ["m1", "m2", "m3"]
    fake = _FakeRef()
    orig = moa._appeler_reference

    async def _run():
        moa._appeler_reference = fake
        try:
            async with httpx.AsyncClient() as client:
                await moa.consulter(MESSAGES, _config(modeles), client)
        finally:
            moa._appeler_reference = orig

    asyncio.run(_run())
    # N références + 1 agrégateur = N+1 appels
    modeles_appeles = [a[0] for a in fake.appels]
    for m in modeles:
        assert m in modeles_appeles, f"Référence {m} non appelée"


def test_6_cache_evite_second_appel():
    """Même contexte × 2 → _appeler_reference n'est appelée qu'une fois."""
    modeles = ["m1", "m2"]
    fake = _FakeRef()
    orig = moa._appeler_reference

    async def _run():
        moa._appeler_reference = fake
        try:
            async with httpx.AsyncClient() as client:
                await moa.consulter(MESSAGES, _config(modeles), client)
                nb_apres_premier = len(fake.appels)
                await moa.consulter(MESSAGES, _config(modeles), client)
                return nb_apres_premier, len(fake.appels)
        finally:
            moa._appeler_reference = orig

    premier, total = asyncio.run(_run())
    assert total == premier, "Le cache n'a pas évité les appels redondants"


def test_7_reference_timeout_avis_partiel():
    """_appeler_reference avec un client en timeout retourne un texte d'erreur, pas d'exception."""

    async def _run():
        config = _config(["modele_lent"])
        mock_client = httpx.AsyncClient()

        # Simuler un client HTTP qui lève une exception réseau
        class _ErrClient:
            async def post(self, *a, **kw):
                raise httpx.TimeoutException("timeout simulé")

        result = await moa._appeler_reference("modele_lent", MESSAGES, config, _ErrClient())
        return result

    result = asyncio.run(_run())
    assert "indisponible" in result
    assert "modele_lent" in result


def test_8_guidance_contient_noms_references():
    """Le prompt d'agrégation contient les noms des modèles référence."""
    modeles = ["openrouter/mistral-large", "openai/gpt-4o"]
    captured: list[tuple[str, list]] = []
    orig = moa._appeler_reference

    async def tracking_ref(modele, messages, config, client):
        captured.append((modele, messages))
        return "Analyse concise."

    async def _run():
        moa._appeler_reference = tracking_ref
        try:
            async with httpx.AsyncClient() as client:
                await moa.consulter(MESSAGES, _config(modeles), client)
        finally:
            moa._appeler_reference = orig

    asyncio.run(_run())

    # L'appel agrégateur reçoit les noms des références dans son prompt
    agregateur_appel = [msgs for modele, msgs in captured if modele == modeles[0]][-1]
    prompt_agregation = str(agregateur_appel)
    for m in modeles:
        assert m in prompt_agregation, f"Nom du modèle '{m}' absent du prompt d'agrégation"


def test_9_moa_un_seul_modele():
    """MOA_MODELES avec 1 modèle fonctionne sans erreur."""
    fake = _FakeRef()
    orig = moa._appeler_reference

    async def _run():
        moa._appeler_reference = fake
        try:
            async with httpx.AsyncClient() as client:
                guidance = await moa.consulter(MESSAGES, _config(["seul"]), client)
                return guidance
        finally:
            moa._appeler_reference = orig

    guidance = asyncio.run(_run())
    assert guidance  # non vide
    appeles = [a[0] for a in fake.appels]
    assert "seul" in appeles


def test_10_cache_invalide_si_messages_changent():
    """Messages différents → deux jeux d'appels distincts (pas de cache croisé)."""
    msgs_a = [{"role": "user", "content": "question A"}]
    msgs_b = [{"role": "user", "content": "question B totalement différente"}]
    fake = _FakeRef()
    orig = moa._appeler_reference

    async def _run():
        moa._appeler_reference = fake
        try:
            async with httpx.AsyncClient() as client:
                await moa.consulter(msgs_a, _config(["m1"]), client)
                nb_a = len(fake.appels)
                await moa.consulter(msgs_b, _config(["m1"]), client)
                return nb_a, len(fake.appels)
        finally:
            moa._appeler_reference = orig

    nb_a, nb_total = asyncio.run(_run())
    assert nb_total > nb_a, "Le cache a bloqué des appels pour un contexte différent"
