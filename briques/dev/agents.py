"""Couche d'abstraction sur l'agent de code. Choix par chantier : Claude Code OU OpenCode.

Un `LanceurAgent` reçoit un worktree isolé + une intention et renvoie un résultat uniforme :

    {"agent": <nom>, "resume": <str>, "journal": [<étapes en français>], "diff_pret": <bool>}

Trois implémentations :
  • `ClaudeCode`  — `claude -p` en mode headless (l'agent que l'utilisateur connaît) ;
  • `OpenCode`    — binaire `opencode` (modèles via la Gateway, provider opencode-go) ;
  • `Factice`     — MOCK HONNÊTE par défaut : aucun binaire requis, fait une modification
                    inoffensive et traçable dans le worktree puis COMMITE, en disant clairement
                    que c'est une simulation. Permet de PROUVER le filet hors-ligne.

Honnêteté : si le binaire d'un agent réel est absent, on ne fait pas semblant — `disponible()`
renvoie False et `choisir()` retombe sur le mock factice en l'annonçant. La `task trace`
(narration pas-à-pas, pédagogique) est l'incrément 3 ; ici le journal reste minimal.
"""
from __future__ import annotations

import os
import shutil
import subprocess

# Invite commune : DDD + filet. Étoffée au flux BMAD (plan d'abord) à l'incrément 2.
GABARIT_INVITE = (
    "Tu travailles dans une COPIE ISOLÉE (git worktree) du projet Workplace, sur une branche "
    "dédiée — jamais `main`. Objectif : {intention}. Respecte le Domain-Driven Design "
    "(entités/agrégats, langage métier, domaine pur). Ne pousse rien, ne déploie rien : "
    "produis des modifications de fichiers, je relirai le diff."
)


class LanceurAgent:
    """Interface commune. Une sous-classe implémente `disponible()` et `executer()`."""
    nom = "abstrait"

    def disponible(self) -> bool:
        raise NotImplementedError

    def executer(self, worktree: str, intention: str, trace: bool = False,
                 brique_cible: str = "") -> dict:
        raise NotImplementedError


def _commit(worktree: str, message: str) -> None:
    """Commite tout le travail dans le worktree (sur SA branche). Aucun push."""
    subprocess.run(["git", "-C", worktree, "add", "-A"], capture_output=True, text=True)
    subprocess.run(["git", "-C", worktree, "commit", "-m", message, "--no-verify"],
                   capture_output=True, text=True)


class ClaudeCode(LanceurAgent):
    """Claude Code en non-interactif : `claude -p <invite>` exécuté dans le worktree."""
    nom = "claude_code"

    def disponible(self) -> bool:
        return shutil.which("claude") is not None

    def executer(self, worktree: str, intention: str, trace: bool = False,
                 brique_cible: str = "") -> dict:
        invite = GABARIT_INVITE.format(intention=intention)
        proc = subprocess.run(
            ["claude", "-p", invite],
            cwd=worktree, capture_output=True, text=True,
        )
        _commit(worktree, f"dev(atelier): {intention}")
        journal = ["Lancement de Claude Code dans le worktree isolé.",
                   "Travail de l'agent terminé, changements commités sur la branche."]
        return {"agent": self.nom, "resume": (proc.stdout or "").strip()[:2000],
                "journal": journal if trace else [], "diff_pret": True}


class OpenCode(LanceurAgent):
    """OpenCode (souverain, modèles via la Gateway) : `opencode run <invite>` dans le worktree."""
    nom = "opencode"

    def disponible(self) -> bool:
        return shutil.which("opencode") is not None

    def executer(self, worktree: str, intention: str, trace: bool = False,
                 brique_cible: str = "") -> dict:
        invite = GABARIT_INVITE.format(intention=intention)
        proc = subprocess.run(
            ["opencode", "run", invite],
            cwd=worktree, capture_output=True, text=True,
        )
        _commit(worktree, f"dev(atelier): {intention}")
        journal = ["Lancement d'OpenCode dans le worktree isolé.",
                   "Travail de l'agent terminé, changements commités sur la branche."]
        return {"agent": self.nom, "resume": (proc.stdout or "").strip()[:2000],
                "journal": journal if trace else [], "diff_pret": True}


class Factice(LanceurAgent):
    """Mock HONNÊTE : pas d'IA. Dépose une note traçable dans le worktree et commite.

    Sert à prouver le filet (worktree → diff → jeter) sans aucun binaire d'agent, et à
    ne jamais prétendre qu'un vrai agent a tourné quand il est absent."""
    nom = "factice"

    def disponible(self) -> bool:
        return True

    def executer(self, worktree: str, intention: str, trace: bool = False,
                 brique_cible: str = "") -> dict:
        # Quand un chantier vise une brique, la note atterrit DANS `briques/<nom>/` — comme le
        # ferait un vrai agent : le rebuild ciblé (S87) peut alors repérer la brique modifiée.
        if brique_cible:
            dossier = os.path.join(worktree, "briques", brique_cible)
            os.makedirs(dossier, exist_ok=True)
            chemin = os.path.join(dossier, "ATELIER_DEV_NOTE.md")
        else:
            chemin = os.path.join(worktree, "ATELIER_DEV_NOTE.md")
        with open(chemin, "w", encoding="utf-8") as f:
            f.write(
                "# Note d'atelier (simulation honnête)\n\n"
                f"Intention demandée : **{intention}**\n\n"
                "Aucun agent de code réel (Claude Code / OpenCode) n'était disponible : "
                "cette modification est un PLACEHOLDER pour prouver le filet git "
                "(worktree isolé → diff → fusion/abandon). Rien n'a touché `main`.\n"
            )
        _commit(worktree, f"dev(atelier, simulation): {intention}")
        journal = ["Aucun agent réel disponible → mock factice honnête.",
                   "Dépôt d'une note traçable dans le worktree, commitée sur la branche.",
                   "Le diff est prêt à être relu ; la prod n'a pas bougé."]
        return {"agent": self.nom,
                "resume": "Simulation honnête : note d'atelier déposée (aucun vrai agent).",
                "journal": journal if trace else [], "diff_pret": True}


_LANCEURS = {c.nom: c for c in (ClaudeCode, OpenCode, Factice)}


def choisir(nom: str = "") -> LanceurAgent:
    """Renvoie le lanceur demandé s'il est disponible, sinon retombe sur le mock factice.

    `nom` vide = auto : Claude Code s'il est là, sinon OpenCode, sinon factice honnête."""
    if nom and nom in _LANCEURS:
        agent = _LANCEURS[nom]()
        return agent if agent.disponible() else Factice()
    for cls in (ClaudeCode, OpenCode):
        agent = cls()
        if agent.disponible():
            return agent
    return Factice()
