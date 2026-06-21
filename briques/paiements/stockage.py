"""Persistance de la brique paiements (SQLite). Tout est cloisonné par `solution` (le tenant) :
une solution ne voit JAMAIS les comptes connectés ni les paiements d'une autre (fail-closed,
404 plutôt que 403 → on ne révèle pas l'existence). Le `solution` est dérivé de la clé API
(sha256 tronqué) côté `main.py` : la clé reste le secret, jamais stockée en clair.

Pur SQL + stdlib (sqlite3, uuid). Aucune logique métier ici : les calculs/transitions vivent
dans `domaine.py`, les appels prestataires dans `fournisseurs.py`."""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone

_DB = os.getenv("PAIEMENTS_DB", "/data/paiements.db")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return uuid.uuid4().hex


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init() -> None:
    """Crée le schéma si besoin (idempotent)."""
    os.makedirs(os.path.dirname(_DB) or ".", exist_ok=True)
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS comptes_connectes (
                id TEXT PRIMARY KEY, solution TEXT NOT NULL, ref_externe TEXT,
                nom TEXT, email TEXT, pays TEXT DEFAULT 'FR',
                statut TEXT NOT NULL DEFAULT 'cree', cree_le TEXT);
            CREATE INDEX IF NOT EXISTS idx_cc_solution ON comptes_connectes(solution);
            CREATE INDEX IF NOT EXISTS idx_cc_ref ON comptes_connectes(ref_externe);

            CREATE TABLE IF NOT EXISTS paiements (
                id TEXT PRIMARY KEY, solution TEXT NOT NULL, compte_id TEXT NOT NULL,
                ref_externe TEXT, montant_cents INTEGER NOT NULL, commission_cents INTEGER NOT NULL,
                net_cents INTEGER NOT NULL, devise TEXT NOT NULL DEFAULT 'EUR',
                statut TEXT NOT NULL DEFAULT 'cree', description TEXT DEFAULT '',
                cree_le TEXT, maj_le TEXT);
            CREATE INDEX IF NOT EXISTS idx_paie_solution ON paiements(solution);
            CREATE INDEX IF NOT EXISTS idx_paie_ref ON paiements(ref_externe);
            """
        )


# Schéma prêt dès l'import (idempotent) : robuste même sans événement de démarrage (TestClient).
init()


def _compte_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "ref_externe": r["ref_externe"], "nom": r["nom"], "email": r["email"],
            "pays": r["pays"], "statut": r["statut"], "cree_le": r["cree_le"]}


def _paiement_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "compte_id": r["compte_id"], "ref_externe": r["ref_externe"],
            "montant_cents": r["montant_cents"], "commission_cents": r["commission_cents"],
            "net_cents": r["net_cents"], "devise": r["devise"], "statut": r["statut"],
            "description": r["description"] or "", "cree_le": r["cree_le"], "maj_le": r["maj_le"]}


# ── Comptes connectés (vendeurs) ─────────────────────────────────
def creer_compte(solution: str, ref_externe: str, statut: str, *, nom: str = "",
                 email: str = "", pays: str = "FR") -> dict:
    cid = _id()
    with _conn() as c:
        c.execute("INSERT INTO comptes_connectes (id, solution, ref_externe, nom, email, pays, "
                  "statut, cree_le) VALUES (?,?,?,?,?,?,?,?)",
                  (cid, solution, ref_externe, nom, email, pays, statut, _maintenant()))
        r = c.execute("SELECT * FROM comptes_connectes WHERE id=?", (cid,)).fetchone()
    return _compte_dict(r)


def lire_compte(solution: str, compte_id: str) -> dict | None:
    """Cloisonné : un compte d'une AUTRE solution renvoie None (invisible)."""
    with _conn() as c:
        r = c.execute("SELECT * FROM comptes_connectes WHERE id=? AND solution=?",
                      (compte_id, solution)).fetchone()
    return _compte_dict(r) if r else None


def lister_comptes(solution: str) -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM comptes_connectes WHERE solution=? ORDER BY cree_le DESC",
                         (solution,)).fetchall()
    return [_compte_dict(r) for r in rows]


def maj_statut_compte(compte_id: str, statut: str) -> None:
    with _conn() as c:
        c.execute("UPDATE comptes_connectes SET statut=? WHERE id=?", (statut, compte_id))


def compte_par_ref(ref_externe: str) -> dict | None:
    """Retrouve un compte par sa référence prestataire (pour les webhooks, non scopé)."""
    with _conn() as c:
        r = c.execute("SELECT * FROM comptes_connectes WHERE ref_externe=?", (ref_externe,)).fetchone()
    return (_compte_dict(r) | {"solution": r["solution"], "id": r["id"]}) if r else None


# ── Paiements ────────────────────────────────────────────────────
def creer_paiement(solution: str, compte_id: str, ref_externe: str, montant_cents: int,
                   commission_cents: int, net_cents: int, devise: str, statut: str,
                   description: str = "") -> dict:
    pid = _id()
    now = _maintenant()
    with _conn() as c:
        c.execute("INSERT INTO paiements (id, solution, compte_id, ref_externe, montant_cents, "
                  "commission_cents, net_cents, devise, statut, description, cree_le, maj_le) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (pid, solution, compte_id, ref_externe, montant_cents, commission_cents,
                   net_cents, devise, statut, description, now, now))
        r = c.execute("SELECT * FROM paiements WHERE id=?", (pid,)).fetchone()
    return _paiement_dict(r)


def lire_paiement(solution: str, paiement_id: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM paiements WHERE id=? AND solution=?",
                      (paiement_id, solution)).fetchone()
    return _paiement_dict(r) if r else None


def lister_paiements(solution: str) -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM paiements WHERE solution=? ORDER BY cree_le DESC",
                         (solution,)).fetchall()
    return [_paiement_dict(r) for r in rows]


def maj_statut_paiement(paiement_id: str, statut: str, ref_externe: str | None = None) -> None:
    with _conn() as c:
        if ref_externe is not None:
            c.execute("UPDATE paiements SET statut=?, ref_externe=?, maj_le=? WHERE id=?",
                      (statut, ref_externe, _maintenant(), paiement_id))
        else:
            c.execute("UPDATE paiements SET statut=?, maj_le=? WHERE id=?",
                      (statut, _maintenant(), paiement_id))


def paiement_par_ref(ref_externe: str) -> dict | None:
    """Retrouve un paiement par sa référence prestataire (pour les webhooks, non scopé)."""
    with _conn() as c:
        r = c.execute("SELECT * FROM paiements WHERE ref_externe=?", (ref_externe,)).fetchone()
    return (_paiement_dict(r) | {"solution": r["solution"]}) if r else None
