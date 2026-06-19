"""Tests du moteur TTS : placeholder honnête, forçage, succès, repli (hors réseau)."""
import asyncio

import fournisseurs as F
import moteur


def _run(coro):
    return asyncio.run(coro)


def test_texte_vide_placeholder():
    res = _run(moteur.synthetiser("   "))
    assert res["place_holder"] is True and res["audio"] is None


def test_aucun_fournisseur_placeholder_honnete():
    # conftest : rien de configuré → pas d'audio, note explicite, JAMAIS de fausse voix.
    res = _run(moteur.synthetiser("Bonjour"))
    assert res["place_holder"] is True
    assert res["audio"] is None and res["backend"] == "placeholder"
    assert "Aucun moteur" in res["note"]


def test_forcage_fournisseur_indisponible():
    res = _run(moteur.synthetiser("Bonjour", fournisseur="openai"))
    assert res["place_holder"] is True and "openai" in res["note"]


def test_succes_via_fournisseur(monkeypatch):
    class Faux:
        nom = "faux"

        def disponible(self):
            return True

        async def synthetiser(self, texte, voix, langue, format):
            assert texte == "Bonjour"
            return b"OCTETS-AUDIO", "ogg"

    monkeypatch.setitem(F.REGISTRE, "faux", Faux())
    monkeypatch.setenv("VOIX_PROVIDERS", "faux")
    res = _run(moteur.synthetiser("Bonjour"))
    assert res["place_holder"] is False
    assert res["audio"] == b"OCTETS-AUDIO" and res["format"] == "ogg"
    assert res["backend"] == "faux"


def test_repli_si_fournisseur_leve(monkeypatch):
    class Casse:
        nom = "casse"

        def disponible(self):
            return True

        async def synthetiser(self, *a):
            raise RuntimeError("boom")

    monkeypatch.setitem(F.REGISTRE, "casse", Casse())
    monkeypatch.setenv("VOIX_PROVIDERS", "casse")
    res = _run(moteur.synthetiser("Bonjour"))
    assert res["place_holder"] is True
    assert "casse" in res.get("erreurs", {})
