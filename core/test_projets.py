"""Projets de l'assistant (façon Claude Projects / Perplexity Spaces).

On vérifie : créer/lister/modifier/supprimer un projet, les instructions personnalisées, le
contexte complet (instructions + rappel des documents rattachés), et le bornage doux des
champs. Autonome : side-car en tmp.
    $ cd core && python3 test_projets.py
"""
import os
import tempfile

os.environ["PROJETS_PATH"] = os.path.join(tempfile.mkdtemp(), "projets.json")

import projets  # noqa: E402


def _reset():
    if projets.CHEMIN.exists():
        projets.CHEMIN.unlink()


def test_creer_et_lister():
    _reset()
    p = projets.creer("Refonte resto", instructions="Sois concis.")
    assert p["nom"] == "Refonte resto" and p["instructions"] == "Sois concis."
    assert p["id"] and p["couleur"]
    liste = projets.lister()
    assert len(liste) == 1 and liste[0]["id"] == p["id"]


def test_nom_vide_a_un_repli():
    _reset()
    p = projets.creer("   ")
    assert p["nom"] == "Projet sans nom"


def test_modifier_champs_partiels():
    _reset()
    p = projets.creer("A", instructions="vieux")
    m = projets.modifier(p["id"], instructions="neuf")
    assert m["instructions"] == "neuf" and m["nom"] == "A"  # nom inchangé
    assert projets.modifier("inconnu", nom="X") is None


def test_instructions_et_contexte():
    _reset()
    p = projets.creer("Resto", instructions="Tu m'aides sur la brique restaurant.",
                      documents=[{"type": "projet", "nom": "Carte 2024"}])
    assert projets.instructions_de(p["id"]) == "Tu m'aides sur la brique restaurant."
    ctx = projets.contexte_de(p["id"])
    assert "brique restaurant" in ctx
    assert "Carte 2024" in ctx and "chercher_documents" in ctx
    assert projets.contexte_de(None) == ""
    assert projets.instructions_de("absent") == ""


def test_contexte_sans_docs_ni_instructions():
    _reset()
    p = projets.creer("Vide")
    assert projets.contexte_de(p["id"]) == ""


def test_supprimer():
    _reset()
    p = projets.creer("X")
    assert projets.supprimer(p["id"]) is True
    assert projets.lister() == []
    assert projets.supprimer(p["id"]) is False


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
