"""S36 — course de provisioning au 1er login (bug S19), sans DB réelle.

Deux 1ers logins concurrents du même utilisateur passent tous deux le `select` initial
(aucun user), puis insèrent → violation d'unicité. Avant S36 : 500 « auto-réparé » au
retry. Après : le savepoint capte l'``IntegrityError`` et on récupère le gagnant.

On simule la session SQLAlchemy : le 1er `flush` (insert) lève ``IntegrityError`` ; le
re-`select` par sub renvoie alors l'utilisateur créé par la transaction concurrente.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app import auth


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def first(self):
        return self._value


class _Nested:
    """Contexte de savepoint : laisse passer l'exception (comme begin_nested réel)."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeSession:
    """Session minimale : `execute` renvoie les résultats dans l'ordre d'appel (robuste,
    sans dépendre du texte SQL) ; `flush` peut lever une fois."""

    def __init__(self, *, exec_results, flush_raises):
        self._exec_results = list(exec_results)
        self._flush_raises = flush_raises
        self.added = []

    async def execute(self, stmt):
        return _Result(self._exec_results.pop(0) if self._exec_results else None)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        if self._flush_raises:
            self._flush_raises = False  # ne lève qu'une fois (le 1er insert)
            raise IntegrityError("INSERT", {}, Exception("users_keycloak_sub_unique"))

    def begin_nested(self):
        return _Nested()


@pytest.mark.asyncio
async def test_course_provisioning_recupere_le_gagnant():
    gagnant = auth.Users(email="a@b.c", nom="Alice", avatar_emoji="👤", keycloak_sub="sub-1")
    # Appels execute : sub→None, email→None, [insert lève], except: sub→gagnant.
    session = _FakeSession(exec_results=[None, None, gagnant], flush_raises=True)

    user = await auth._provision_user(session, {"sub": "sub-1", "email": "a@b.c", "nom": "Alice"})

    assert user is gagnant, "la course doit renvoyer l'utilisateur déjà créé, pas lever un 500"


@pytest.mark.asyncio
async def test_integrity_error_non_resolue_remonte():
    # IntegrityError mais aucun gagnant retrouvé (autre cause d'unicité) → on ne masque pas.
    session = _FakeSession(exec_results=[None, None, None, None], flush_raises=True)
    with pytest.raises(IntegrityError):
        await auth._provision_user(session, {"sub": "sub-x", "email": "x@y.z", "nom": "X"})


@pytest.mark.asyncio
async def test_chemin_nominal_insere_une_fois():
    # Pas de course : sub→None, email→None, flush OK → l'utilisateur inséré est renvoyé.
    session = _FakeSession(exec_results=[None, None], flush_raises=False)
    user = await auth._provision_user(session, {"sub": "sub-2", "email": "n@e.w", "nom": "Neo"})
    assert user.keycloak_sub == "sub-2" and user in session.added
