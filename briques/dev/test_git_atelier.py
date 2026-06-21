"""Le filet : worktree isolé, diff, abandon — sur un VRAI dépôt git jetable (cf. conftest).

Ces tests prouvent l'invariant central de l'incrément 1 : on produit un diff sans JAMAIS
toucher la branche de prod (`main`)."""
import os
import subprocess

import git_atelier
import pytest


def _sur_main(*args):
    return subprocess.run(["git", "-C", git_atelier.REPO, *args],
                          capture_output=True, text=True).stdout


def test_est_un_depot():
    assert git_atelier.est_un_depot()


def test_ouvrir_chantier_cree_worktree_et_branche():
    chemin = git_atelier.ouvrir_chantier("dev/test-ouvrir")
    assert os.path.isdir(chemin)
    branches = _sur_main("branch", "--list", "dev/test-ouvrir")
    assert "dev/test-ouvrir" in branches
    git_atelier.jeter_chantier("dev/test-ouvrir")


def test_refus_branche_protegee():
    with pytest.raises(git_atelier.ErreurGit):
        git_atelier.ouvrir_chantier("main")


def test_diff_visible_et_main_intact():
    chemin = git_atelier.ouvrir_chantier("dev/test-diff")
    # On modifie DANS le worktree et on commite sur SA branche.
    with open(os.path.join(chemin, "nouveau.txt"), "w") as f:
        f.write("ajout dans le worktree\n")
    subprocess.run(["git", "-C", chemin, "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", chemin, "commit", "-m", "ajout"], check=True, capture_output=True)

    diff = git_atelier.diff_chantier("dev/test-diff")
    assert "nouveau.txt" in diff and "ajout dans le worktree" in diff
    stats = git_atelier.resume_diff("dev/test-diff")
    assert "nouveau.txt" in stats["fichiers"] and stats["ajouts"] >= 1

    # La prod (main) n'a pas bougé : le fichier n'y existe pas.
    assert "nouveau.txt" not in _sur_main("ls-tree", "--name-only", "main")
    git_atelier.jeter_chantier("dev/test-diff")


def test_jeter_est_idempotent():
    git_atelier.ouvrir_chantier("dev/test-jeter")
    git_atelier.jeter_chantier("dev/test-jeter")
    git_atelier.jeter_chantier("dev/test-jeter")  # 2e fois : pas d'erreur
    assert "dev/test-jeter" not in _sur_main("branch", "--list", "dev/test-jeter")
