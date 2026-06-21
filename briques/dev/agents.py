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
renvoie False et `choisir()` retombe sur le mock factice en l'annonçant.

Task trace (S89) : quand `trace=True` ET qu'un `trace_fichier` est fourni, l'agent RACONTE ses
pas en français dans ce journal (live + archivé). Le factice narre ses propres pas ; Claude Code
délègue la narration fine de ses outils à un **hook** (`trace_hook.py`) branché en `PreToolUse`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import traceur

# Script de hook Claude Code (PreToolUse) qui traduit chaque outil en phrase FR (S89).
_HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trace_hook.py")

# Invite commune : DDD + filet + (S88) le DOMAINE PUR d'abord, et la story (plan validé) en tête.
GABARIT_INVITE = (
    "Tu travailles dans une COPIE ISOLÉE (git worktree) du projet Workplace, sur une branche "
    "dédiée — jamais `main`. Objectif : {intention}.\n"
    "Méthode imposée (Domain-Driven Design) : commence par le DOMAINE PUR — modélise les "
    "entités/agrégats en langage métier dans un `domaine.py` SANS aucune I/O (ni réseau, ni "
    "base, ni fichier), testable hors-ligne — AVANT toute logique technique ou branchement. "
    "Ne pousse rien, ne déploie rien : produis des modifications de fichiers, je relirai le diff."
)

# Préfixe injecté quand un plan BMAD a été validé : la story porte le contexte (3e idée BMAD).
GABARIT_PLAN = (
    "PLAN VALIDÉ à respecter (ne t'en écarte pas sans raison ; il prime sur l'improvisation) :\n"
    "{plan}\n\n"
)


def _invite(intention: str, plan: str = "") -> str:
    """Compose l'invite : le plan validé en tête (s'il existe), puis le gabarit DDD + filet."""
    base = GABARIT_INVITE.format(intention=intention)
    return (GABARIT_PLAN.format(plan=plan) + base) if plan.strip() else base


class LanceurAgent:
    """Interface commune. Une sous-classe implémente `disponible()` et `executer()`."""
    nom = "abstrait"

    def disponible(self) -> bool:
        raise NotImplementedError

    def executer(self, worktree: str, intention: str, trace: bool = False,
                 brique_cible: str = "", plan: str = "") -> dict:
        raise NotImplementedError


def _commit(worktree: str, message: str) -> None:
    """Commite tout le travail dans le worktree (sur SA branche). Aucun push."""
    subprocess.run(["git", "-C", worktree, "add", "-A"], capture_output=True, text=True)
    subprocess.run(["git", "-C", worktree, "commit", "-m", message, "--no-verify"],
                   capture_output=True, text=True)


def _narrer(trace_fichier: str, phrase: str) -> None:
    """Ajoute un pas narré au journal de trace, si la trace est active (sinon no-op)."""
    if trace_fichier:
        traceur.Traceur(trace_fichier).noter(phrase)


def _resultat(nom: str, resume: str, trace_fichier: str, secours: list) -> dict:
    """Compose le retour uniforme. `journal` = la narration tracée (ou le secours si pas de trace)."""
    journal = traceur.Traceur(trace_fichier).phrases() if trace_fichier else []
    return {"agent": nom, "resume": resume, "journal": journal or (secours if trace_fichier else []),
            "diff_pret": True}


def _brancher_hook_claude(worktree: str, trace_fichier: str) -> None:
    """Écrit un `.claude/settings.json` dans le worktree qui narre chaque outil en direct (S89).

    Best-effort : si l'écriture échoue, le run de Claude Code continue (la trace est un bonus)."""
    try:
        dossier = os.path.join(worktree, ".claude")
        os.makedirs(dossier, exist_ok=True)
        reglages = {"hooks": {"PreToolUse": [{"matcher": "",
                    "hooks": [{"type": "command", "command": f"python3 {_HOOK} {trace_fichier}"}]}]}}
        with open(os.path.join(dossier, "settings.json"), "w", encoding="utf-8") as f:
            json.dump(reglages, f)
    except OSError:
        pass


