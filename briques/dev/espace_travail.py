"""Seam à 3 rôles sur l'ESPACE DE TRAVAIL du chantier (Service Definition / Provider / Consumer,
vocabulaire de la veille GitHub deepseek-ai/deepseek-harness — Cordis, « capability seams »).

Aujourd'hui, `git_atelier.py` fait tout : le worktree jetable vit sur CETTE machine, `git` est
lancé en sous-processus local. C'est un choix d'implémentation, pas un invariant du domaine — le
domaine (`domaine.py`) et les consommateurs (`main.py`) n'ont besoin que du CONTRAT « ouvrir une
copie isolée sur une branche neuve, en tirer un diff, fusionner ou jeter ». Ce module rend ce
contrat explicite (`EspaceTravail`) pour qu'un futur provider distant (sandbox conteneurisé,
VM dédiée…) puisse un jour remplacer l'implémentation locale SANS toucher `main.py` :

  • Service Definition — `EspaceTravail` : l'interface que tout provider doit tenir.
  • Provider  — `EspaceTravailLocal` : délègue tel quel à `git_atelier` (comportement inchangé,
    aucune régression sur le filet git existant).
  • Provider  — `EspaceTravailDistant` : STUB HONNÊTE. Rien n'est implémenté ; `disponible()`
    répond toujours False et chaque opération lève `ErreurEspace` plutôt que de prétendre avoir
    tourné quelque part. Même honnêteté que le mock `Factice` d'`agents.py` : on ne fait jamais
    semblant qu'un provider indisponible a réussi.
  • Consumer  — `main.py` n'importera plus `git_atelier` pour le cycle de vie du chantier ; il
    appelle `choisir_espace()` et ne connaît que l'interface `EspaceTravail`.
"""
from __future__ import annotations

import os

import git_atelier


class ErreurEspace(RuntimeError):
    """Une opération sur l'espace de travail a échoué — message diagnostic honnête."""


class EspaceTravail:
    """Interface commune. Une sous-classe implémente `disponible()` et les 6 opérations."""
    nom = "abstrait"

    def disponible(self) -> bool:
        raise NotImplementedError

    def ouvrir(self, branche: str, base: str = "HEAD") -> str:
        raise NotImplementedError

    def diff(self, branche: str, base: str = "HEAD") -> str:
        raise NotImplementedError

    def resume_diff(self, branche: str, base: str = "HEAD") -> dict:
        raise NotImplementedError

    def briques_touchees(self, branche: str, base: str = "HEAD") -> list:
        raise NotImplementedError

    def fusionner(self, branche: str, base: str = "HEAD") -> str:
        raise NotImplementedError

    def jeter(self, branche: str) -> None:
        raise NotImplementedError


class EspaceTravailLocal(EspaceTravail):
    """Provider par défaut : worktree git sur CETTE machine (comportement historique).

    Délègue tel quel à `git_atelier` — c'est le SEUL provider fonctionnel aujourd'hui. Toute
    `git_atelier.ErreurGit` est traduite en `ErreurEspace` : le consommateur (`main.py`) ne
    dépend plus d'un type d'erreur spécifique au git local."""
    nom = "local"

    def disponible(self) -> bool:
        return git_atelier.est_un_depot()

    def ouvrir(self, branche: str, base: str = "HEAD") -> str:
        try:
            return git_atelier.ouvrir_chantier(branche, base)
        except git_atelier.ErreurGit as e:
            raise ErreurEspace(str(e)) from e

    def diff(self, branche: str, base: str = "HEAD") -> str:
        try:
            return git_atelier.diff_chantier(branche, base)
        except git_atelier.ErreurGit as e:
            raise ErreurEspace(str(e)) from e

    def resume_diff(self, branche: str, base: str = "HEAD") -> dict:
        try:
            return git_atelier.resume_diff(branche, base)
        except git_atelier.ErreurGit as e:
            raise ErreurEspace(str(e)) from e

    def briques_touchees(self, branche: str, base: str = "HEAD") -> list:
        try:
            return git_atelier.briques_touchees(branche, base)
        except git_atelier.ErreurGit as e:
            raise ErreurEspace(str(e)) from e

    def fusionner(self, branche: str, base: str = "HEAD") -> str:
        try:
            return git_atelier.fusionner(branche, base)
        except git_atelier.ErreurGit as e:
            raise ErreurEspace(str(e)) from e

    def jeter(self, branche: str) -> None:
        # Pas de try/except ErreurGit ici : `git_atelier.jeter_chantier` appelle `_git(...,
        # check=False)` partout et ne lève donc jamais — idempotent et tolérant par construction.
        git_atelier.jeter_chantier(branche)


class EspaceTravailDistant(EspaceTravail):
    """Provider FUTUR (non implémenté) : sandbox distant (conteneur/VM dédiée).

    Prouve que le seam est swappable sans prétendre qu'un sandbox distant existe. Honnêteté
    par construction : `disponible()` renvoie toujours False, et chaque opération lève
    `ErreurEspace` avec un message clair plutôt qu'un faux succès local."""
    nom = "distant"

    _MESSAGE = ("espace de travail « distant » non implémenté — aucun sandbox distant n'est "
                "câblé ; utilise l'espace « local » (défaut) en attendant un futur provider")

    def disponible(self) -> bool:
        return False

    def ouvrir(self, branche: str, base: str = "HEAD") -> str:
        raise ErreurEspace(self._MESSAGE)

    def diff(self, branche: str, base: str = "HEAD") -> str:
        raise ErreurEspace(self._MESSAGE)

    def resume_diff(self, branche: str, base: str = "HEAD") -> dict:
        raise ErreurEspace(self._MESSAGE)

    def briques_touchees(self, branche: str, base: str = "HEAD") -> list:
        raise ErreurEspace(self._MESSAGE)

    def fusionner(self, branche: str, base: str = "HEAD") -> str:
        raise ErreurEspace(self._MESSAGE)

    def jeter(self, branche: str) -> None:
        raise ErreurEspace(self._MESSAGE)


_ESPACES = {c.nom: c for c in (EspaceTravailLocal, EspaceTravailDistant)}


def choisir_espace(nom: str = "") -> EspaceTravail:
    """Renvoie l'espace demandé (ou `DEV_ESPACE` si `nom` vide), replié sur Local si absent.

    Jamais de silence trompeur : un nom inconnu ou un provider indisponible (le seul provider
    fonctionnel est `local` pour l'instant) retombe sur `EspaceTravailLocal`, comme
    `agents.choisir()` retombe sur `Factice` — on ne prétend jamais qu'un provider a tourné."""
    nom = nom or os.environ.get("DEV_ESPACE", "")
    if nom and nom in _ESPACES:
        espace = _ESPACES[nom]()
        if espace.disponible():
            return espace
    return EspaceTravailLocal()
