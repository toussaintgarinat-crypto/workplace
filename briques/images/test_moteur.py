"""Tests — orchestrateur moteur.py (sélection de fournisseur + repli honnête).

Le mode placeholder doit produire un vrai fichier servable et l'ANNONCER honnêtement
(`place_holder: True`) ; jamais faire passer un placeholder pour une image réelle. La
sélection suit les fournisseurs DISPONIBLES (mockés ici, aucun réseau).
"""
import asyncio

import fournisseurs
import moteur

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32          # entête PNG plausible


def test_placeholder_quand_aucun_fournisseur(monkeypatch):
    monkeypatch.setattr(fournisseurs, "disponibles", lambda: [])
    res = asyncio.run(moteur.generer("un héros au clair de lune"))
    assert res["place_holder"] is True
    assert res["backend"] == "placeholder"
    assert res["url"].startswith("/fichiers/")
    nom = res["url"].split("/")[-1]
    fichier = moteur.IMAGES_DIR / nom
    assert fichier.is_file() and fichier.suffix == ".svg"
    assert "moteur" in fichier.read_text(encoding="utf-8").lower()


def test_placeholder_echappe_le_prompt(monkeypatch):
    monkeypatch.setattr(fournisseurs, "disponibles", lambda: [])
    res = asyncio.run(moteur.generer("<script>alert(1)</script>"))
    contenu = (moteur.IMAGES_DIR / res["url"].split("/")[-1]).read_text(encoding="utf-8")
    assert "<script>alert" not in contenu        # échappé
    assert "&lt;script&gt;" in contenu


def test_premier_fournisseur_qui_repond_gagne(monkeypatch):
    """Deux fournisseurs dispo : le 1er échoue, on bascule sur le 2e — son image est servie."""
    class KO:
        async def generer(self, *a):
            raise RuntimeError("clé invalide")

    class OK:
        async def generer(self, *a):
            return PNG

    monkeypatch.setattr(fournisseurs, "disponibles", lambda: ["fal", "nanobanana"])
    monkeypatch.setattr(fournisseurs, "REGISTRE", {"fal": KO(), "nanobanana": OK()})
    res = asyncio.run(moteur.generer("un dragon"))
    assert res["place_holder"] is False
    assert res["backend"] == "nanobanana"        # le 1er a échoué, le 2e a rendu
    assert res["url"].endswith(".png")
    assert (moteur.IMAGES_DIR / res["url"].split("/")[-1]).read_bytes() == PNG


def test_tous_echouent_placeholder_avec_erreurs(monkeypatch):
    class KO:
        async def generer(self, *a):
            raise RuntimeError("boum")

    monkeypatch.setattr(fournisseurs, "disponibles", lambda: ["fal", "openai"])
    monkeypatch.setattr(fournisseurs, "REGISTRE", {"fal": KO(), "openai": KO()})
    res = asyncio.run(moteur.generer("x"))
    assert res["place_holder"] is True
    assert set(res["erreurs"]) == {"fal", "openai"}     # on dit lesquels ont été essayés


def test_forcage_fournisseur(monkeypatch):
    class OK:
        async def generer(self, *a):
            return PNG

    reg = {"fal": OK(), "openai": OK()}
    reg["fal"].disponible = lambda: True
    reg["openai"].disponible = lambda: True
    monkeypatch.setattr(fournisseurs, "REGISTRE", reg)
    # même si l'ordre préfère fal, on force openai
    res = asyncio.run(moteur.generer("x", fournisseur="openai"))
    assert res["backend"] == "openai" and res["place_holder"] is False


def test_forcage_fournisseur_indisponible_placeholder(monkeypatch):
    reg = {"openai": fournisseurs.OpenAI()}              # pas de clé → indisponible
    monkeypatch.setattr(fournisseurs, "REGISTRE", reg)
    res = asyncio.run(moteur.generer("x", fournisseur="openai"))
    assert res["place_holder"] is True


def test_extension_selon_les_octets():
    assert moteur._ext(b"\x89PNG\r\n\x1a\n") == "png"
    assert moteur._ext(b"\xff\xd8\xff\xe0") == "jpg"
    assert moteur._ext(b"RIFF\x00\x00\x00\x00WEBP") == "webp"
    assert moteur._ext(b"GIF89a....") == "gif"
    assert moteur._ext(b"???") == "png"                  # défaut prudent


def test_modele_restitue_quand_fournisseur_gateway(monkeypatch):
    class OK:
        def disponible(self):
            return True
        async def generer(self, *a):
            return PNG
    monkeypatch.setattr(fournisseurs, "REGISTRE", {"gateway": OK()})
    res = asyncio.run(moteur.generer("x", fournisseur="gateway", modele="openai/gpt-5-image"))
    assert res["modele"] == "openai/gpt-5-image"


def test_modele_absent_hors_gateway(monkeypatch):
    class OK:
        def disponible(self):
            return True
        async def generer(self, *a):
            return PNG
    monkeypatch.setattr(fournisseurs, "REGISTRE", {"fal": OK()})
    res = asyncio.run(moteur.generer("x", fournisseur="fal", modele="ignore-moi"))
    assert res["modele"] is None


def test_modele_absent_par_defaut():
    res = asyncio.run(moteur.generer("x"))  # aucun fournisseur configuré → placeholder
    assert "modele" not in res or res.get("modele") is None