class ClaudeCode(LanceurAgent):
    """Claude Code en non-interactif : `claude -p <invite>` exécuté dans le worktree."""
    nom = "claude_code"

    def disponible(self) -> bool:
        return shutil.which("claude") is not None

    def executer(self, worktree: str, intention: str, trace: bool = False,
                 brique_cible: str = "", plan: str = "", trace_fichier: str = "") -> dict:
        tf = trace_fichier if trace else ""
        if tf:
            _brancher_hook_claude(worktree, tf)  # narration live de chaque outil (PreToolUse)
            _narrer(tf, "J'ouvre la branche dédiée et je lance Claude Code dans la copie isolée.")
        invite = _invite(intention, plan)
        proc = subprocess.run(
            ["claude", "-p", invite],
            cwd=worktree, capture_output=True, text=True,
        )
        _narrer(tf, "Travail terminé : je commite mes changements sur la branche.")
        _commit(worktree, f"dev(atelier): {intention}")
        return _resultat(self.nom, (proc.stdout or "").strip()[:2000], tf,
                         ["Lancement de Claude Code dans le worktree isolé.",
                          "Travail terminé, changements commités sur la branche."])


class OpenCode(LanceurAgent):
    """OpenCode (souverain, modèles via la Gateway) : `opencode run <invite>` dans le worktree."""
    nom = "opencode"

    def disponible(self) -> bool:
        return shutil.which("opencode") is not None

    def executer(self, worktree: str, intention: str, trace: bool = False,
                 brique_cible: str = "", plan: str = "", trace_fichier: str = "") -> dict:
        tf = trace_fichier if trace else ""
        _narrer(tf, "J'ouvre la branche dédiée et je lance OpenCode dans la copie isolée.")
        invite = _invite(intention, plan)
        proc = subprocess.run(
            ["opencode", "run", invite],
            cwd=worktree, capture_output=True, text=True,
        )
        _narrer(tf, "Travail terminé : je commite mes changements sur la branche.")
        _commit(worktree, f"dev(atelier): {intention}")
        return _resultat(self.nom, (proc.stdout or "").strip()[:2000], tf,
                         ["Lancement d'OpenCode dans le worktree isolé.",
                          "Travail terminé, changements commités sur la branche."])


class Factice(LanceurAgent):
    """Mock HONNÊTE : pas d'IA. Dépose une note traçable dans le worktree et commite.

    Sert à prouver le filet (worktree → diff → jeter) sans aucun binaire d'agent, et à
    ne jamais prétendre qu'un vrai agent a tourné quand il est absent."""
    nom = "factice"

    def disponible(self) -> bool:
        return True

    def executer(self, worktree: str, intention: str, trace: bool = False,
                 brique_cible: str = "", plan: str = "", trace_fichier: str = "") -> dict:
        tf = trace_fichier if trace else ""
        _narrer(tf, "Aucun agent réel disponible : je simule honnêtement (mock).")
        # Quand un chantier vise une brique, la note atterrit DANS `briques/<nom>/` — comme le
        # ferait un vrai agent : le rebuild ciblé (S87) peut alors repérer la brique modifiée.
        if brique_cible:
            dossier = os.path.join(worktree, "briques", brique_cible)
            os.makedirs(dossier, exist_ok=True)
            chemin = os.path.join(dossier, "ATELIER_DEV_NOTE.md")
            _narrer(tf, f"Je crée la note dans la brique ciblée : briques/{brique_cible}/.")
        else:
            chemin = os.path.join(worktree, "ATELIER_DEV_NOTE.md")
            _narrer(tf, "Je crée une note d'atelier à la racine du worktree.")
        if plan.strip():
            _narrer(tf, "Je reporte le plan validé dans la note (la story porte le contexte).")
        bloc_plan = f"\n## Plan validé suivi\n\n{plan}\n" if plan.strip() else ""
        with open(chemin, "w", encoding="utf-8") as f:
            f.write(
                "# Note d'atelier (simulation honnête)\n\n"
                f"Intention demandée : **{intention}**\n\n"
                "Aucun agent de code réel (Claude Code / OpenCode) n'était disponible : "
                "cette modification est un PLACEHOLDER pour prouver le filet git "
                "(worktree isolé → diff → fusion/abandon). Rien n'a touché `main`.\n"
                + bloc_plan
            )
        _narrer(tf, "Je commite la note sur la branche ; le diff est prêt à relire.")
        _commit(worktree, f"dev(atelier, simulation): {intention}")
        return _resultat(self.nom, "Simulation honnête : note d'atelier déposée (aucun vrai agent).",
                         tf, ["Aucun agent réel disponible → mock factice honnête.",
                              "Dépôt d'une note traçable dans le worktree, commitée sur la branche.",
                              "Le diff est prêt à être relu ; la prod n'a pas bougé."])


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
