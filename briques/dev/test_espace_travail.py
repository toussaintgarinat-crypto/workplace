"""Seam à 3 rôles (veille deepseek-harness/Cordis, 4e et dernier chantier) : `EspaceTravail`
(Service Definition) doit pouvoir basculer local ↔ distant SANS toucher les consommateurs
(`main.py`). Ces tests prouvent :
  • `EspaceTravailLocal` délègue fidèlement à `git_atelier` (même filet, même invariant
    « prod jamais touchée » que `test_git_atelier.py`) ;
  • `EspaceTravailDistant` est un stub HONNÊTE (pas encore implémenté) : `disponible()` ment
    jamais (toujours False), et toute opération lève une erreur claire plutôt qu'un faux succès ;
  • `choisir_espace()` retombe sur Local si le nom demandé est indisponible ou inconnu — jamais
    de silence qui ferait croire qu'un sandbox distant a tourné.
"""
import os

import espace_travail
import git_atelier
import pytest


def _sur_main(*args):
    import subprocess
    return subprocess.run(["git", "-C", git_atelier.REPO, *args],
                          capture_output=True, text=True).stdout


# ── EspaceTravailLocal : délégation fidèle à git_atelier ────────────────────────

def test_local_disponible_reflete_git_atelier():
    espace = espace_travail.EspaceTravailLocal()
    assert espace.nom == "local"
    assert espace.disponible() == git_atelier.est_un_depot()


def test_local_ouvrir_diff_jeter_round_trip():
    espace = espace_travail.EspaceTravailLocal()
    chemin = espace.ouvrir("dev/test-espace-local")
    assert os.path.isdir(chemin)
    with open(os.path.join(chemin, "nouveau.txt"), "w") as f:
        f.write("ajout via le seam\n")
    import subprocess
    subprocess.run(["git", "-C", chemin, "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", chemin, "commit", "-m", "ajout"], check=True, capture_output=True)

    diff = espace.diff("dev/test-espace-local")
    assert "nouveau.txt" in diff
    stats = espace.resume_diff("dev/test-espace-local")
    assert "nouveau.txt" in stats["fichiers"]

    # Le filet tient : la prod (main) n'a jamais vu passer le fichier.
    assert "nouveau.txt" not in _sur_main("ls-tree", "--name-only", "main")
    espace.jeter("dev/test-espace-local")
    assert "dev/test-espace-local" not in _sur_main("branch", "--list", "dev/test-espace-local")


def test_local_briques_touchees():
    espace = espace_travail.EspaceTravailLocal()
    branche = "dev/test-espace-briques"
    espace.ouvrir(branche)
    wt = os.path.join(git_atelier.ATELIERS, "dev-test-espace-briques")
    os.makedirs(os.path.join(wt, "briques", "mail"), exist_ok=True)
    with open(os.path.join(wt, "briques", "mail", "x.py"), "w") as f:
        f.write("# x\n")
    import subprocess
    subprocess.run(["git", "-C", wt, "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", wt, "commit", "-m", "ajout"], check=True, capture_output=True)
    assert espace.briques_touchees(branche) == ["mail"]
    espace.jeter(branche)


def test_local_refuse_branche_protegee_via_erreur_espace():
    espace = espace_travail.EspaceTravailLocal()
    with pytest.raises(espace_travail.ErreurEspace):
        espace.ouvrir("main")


def test_local_fusionner_et_erreur_espace_sur_conflit():
    espace = espace_travail.EspaceTravailLocal()
    avant = _sur_main("rev-parse", "HEAD").strip()

    chemin_prod = os.path.join(git_atelier.REPO, "conflit_espace.txt")
    with open(chemin_prod, "w") as f:
        f.write("version prod\n")
    import subprocess
    subprocess.run(["git", "-C", git_atelier.REPO, "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", git_atelier.REPO, "commit", "-m", "base conflit"],
                   check=True, capture_output=True)
    base = _sur_main("rev-parse", "HEAD").strip()

    espace.ouvrir("dev/espace-conflit-a", base)
    wt_a = os.path.join(git_atelier.ATELIERS, "dev-espace-conflit-a")
    with open(os.path.join(wt_a, "conflit_espace.txt"), "w") as f:
        f.write("version A\n")
    subprocess.run(["git", "-C", wt_a, "commit", "-am", "A"], check=True, capture_output=True)

    espace.ouvrir("dev/espace-conflit-b", base)
    wt_b = os.path.join(git_atelier.ATELIERS, "dev-espace-conflit-b")
    with open(os.path.join(wt_b, "conflit_espace.txt"), "w") as f:
        f.write("version B\n")
    subprocess.run(["git", "-C", wt_b, "commit", "-am", "B"], check=True, capture_output=True)

    espace.fusionner("dev/espace-conflit-a", base)
    with pytest.raises(espace_travail.ErreurEspace):
        espace.fusionner("dev/espace-conflit-b", base)

    espace.jeter("dev/espace-conflit-a")
    espace.jeter("dev/espace-conflit-b")
    subprocess.run(["git", "-C", git_atelier.REPO, "reset", "--hard", avant],
                   check=True, capture_output=True)


# ── EspaceTravailDistant : stub honnête, jamais de faux succès ──────────────────

def test_distant_jamais_disponible():
    espace = espace_travail.EspaceTravailDistant()
    assert espace.nom == "distant"
    assert espace.disponible() is False


@pytest.mark.parametrize("appel", [
    lambda e: e.ouvrir("dev/x"),
    lambda e: e.diff("dev/x"),
    lambda e: e.resume_diff("dev/x"),
    lambda e: e.briques_touchees("dev/x"),
    lambda e: e.fusionner("dev/x"),
    lambda e: e.jeter("dev/x"),
])
def test_distant_leve_erreur_espace_sur_toute_operation(appel):
    espace = espace_travail.EspaceTravailDistant()
    with pytest.raises(espace_travail.ErreurEspace):
        appel(espace)


# ── choisir_espace() : jamais de silence trompeur ────────────────────────────────

def test_choisir_espace_defaut_local():
    assert isinstance(espace_travail.choisir_espace(), espace_travail.EspaceTravailLocal)


def test_choisir_espace_nom_local_explicite():
    assert isinstance(espace_travail.choisir_espace("local"), espace_travail.EspaceTravailLocal)


def test_choisir_espace_distant_indisponible_retombe_sur_local():
    assert isinstance(espace_travail.choisir_espace("distant"), espace_travail.EspaceTravailLocal)


def test_choisir_espace_nom_inconnu_retombe_sur_local():
    assert isinstance(espace_travail.choisir_espace("sandbox-imaginaire"),
                      espace_travail.EspaceTravailLocal)


def test_choisir_espace_lit_env_dev_espace(monkeypatch):
    monkeypatch.setenv("DEV_ESPACE", "distant")
    assert isinstance(espace_travail.choisir_espace(), espace_travail.EspaceTravailLocal)
    monkeypatch.delenv("DEV_ESPACE", raising=False)
