"""Tests — orchestrateur moteur.py (sélection de fournisseur + repli honnête).

Le mode placeholder doit produire un vrai fichier servable et l'ANNONCER honnêtement
(`place_holder: True`) ; jamais faire passer un placeholder pour une vraie vidéo. La
sélection suit les fournisseurs DISPONIBLES (mockés ici, aucun réseau).
"""
import asyncio

import fournisseurs
import moteur

# Conteneur MP4 plausible : « ....ftypisom » (octets magiques ISO-BMFF en offset 4).
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 24
WEBM = b"\x1aE\xdf\xa3" + b"\x00" * 28


def test_placeholder_quand_aucun_fournisseur(monkeypatch):
    monkeypatch.setattr(fournisseurs, "disponibles", lambda: [])
    res = asyncio.run(moteur.generer("un héros qui dégaine au clair de lune"))
    assert res["place_holder"] is True
    assert res["backend"] == "placeholder"
    assert res["url"].startswith("/fichiers/")
    nom = res["url"].split("/")[-1]
    fichier = moteur.VIDEOS_DIR / nom
    assert fichier.is_file() and fichier.suffix == ".svg"
    assert "moteur" in fichier.read_text(encoding="utf-8").lower()


def test_placeholder_echappe_le_prompt(monkeypatch):
    monkeypatch.setattr(fournisseurs, "disponibles", lambda: [])
    res = asyncio.run(moteur.generer("<script>alert(1)</script>"))
    contenu = (moteur.VIDEOS_DIR / res["url"].split("/")[-1]).read_text(encoding="utf-8")
    assert "<script>alert" not in contenu        # échappé
    assert "&lt;script&gt;" in contenu


def test_premier_fournisseur_qui_repond_gagne(monkeypatch):
    """Deux fournisseurs dispo : le 1er échoue, on bascule sur le 2e — sa vidéo est servie."""
    class KO:
        async def generer(self, *a):
            raise RuntimeError("clé invalide")

    class OK:
        async def generer(self, *a):
            return MP4

    monkeypatch.setattr(fournisseurs, "disponibles", lambda: ["fal", "replicate"])
    monkeypatch.setattr(fournisseurs, "REGISTRE", {"fal": KO(), "replicate": OK()})
    res = asyncio.run(moteur.generer("un dragon"))
    assert res["place_holder"] is False
    assert res["backend"] == "replicate"         # le 1er a échoué, le 2e a rendu
    assert res["url"].endswith(".mp4")
    assert (moteur.VIDEOS_DIR / res["url"].split("/")[-1]).read_bytes() == MP4


def test_tous_echouent_placeholder_avec_erreurs(monkeypatch):
    class KO:
        async def generer(self, *a):
            raise RuntimeError("boum")

    monkeypatch.setattr(fournisseurs, "disponibles", lambda: ["fal", "luma"])
    monkeypatch.setattr(fournisseurs, "REGISTRE", {"fal": KO(), "luma": KO()})
    res = asyncio.run(moteur.generer("x"))
    assert res["place_holder"] is True
    assert set(res["erreurs"]) == {"fal", "luma"}       # on dit lesquels ont été essayés


def test_aucune_video_renvoyee_compte_comme_echec(monkeypatch):
    class Vide:
        async def generer(self, *a):
            return None                                  # job sans vidéo exploitable

    monkeypatch.setattr(fournisseurs, "disponibles", lambda: ["gateway"])
    monkeypatch.setattr(fournisseurs, "REGISTRE", {"gateway": Vide()})
    res = asyncio.run(moteur.generer("x"))
    assert res["place_holder"] is True
    assert res["erreurs"]["gateway"] == "aucune vidéo renvoyée"


def test_forcage_fournisseur(monkeypatch):
    class OK:
        async def generer(self, *a):
            return MP4

    reg = {"fal": OK(), "luma": OK()}
    reg["fal"].disponible = lambda: True
    reg["luma"].disponible = lambda: True
    monkeypatch.setattr(fournisseurs, "REGISTRE", reg)
    # même si l'ordre préfère fal, on force luma
    res = asyncio.run(moteur.generer("x", fournisseur="luma"))
    assert res["backend"] == "luma" and res["place_holder"] is False


def test_forcage_fournisseur_indisponible_placeholder(monkeypatch):
    reg = {"luma": fournisseurs.Luma()}                  # pas de clé → indisponible
    monkeypatch.setattr(fournisseurs, "REGISTRE", reg)
    res = asyncio.run(moteur.generer("x", fournisseur="luma"))
    assert res["place_holder"] is True


def test_extension_selon_les_octets():
    assert moteur._ext(b"\x00\x00\x00\x18ftypisom") == "mp4"
    assert moteur._ext(b"\x00\x00\x00\x14ftypqt  ") == "mov"
    assert moteur._ext(b"\x1aE\xdf\xa3....") == "webm"
    assert moteur._ext(b"???") == "mp4"                  # défaut prudent
