"""Config de test : un VRAI dépôt git temporaire + worktrees isolés, AVANT import des modules.

On ne touche jamais au dépôt Workplace réel pendant les tests : `DEV_REPO` pointe sur un dépôt
jetable créé dans un tmpdir, et `DEV_ATELIERS`/`DEV_DB` vivent aussi en temporaire.
"""
import os
import subprocess
import tempfile

import pytest

_racine = tempfile.mkdtemp(prefix="dev-atelier-tests-")
_repo = os.path.join(_racine, "depot")
os.environ["DEV_REPO"] = _repo
os.environ["DEV_ATELIERS"] = os.path.join(_racine, "ateliers")
os.environ["DEV_TRACES"] = os.path.join(_racine, "traces")
os.environ["DEV_DB"] = os.path.join(_racine, "chantiers.json")
os.environ.pop("DEV_KEY", None)  # atelier ouvert en test
# IDE SpearCode (porté de Gungnir) : workspace + données en temporaire (jamais le vrai dépôt).
os.environ["DEV_IDE_WORKSPACE"] = os.path.join(_racine, "ide-workspace")
os.environ["DEV_IDE_DATA"] = os.path.join(_racine, "ide-data")
# Pas de LLM en test : le plan BMAD (S88) retombe sur son squelette local, déterministe et
# hors-ligne (aucun appel réseau). La preuve LIVE avec vrai LLM se fait à part.
os.environ["GATEWAY_MODEL"] = ""


def _git(*args, cwd=_repo):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture(scope="session", autouse=True)
def depot_jetable():
    """Initialise un dépôt git minimal avec un commit sur `main` (la « prod » des tests)."""
    os.makedirs(_repo, exist_ok=True)
    _git("init", "-b", "main")
    _git("config", "user.email", "test@atelier.local")
    _git("config", "user.name", "Atelier Test")
    with open(os.path.join(_repo, "README.md"), "w") as f:
        f.write("# Projet de test\n")
    _git("add", "-A")
    _git("commit", "-m", "base prod")
    yield
