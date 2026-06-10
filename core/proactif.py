"""Proactif léger (Sprint S12) — l'assistant signale spontanément des choses utiles.

Repris de l'IDÉE de `workspace/assistant/backend/proactive.py` (`run_check` qui agrège
des vérifications → alertes), mais en version **autonome** : une simple boucle asyncio
dans le Cœur, SANS Redis ni push ni canaux externes. Les « rappels » sont persistés en
SQLite et dédoublonnés (pas de spam) ; le front les affiche via une pastille 🔔.

Vérifications Workplace : rendez-vous imminents (agenda, S10) et documents non classés
(ETL, S9). Extensible : ajouter une coroutine dans `CHECKS`.
"""

import asyncio
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import httpx

import agenda
import orchestrateur

logger = logging.getLogger(__name__)

DB = os.getenv("RAPPELS_DB", "/data/rappels.db")
INTERVALLE = int(os.getenv("PROACTIF_INTERVALLE", "300"))  # secondes


def _conn() -> sqlite3.Connection:
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS rappels (
                id     TEXT PRIMARY KEY,
                type   TEXT NOT NULL,
                titre  TEXT NOT NULL,
                corps  TEXT,
                cle    TEXT,            -- clé de dédoublonnage
                cree   TEXT NOT NULL,
                vu     INTEGER DEFAULT 0
            )
        """)


def _ajouter(type_: str, titre: str, corps: str, cle: str) -> bool:
    """Insère un rappel si aucun rappel NON LU avec la même clé n'existe déjà."""
    with _conn() as c:
        existe = c.execute(
            "SELECT 1 FROM rappels WHERE cle = ? AND vu = 0 LIMIT 1", (cle,)
        ).fetchone()
        if existe:
            return False
        c.execute(
            "INSERT INTO rappels (id, type, titre, corps, cle, cree, vu) VALUES (?,?,?,?,?,?,0)",
            (str(uuid.uuid4()), type_, titre, corps, cle, datetime.utcnow().isoformat()),
        )
    return True


def lister(non_lus: bool = False, limite: int = 50) -> list[dict]:
    with _conn() as c:
        sql = "SELECT * FROM rappels"
        if non_lus:
            sql += " WHERE vu = 0"
        sql += " ORDER BY vu ASC, cree DESC LIMIT ?"
        rows = c.execute(sql, (limite,)).fetchall()
    return [dict(r) for r in rows]


def existe_cle(cle: str) -> bool:
    """Vrai si un rappel porte déjà cette clé, LU ou NON (contrairement au
    dédoublonnage « non lu » de `_ajouter`). Sert l'idempotence par jour du
    briefing (S30) : un seul briefing par date, même s'il a déjà été lu."""
    with _conn() as c:
        return c.execute(
            "SELECT 1 FROM rappels WHERE cle = ? LIMIT 1", (cle,)
        ).fetchone() is not None


def supprimer_cle(cle: str) -> int:
    """Supprime tous les rappels portant cette clé (lus ou non). Sert la
    régénération forcée du briefing (S30) : on remplace, on ne duplique pas."""
    with _conn() as c:
        return c.execute("DELETE FROM rappels WHERE cle = ?", (cle,)).rowcount


def compter_non_lus() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM rappels WHERE vu = 0").fetchone()[0]


def marquer_vu(rappel_id: str) -> bool:
    with _conn() as c:
        n = c.execute("UPDATE rappels SET vu = 1 WHERE id = ?", (rappel_id,)).rowcount
    return n > 0


# ── Vérifications ────────────────────────────────────────────────────────────

async def _check_agenda(registre) -> int:
    """Rendez-vous dans les 2 prochaines heures."""
    n = 0
    try:
        maintenant = datetime.now()
        fin = maintenant + timedelta(hours=2)
        evts = await agenda.lister_evenements(
            registre, maintenant.isoformat(), fin.isoformat())
        for e in evts:
            heure = (e.get("start_at") or "")[11:16]
            titre = f"Rendez-vous bientôt : {e.get('title','(sans titre)')}"
            corps = f"À {heure}" + (f" — {e.get('location')}" if e.get("location") else "")
            if _ajouter("agenda", titre, corps, f"agenda:{e.get('id')}"):
                n += 1
    except Exception as ex:  # noqa: BLE001
        logger.warning("Proactif agenda : %s", ex)
    return n


async def _check_documents(registre) -> int:
    """Documents ingérés mais non classés (sans metadonnees.classement)."""
    try:
        base = orchestrateur._brique_base(registre, "etl")
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{base}/documents", params={"limite": 500})
        docs = r.json().get("documents", []) if r.status_code < 400 else []
        non_classes = [d for d in docs if not (d.get("classement") or {}).get("categorie")]
        if non_classes:
            titre = f"{len(non_classes)} document(s) à classer"
            corps = ", ".join(d.get("nom", "?") for d in non_classes[:5])
            # Clé datée du jour → un seul rappel « à classer » par jour.
            cle = "docs-a-classer:" + datetime.utcnow().strftime("%Y-%m-%d")
            return 1 if _ajouter("documents", titre, corps, cle) else 0
    except Exception as ex:  # noqa: BLE001
        logger.warning("Proactif documents : %s", ex)
    return 0


CHECKS = [_check_agenda, _check_documents]


async def run_check(registre) -> int:
    """Lance toutes les vérifications, renvoie le nombre de nouveaux rappels."""
    resultats = await asyncio.gather(*(chk(registre) for chk in CHECKS),
                                     return_exceptions=True)
    return sum(r for r in resultats if isinstance(r, int))


async def boucle(registre) -> None:
    """Tâche de fond : vérifie périodiquement (démarrée dans le lifespan du Cœur)."""
    init_db()
    await asyncio.sleep(20)  # laisser les briques démarrer
    while True:
        try:
            nb = await run_check(registre)
            if nb:
                logger.info("Proactif : %d nouveau(x) rappel(s)", nb)
        except Exception as ex:  # noqa: BLE001
            logger.warning("Proactif boucle : %s", ex)
        await asyncio.sleep(INTERVALLE)
