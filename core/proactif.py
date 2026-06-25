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

# Fenêtre de balayage : assez large pour attraper un rappel « 1 semaine avant »
# (le plus long preset). On ne lève le 🔔 que lorsque CHAQUE rappel devient dû.
FENETRE_AGENDA_JOURS = 8


def _delai_lisible(minutes: int) -> str:
    """« 0 → à l'heure », « 30 → dans 30 min », « 60 → dans 1 h », « 1440 → dans 1 j »."""
    if minutes <= 0:
        return "maintenant"
    if minutes < 60:
        return f"dans {minutes} min"
    if minutes < 1440:
        h = minutes / 60
        return f"dans {int(h)} h" if h == int(h) else f"dans {h:.1f} h"
    j = minutes / 1440
    return f"dans {int(j)} j" if j == int(j) else f"dans {j:.1f} j"


def _rappels_dus(evt: dict, maintenant: datetime):
    """Rappels d'un événement qui sont dus MAINTENANT (générateur de (minutes, debut)).

    Un rappel `m` est dû si `maintenant >= debut - m` et que l'événement n'a pas encore
    commencé (`maintenant <= debut`). Pur (aucune I/O) → testable directement.
    """
    rappels = evt.get("rappels") or []
    debut_iso = evt.get("start_at") or ""
    try:
        debut = datetime.fromisoformat(debut_iso)
    except (ValueError, TypeError):
        return
    # La brique renvoie l'heure en Europe/Paris (avec offset) ; on la ramène à
    # l'heure murale locale pour comparer à `maintenant` (datetime.now(), naïf local).
    if debut.tzinfo is not None:
        debut = debut.replace(tzinfo=None)
    for m in rappels:
        try:
            m = int(m)
        except (ValueError, TypeError):
            continue
        fire_at = debut - timedelta(minutes=m)
        if maintenant >= fire_at and maintenant <= debut:
            yield m, debut


async def _check_agenda(registre) -> int:
    """Lève un 🔔 (et un push messagerie) pour chaque rappel configuré devenu dû.

    Les rappels sont configurés PAR ÉVÉNEMENT dans la brique agenda (liste de minutes
    avant le début). Aucun rappel par défaut : un événement sans `rappels` ne sonne pas.
    Dédoublonnage par (événement, minutes) → chaque rappel ne sonne qu'une fois.
    """
    n = 0
    try:
        maintenant = datetime.now()
        fin = maintenant + timedelta(days=FENETRE_AGENDA_JOURS)
        evts = await agenda.lister_evenements(
            registre, maintenant.isoformat(), fin.isoformat())
        for e in evts:
            titre_evt = e.get("title", "(sans titre)")
            heure = (e.get("start_at") or "")[11:16]
            lieu = f" — {e.get('location')}" if e.get("location") else ""
            for m, _debut in _rappels_dus(e, maintenant):
                titre = f"Rappel : {titre_evt}"
                corps = f"{_delai_lisible(m).capitalize()} (à {heure}){lieu}"
                if _ajouter("agenda", titre, corps, f"agenda:{e.get('id')}:{m}"):
                    n += 1
                    await _pousser_messagerie(registre, titre, corps)
    except Exception as ex:  # noqa: BLE001
        logger.warning("Proactif agenda : %s", ex)
    return n


async def _pousser_messagerie(registre, titre: str, corps: str) -> None:
    """Pousse un rappel vers les messageries de l'utilisateur (Telegram…) via le pont.

    Best-effort : si la brique « connexion » est absente du registre ou injoignable, on
    ignore silencieusement — le 🔔 du dashboard reste, lui, en place. Ne lève jamais.
    """
    try:
        base = orchestrateur._brique_base(registre, "connexion")
    except Exception:  # noqa: BLE001 — brique non déclarée → pas de push, c'est tout
        return
    entetes = {}
    cle = os.getenv("CONNEXION_KEY", "")
    if cle:
        entetes["X-API-Key"] = cle
    corps_push = {"utilisateur": agenda.USER_ID, "texte": f"🔔 {titre}\n{corps}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{base}/pousser", json=corps_push, headers=entetes)
    except Exception as ex:  # noqa: BLE001
        logger.warning("Proactif push messagerie : %s", ex)


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
