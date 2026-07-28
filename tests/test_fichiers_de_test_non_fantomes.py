"""Filet « pas de fichier de test fantôme » (2026-07-28).

Un fichier nommé `test_*.py` qui ne déclare **aucun** test pytest est pire que pas de
fichier : il compte dans l'inventaire, il rassure à la relecture, et il ne protège rien.

Le parc en portait **8**, découverts en soldant la dette de S213 :

  • six dans `briques/generateur/` (`test_appliquer`, `test_balayage`,
    `test_client_provisioning`, `test_langues`, `test_pont_crm`, `test_revue`) et un dans
    `briques/forge/` (`test_propagation_identite`) — des scripts autonomes (`def run()` +
    `if __name__ == "__main__"`) lancés à la main au moment de leur sprint, puis plus
    jamais : ni `make test-briques` ni `scripts/tests_briques.sh` n'exécutent autre chose
    que pytest. **34 + 3 scénarios invisibles**, tous verts une fois convertis — donc de la
    couverture réelle, simplement débranchée.
  • un dans `core/` (`test_langue.py`), cas plus sournois : ses assertions étaient au
    niveau module, donc pytest les exécutait bien à l'import — mais le fichier déclarait 0
    test, un échec sortait en *erreur de collecte* au lieu d'un test rouge nommé, et la
    première assertion en échec masquait les 23 suivantes.

Ce filet est volontairement bête : il compte les `def test_` / `class Test`. Il ne juge pas
la qualité d'un test, seulement qu'il existe et que pytest le verra.
"""
import ast
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
DOSSIERS = ("briques", "core", "tests", "shared")
EXCLUS = {"node_modules", ".venv", "venv", "__pycache__", ".dev-ateliers", ".worktrees",
          ".claude", "apps_exportees"}


def _fichiers_de_test():
    trouves = []
    for dossier in DOSSIERS:
        base = RACINE / dossier
        if not base.is_dir():
            continue
        for chemin in base.rglob("test_*.py"):
            if EXCLUS & set(chemin.parts):
                continue
            trouves.append(chemin)
    return sorted(trouves)


def _declare_des_tests(chemin: Path) -> bool:
    """Vrai si le fichier déclare au moins un test que pytest collectera.

    On lit l'AST plutôt que le texte : un `def test_` dans une chaîne, un commentaire ou un
    nom de variable ne compte pas — c'est exactement ce qu'un grep laisserait passer."""
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError) as e:
        pytest.fail(f"{chemin.relative_to(RACINE)} : illisible ({e})")
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                noeud.name.startswith("test"):
            return True
        if isinstance(noeud, ast.ClassDef) and noeud.name.startswith("Test"):
            return True
    return False


def test_il_y_a_bien_des_fichiers_a_verifier():
    """Garde-fou du garde-fou : un glob cassé rendrait ce filet vert et vide."""
    assert len(_fichiers_de_test()) > 100, "la collecte des fichiers de test a dû casser"


@pytest.mark.parametrize("chemin", _fichiers_de_test(),
                         ids=lambda p: str(p.relative_to(RACINE)))
def test_un_fichier_test_declare_au_moins_un_test(chemin):
    assert _declare_des_tests(chemin), (
        f"{chemin.relative_to(RACINE)} ne déclare aucun test pytest. Si c'est un script de "
        f"preuve autonome (`def run()` + `__main__`), il n'est lancé par AUCUN filet : "
        f"convertis-le en tests pytest, ou renomme-le pour qu'il cesse de se faire passer "
        f"pour un test (`preuve_*.py`, `scripts/`).")
