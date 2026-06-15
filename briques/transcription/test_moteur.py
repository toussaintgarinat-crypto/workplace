"""Tests de l'orchestrateur : repli HONNÊTE, forçage, succès, agrégation d'erreurs."""
import asyncio

import fournisseurs
import moteur


def _run(coro):
    return asyncio.run(coro)


class _FauxOK:
    """Fournisseur factice qui transcrit toujours (pour tester le chemin nominal)."""
    nom = "faux"

    def disponible(self):
        return True

    async def transcrire(self, audio, nom_fichier, langue, diarisation):
        return {"texte": "ceci est un test", "segments": [{"debut": 0, "fin": 1,
                "texte": "ceci est un test"}], "langue": langue or "fr",
                "diarisation": diarisation}


class _FauxKO:
    nom = "casse"

    def disponible(self):
        return True

    async def transcrire(self, *a):
        raise RuntimeError("boum")


def test_audio_vide_repli_honnete():
    res = _run(moteur.transcrire(b""))
    assert res["place_holder"] is True
    assert res["texte"] == ""


def test_aucun_fournisseur_repli_honnete():
    # conftest : aucun moteur → placeholder honnête, jamais de texte inventé.
    res = _run(moteur.transcrire(b"des octets audio"))
    assert res["place_holder"] is True
    assert res["texte"] == ""
    assert res["backend"] == "placeholder"
    assert "Aucun moteur" in res["note"]


def test_forcage_fournisseur_indisponible():
    res = _run(moteur.transcrire(b"audio", fournisseur="openai"))
    assert res["place_holder"] is True
    assert "openai" in res["note"]


def test_succes_avec_fournisseur(monkeypatch):
    monkeypatch.setitem(fournisseurs.REGISTRE, "faux", _FauxOK())
    monkeypatch.setattr(fournisseurs, "disponibles", lambda: ["faux"])
    res = _run(moteur.transcrire(b"audio", langue="fr", diarisation=True))
    assert res["place_holder"] is False
    assert res["backend"] == "faux"
    assert res["texte"] == "ceci est un test"
    assert res["diarisation"] is True


def test_erreur_fournisseur_agregee(monkeypatch):
    monkeypatch.setitem(fournisseurs.REGISTRE, "casse", _FauxKO())
    monkeypatch.setattr(fournisseurs, "disponibles", lambda: ["casse"])
    res = _run(moteur.transcrire(b"audio"))
    assert res["place_holder"] is True
    assert "casse" in res["erreurs"]
    assert "boum" in res["erreurs"]["casse"]


def test_premier_qui_repond_gagne(monkeypatch):
    monkeypatch.setitem(fournisseurs.REGISTRE, "casse", _FauxKO())
    monkeypatch.setitem(fournisseurs.REGISTRE, "faux", _FauxOK())
    monkeypatch.setattr(fournisseurs, "disponibles", lambda: ["casse", "faux"])
    res = _run(moteur.transcrire(b"audio"))
    # le KO échoue, on bascule sur le suivant : pas de placeholder.
    assert res["place_holder"] is False
    assert res["backend"] == "faux"
