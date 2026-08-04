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
    avant de considérer l'ancienne session comme close — c'est ce qui garantit qu'aucune
    écriture de l'ancien appareil n'est perdue au moment du relai (cf. `auth_callback`).
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
        nouvelle_generation = (ancienne.generation + 1) if ancienne else 1
        maintenant = time.time()
        c.execute(
            """
            INSERT INTO sessions_actives (sub, generation, appareil, connecte_a)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(sub) DO UPDATE SET generation = ?, appareil = ?, connecte_a = ?
            """,
            (sub, nouvelle_generation, appareil, maintenant,
             nouvelle_generation, appareil, maintenant),
        )
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
