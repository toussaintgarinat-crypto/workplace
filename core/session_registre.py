"""Registre des sessions actives par compte — relai propre entre appareils.

Le Cœur n'a aujourd'hui aucun état de session côté serveur (cookie AES-GCM autoporteur,
cf. `core/auth.py`) : rien ne permet de savoir si un compte est déjà connecté ailleurs.
Ce module ajoute le minimum nécessaire pour ça — pas le contenu de la session (jamais de
token ici), seulement : qui, sur quel appareil, avec quel numéro de génération.

Décision produit (conversation utilisateur) : pas de partage simultané. Une nouvelle
connexion sur un compte déjà actif EST une éviction de l'ancienne — mais avec un point de
contrôle préalable (cf. `checkpoint_session.py`) pour ne rien perdre du travail en cours,
et une notification côté ancien appareil au lieu d'un échec silencieux (cf. modifications
à `core/auth.py` / `core/routers/auth.py` / `core/dashboard.html`).

Même motif SQLite que `core/horloge.py` : fichier configurable par variable
d'environnement, `sqlite3.Row`, `CREATE TABLE IF NOT EXISTS` idempotent.
"""
from __future__ import annotations

import os
import sqlite3
import time
from typing import NamedTuple, Optional

DB = os.getenv("SESSION_REGISTRE_DB", "/data/session_registre.db")


class AncienneSession(NamedTuple):
    generation: int
    appareil: Optional[str]
    connecte_a: float


def _conn() -> sqlite3.Connection:
    dossier = os.path.dirname(DB)
    if dossier:
        os.makedirs(dossier, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions_actives (
                sub TEXT PRIMARY KEY,
                generation INTEGER NOT NULL,
                appareil TEXT,
                connecte_a REAL NOT NULL
            )
            """
        )


def nouvelle_session(sub: str, appareil: Optional[str]) -> tuple[int, Optional[AncienneSession]]:
    """Enregistre une nouvelle connexion pour `sub`, en évinçant toute session précédente.

    Renvoie `(nouvelle_generation, ancienne_session_ou_None)`. Si `ancienne_session_ou_None`
    n'est pas `None`, l'appelant DOIT déclencher `checkpoint_session.declencher_checkpoint`
    avant de considérer l'ancienne session comme close — c'est ce qui contribuera à ce
    qu'aucune écriture de l'ancien appareil ne soit perdue au moment du relai (cf.
    `auth_callback`).

    L'incrément de génération est calculé PAR SQLite lui-même, dans l'UPSERT (`generation =
    sessions_actives.generation + 1`, `RETURNING generation`) — pas en Python après un SELECT
    séparé. Deux appels concurrents sur le même `sub` ne peuvent donc JAMAIS recevoir le même
    numéro de génération (SQLite sérialise les écritures conflictuelles sur une même ligne) ;
    avant ce correctif (Critical 2, revue finale whole-branch), le SELECT-puis-calcul-puis-
    écriture était reproductible 5/5 en concurrence réelle. Le `SELECT` initial ci-dessous ne
    sert plus qu'à capturer l'« ancienne session » pour le retour — une légère staleness y est
    possible sous vraie concurrence (l'ancienne session rapportée à l'appelant peut ne pas
    être exactement celle qui vient d'être remplacée), acceptable ici : ce n'est qu'un
    déclencheur best-effort de checkpoint (cf. `checkpoint_session.py`), pas la garantie de
    génération elle-même.
    """
    init_db()
    with _conn() as c:
        row = c.execute(
            "SELECT generation, appareil, connecte_a FROM sessions_actives WHERE sub = ?",
            (sub,),
        ).fetchone()
        ancienne = (
            AncienneSession(row["generation"], row["appareil"], row["connecte_a"])
            if row is not None
            else None
        )
        maintenant = time.time()
        cur = c.execute(
            """
            INSERT INTO sessions_actives (sub, generation, appareil, connecte_a)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(sub) DO UPDATE SET
                generation = sessions_actives.generation + 1,
                appareil = excluded.appareil,
                connecte_a = excluded.connecte_a
            RETURNING generation
            """,
            (sub, appareil, maintenant),
        )
        nouvelle_generation = cur.fetchone()[0]
    return nouvelle_generation, ancienne


def generation_actuelle(sub: str) -> Optional[int]:
    """Génération actuellement enregistrée pour `sub`, ou `None` si jamais connecté —
    `None` signifie « pas encore de registre pour ce compte », traité comme non bloquant
    par `exiger_session` (comportement historique préservé pour les cookies déjà émis)."""
    init_db()
    with _conn() as c:
        row = c.execute(
            "SELECT generation FROM sessions_actives WHERE sub = ?", (sub,)
        ).fetchone()
        return row["generation"] if row is not None else None
