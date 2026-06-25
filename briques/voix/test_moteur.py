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


def _faux(nom, octets):
    class Faux:
        def disponible(self):
            return True

        async def synthetiser(self, texte, voix, langue, format):
            return octets, "ogg"
    Faux.nom = nom
    return Faux()


def test_routage_lecture_par_longueur(monkeypatch, tmp_path):
    # Deux moteurs dispo : un de conversation, un de lecture. Seuil bas pour le test.
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    monkeypatch.setenv("VOIX_SEUIL_LECTURE", "50")
    monkeypatch.setitem(F.REGISTRE, "convx", _faux("convx", b"CONV"))
    monkeypatch.setitem(F.REGISTRE, "lectx", _faux("lectx", b"LECT"))
    monkeypatch.setenv("VOIX_PROVIDERS", "convx,lectx")
    import reglages
    reglages.definir_moteur("lectx", "lecture")

    court = _run(moteur.synthetiser("Bonjour"))                 # < 50 → conversation
    assert court["backend"] == "convx"

    long = _run(moteur.synthetiser("x" * 80))                  # ≥ 50 → lecture
    assert long["backend"] == "lectx"


def test_usage_force_outrepasse_la_longueur(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    monkeypatch.setenv("VOIX_SEUIL_LECTURE", "50")
    monkeypatch.setitem(F.REGISTRE, "convx", _faux("convx", b"CONV"))
    monkeypatch.setitem(F.REGISTRE, "lectx", _faux("lectx", b"LECT"))
    monkeypatch.setenv("VOIX_PROVIDERS", "convx,lectx")
    import reglages
    reglages.definir_moteur("lectx", "lecture")
    # Texte court mais usage=lecture forcé → voix de lecture quand même.
    res = _run(moteur.synthetiser("Salut", usage="lecture"))
    assert res["backend"] == "lectx"


def test_lecture_repli_si_moteur_lecture_absent(monkeypatch, tmp_path):
    # Texte long mais AUCUNE voix de lecture choisie → on reste sur la conversation (honnête).
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    monkeypatch.setenv("VOIX_SEUIL_LECTURE", "50")
    monkeypatch.setitem(F.REGISTRE, "convx", _faux("convx", b"CONV"))
    monkeypatch.setenv("VOIX_PROVIDERS", "convx")
    res = _run(moteur.synthetiser("x" * 80))
    assert res["backend"] == "convx"


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
