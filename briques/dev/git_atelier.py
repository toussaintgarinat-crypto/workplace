"""Le filet : git worktrees jetables. C'est la pièce qui rend l'auto-atelier sûr.

Principe : l'agent ne travaille JAMAIS dans le dépôt vivant. Pour chaque chantier on crée
un **worktree isolé** sur une **branche neuve** (`git worktree add -b dev/… <chemin> <base>`).
La prod continue de tourner sur `main` ; l'agent ne voit que sa copie. On calcule le **diff**
de la branche par rapport à la base, et soit on fusionne (incrément 4, gate humain), soit on
**jette** le worktree — sans laisser de trace.

Garde-fous, par construction :
  • refus de cibler une branche protégée (`main`/`master`/…) — cf. `domaine.branche_protegee` ;
  • aucun `git push`, aucune fusion ici (incrément 1 = produire un diff, rien de plus) ;
  • les worktrees vivent HORS du dépôt (dossier dédié) pour ne pas imbriquer deux .git.

Tout passe par `git` en sous-processus : pas de dépendance, et c'est le même git que l'humain.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

import domaine

# Dépôt cible (le projet Workplace lui-même) et dossier des worktrees jetables.
REPO = os.environ.get("DEV_REPO", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
ATELIERS = os.environ.get("DEV_ATELIERS", os.path.join(tempfile.gettempdir(), "ateliers-dev"))


class ErreurGit(RuntimeError):
    """Une commande git a échoué — message brut remonté pour diagnostic honnête."""


def _run(repo: str, *args: str) -> tuple[int, str, str]:
    """Lance `git -C <repo> <args>` et renvoie `(code, stdout, stderr)`, sans jamais lever."""
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _git(repo: str, *args: str, check: bool = True) -> str:
    """Lance `git -C <repo> <args>` et renvoie stdout. Lève `ErreurGit` si check et code≠0."""
    code, out, err = _run(repo, *args)
    if check and code != 0:
        raise ErreurGit((err or out or "échec git").strip())
    return out


def est_un_depot(repo: str = REPO) -> bool:
    """Le chemin est-il bien un dépôt git ? (sinon l'atelier n'a pas de filet)."""
    try:
        return _git(repo, "rev-parse", "--is-inside-work-tree").strip() == "true"
    except (ErreurGit, FileNotFoundError):
        return False


def ouvrir_chantier(branche: str, base: str = "HEAD", repo: str = REPO) -> str:
    """Crée un worktree jetable sur une branche NEUVE depuis `base`. Renvoie son chemin.

    Refuse une branche protégée (le filet). Échoue proprement si la branche existe déjà."""
    if domaine.branche_protegee(branche):
        raise ErreurGit(f"refus de cibler une branche protégée : {branche!r}")
    os.makedirs(ATELIERS, exist_ok=True)
    chemin = os.path.join(ATELIERS, domaine.slug(branche))
    if os.path.exists(chemin):
        raise ErreurGit(f"un worktree existe déjà à {chemin}")
    _git(repo, "worktree", "add", "-b", branche, chemin, base)
    return chemin


def diff_chantier(branche: str, base: str = "HEAD", repo: str = REPO) -> str:
    """Diff des changements APPORTÉS par la branche depuis sa divergence de `base` (3 points).

    C'est ce que l'humain relit au gate. La prod (base) n'est jamais modifiée."""
    return _git(repo, "diff", f"{base}...{branche}")


def resume_diff(branche: str, base: str = "HEAD", repo: str = REPO) -> dict:
    """Statistiques compactes du diff (fichiers touchés, insertions/suppressions)."""
    sortie = _git(repo, "diff", "--numstat", f"{base}...{branche}").strip()
    fichiers, ajouts, retraits = [], 0, 0
    for ligne in (l for l in sortie.splitlines() if l.strip()):
        parts = ligne.split("\t")
        if len(parts) == 3:
            a, r, f = parts
            fichiers.append(f)
            ajouts += int(a) if a.isdigit() else 0
            retraits += int(r) if r.isdigit() else 0
    return {"fichiers": fichiers, "ajouts": ajouts, "retraits": retraits}


def briques_touchees(branche: str, base: str = "HEAD", repo: str = REPO) -> list:
    """Noms des briques modifiées par le diff (chemins `briques/<nom>/…`), triés et dédupliqués.

    Sert au rebuild CIBLÉ (on ne rebuild que ce qui a changé) et au garde-fou des briques
    sensibles (`domaine.fusion_autorisee`)."""
    noms = set()
    for f in resume_diff(branche, base, repo)["fichiers"]:
        parts = f.split("/")
        if len(parts) >= 2 and parts[0] == "briques" and parts[1]:
            noms.add(parts[1])
    return sorted(noms)


def fusionner(branche: str, base: str = "HEAD", repo: str = REPO) -> str:
    """Fusionne la branche du chantier dans la branche courante du dépôt (`git merge --no-ff`).

    C'est le SEUL endroit qui touche la base (`main`). Garde-fous, par construction :
      • la SOURCE ne peut pas être une branche protégée (on ne fusionne pas `main` dans `main`) ;
      • `--no-ff` : la fusion reste un commit relisible/`git revert`-able (pas de fast-forward) ;
      • on ne FORCE jamais : un conflit (ou un arbre sale) → `merge --abort` puis `ErreurGit`,
        le dépôt est laissé propre, à l'humain de trancher.
    Aucun `git push` : fusionner reste local. Renvoie la sortie de merge (traçable)."""
    if domaine.branche_protegee(branche):
        raise ErreurGit(f"la source d'une fusion ne peut pas être une branche protégée : {branche!r}")
    cible = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if cible == branche:
        raise ErreurGit(f"le dépôt est déjà sur {branche!r} : rien à fusionner")
    message = f"dev(atelier): fusion de {branche} dans {cible}"
    code, out, err = _run(repo, "merge", "--no-ff", "-m", message, branche)
    if code != 0:
        _run(repo, "merge", "--abort")  # ne JAMAIS laisser un conflit en place
        raise ErreurGit("fusion impossible (conflit ou arbre sale) — rien n'a été fusionné : "
                        + (err or out or "").strip())
    return (out or "").strip()


def jeter_chantier(branche: str, repo: str = REPO) -> None:
    """Détruit le worktree ET la branche : le chantier disparaît, prod intacte.

    Idempotent et tolérant : un worktree/branche déjà absent n'est pas une erreur."""
    chemin = os.path.join(ATELIERS, domaine.slug(branche))
    _git(repo, "worktree", "remove", "--force", chemin, check=False)
    _git(repo, "branch", "-D", branche, check=False)
    # Nettoie d'éventuelles références mortes (worktree supprimé à la main, etc.).
    _git(repo, "worktree", "prune", check=False)
