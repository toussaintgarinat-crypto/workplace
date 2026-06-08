"""Moteur de relances des factures impayées (S22).

Sélectionne les factures `envoyée` échues (J+7/15/30), déduit le niveau de relance
du retard, et envoie une relance par `(facture, niveau)` — **anti-doublon strict**
via un journal SQLite side-car (motif `core/proactif.py`, aucune migration du schéma
Postgres partagé). `apercu()` est un dry-run (n'envoie rien) ; `executer()` envoie
et journalise.

La logique de cadence (`niveau_du`) est pure (testable sans DB ni SMTP).
"""

from __future__ import annotations

import datetime
import logging
import os
import sqlite3
import tempfile

from sqlalchemy import select

from app import email as email_mod
from app.db import SessionLocal
from app.models import FacturesDocs

log = logging.getLogger("forge.relances")

# Statuts considérés « impayé en attente » (parité facturation : 'envoyée'/'envoyé').
_STATUTS_IMPAYES = ("envoyée", "envoyé")
NIVEAUX = (7, 15, 30)

DB_PATH = os.getenv("RELANCES_DB", os.path.join(tempfile.gettempdir(), "forge_relances.db"))


# ── Cadence (pure) ──────────────────────────────────────────────────────────

def niveau_du(jours_retard: int) -> int | None:
    """Niveau de relance dû pour un retard donné : le plus haut seuil atteint.

    <7 j → None ; 7–14 → 7 ; 15–29 → 15 ; ≥30 → 30. Progressif et sans spam :
    combiné à l'anti-doublon `(facture, niveau)`, chaque palier ne part qu'une fois.
    """
    atteints = [n for n in NIVEAUX if jours_retard >= n]
    return max(atteints) if atteints else None


def _parse_date(s: str | None) -> datetime.date | None:
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(s.strip()[:10])
    except (ValueError, AttributeError):
        return None


# ── Journal anti-doublon (SQLite side-car) ─────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS relances_envoyees (
                facture_id TEXT NOT NULL,
                niveau     INTEGER NOT NULL,
                numero     TEXT,
                client     TEXT,
                email      TEXT,
                montant    REAL,
                envoye_le  TEXT NOT NULL,
                PRIMARY KEY (facture_id, niveau)
            )
        """)


def _deja_envoyee(facture_id: str, niveau: int) -> bool:
    with _conn() as c:
        return c.execute(
            "SELECT 1 FROM relances_envoyees WHERE facture_id = ? AND niveau = ? LIMIT 1",
            (facture_id, niveau),
        ).fetchone() is not None


def _journaliser(facture_id: str, niveau: int, *, numero: str, client: str,
                 email: str, montant: float) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO relances_envoyees "
            "(facture_id, niveau, numero, client, email, montant, envoye_le) "
            "VALUES (?,?,?,?,?,?,?)",
            (facture_id, niveau, numero, client, email, montant,
             datetime.datetime.utcnow().isoformat(timespec="seconds")),
        )


def journal_lister(limite: int = 50) -> list[dict]:
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM relances_envoyees ORDER BY envoye_le DESC LIMIT ?", (limite,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Scan / aperçu / exécution ──────────────────────────────────────────────────

async def _factures_impayees(user_id: str) -> list[FacturesDocs]:
    async with SessionLocal() as s:
        return list((await s.execute(
            select(FacturesDocs).where(
                FacturesDocs.user_id == user_id,
                FacturesDocs.type == "facture",
                FacturesDocs.statut.in_(_STATUTS_IMPAYES),
            )
        )).scalars().all())


def _candidat(doc: FacturesDocs, today: datetime.date) -> dict | None:
    """Décrit la relance due pour une facture, ou None si rien à faire.

    Renvoie aussi `raison` quand une facture est ignorée (email/échéance manquants)
    pour que l'aperçu soit honnête plutôt que silencieux.
    """
    ech = _parse_date(doc.date_echeance)
    if not ech:
        return {"ignore": True, "numero": doc.numero, "raison": "échéance absente/illisible"}
    retard = (today - ech).days
    niveau = niveau_du(retard)
    if niveau is None:
        return None  # pas encore échue assez
    if not (doc.client_email or "").strip():
        return {"ignore": True, "numero": doc.numero, "raison": "email client manquant"}
    return {
        "ignore": False,
        "facture_id": str(doc.id),
        "numero": doc.numero,
        "client": doc.client_nom,
        "email": doc.client_email,
        "montant_ttc": doc.total_ttc or 0.0,
        "jours_retard": retard,
        "niveau": niveau,
    }


async def apercu(user_id: str, today: datetime.date | None = None) -> dict:
    """Dry-run : qui serait relancé (et à quel niveau), sans rien envoyer."""
    init_db()
    today = today or datetime.date.today()
    a_relancer, ignorees, deja = [], [], 0
    for doc in await _factures_impayees(user_id):
        c = _candidat(doc, today)
        if c is None:
            continue
        if c.get("ignore"):
            ignorees.append({"numero": c["numero"], "raison": c["raison"]})
            continue
        if _deja_envoyee(c["facture_id"], c["niveau"]):
            deja += 1
            continue
        a_relancer.append(c)
    return {
        "a_relancer": a_relancer,
        "total": len(a_relancer),
        "montant_total": round(sum(c["montant_ttc"] for c in a_relancer), 2),
        "deja_relancees": deja,
        "ignorees": ignorees,
    }


async def executer(user_id: str, today: datetime.date | None = None) -> dict:
    """Envoie les relances dues et les journalise. Tolérant : un échec d'envoi
    n'interrompt pas les autres (il est rapporté)."""
    init_db()
    today = today or datetime.date.today()
    envoyees, echecs = [], []
    for doc in await _factures_impayees(user_id):
        c = _candidat(doc, today)
        if c is None or c.get("ignore"):
            continue
        if _deja_envoyee(c["facture_id"], c["niveau"]):
            continue
        sujet, html = email_mod.template_relance(
            client=c["client"], numero=c["numero"],
            montant_ttc=c["montant_ttc"], niveau=c["niveau"])
        try:
            await email_mod.send(c["email"], sujet, html)
        except Exception as e:  # noqa: BLE001 — par-facture, on continue
            log.warning("Relance %s niveau %s échouée : %s", c["numero"], c["niveau"], e)
            echecs.append({"numero": c["numero"], "niveau": c["niveau"], "erreur": str(e)})
            continue
        _journaliser(c["facture_id"], c["niveau"], numero=c["numero"], client=c["client"],
                     email=c["email"], montant=c["montant_ttc"])
        envoyees.append({"numero": c["numero"], "client": c["client"],
                         "niveau": c["niveau"], "montant_ttc": c["montant_ttc"]})
    return {
        "envoyees": envoyees,
        "nb_envoyees": len(envoyees),
        "montant_relance": round(sum(e["montant_ttc"] for e in envoyees), 2),
        "echecs": echecs,
    }
