"""Approbations humaines persistantes sur les actions sensibles (S245).

Complète `accord_action.py` SANS le remplacer : le gate conversationnel (un « oui » dans un
fil) reste le mécanisme des 133 actions existantes. Ici, une capacité qui déclare
`sensibilite` dans son manifeste exige une approbation LIÉE À L'ACTION EXACTE (même
empreinte que `accord_action.empreinte`), donnée par un humain autorisé sur Telegram,
persistante, à usage unique, expirante, journalisée.

## Garanti
- Une capacité sensible ne s'exécute que si une approbation `approuvee`, non expirée, de
  même empreinte, est consommée ATOMIQUEMENT (UPDATE … WHERE statut='approuvee').
- Un double clic / double callback ne produit qu'une exécution.
- Toute transition est journalisée dans une table append-only (triggers SQL).

## NON garanti (cf. ADR 2026-11-25-approbation-telegram)
- Que l'humain a COMPRIS l'action : on garantit qu'il a vu le résumé et cliqué.
- La sécurité d'un compte Telegram compromis. D'où le code à 6 chiffres (canal distinct :
  l'app) pour `destructif`, et le TTL court.
- Les capacités sans champ `sensibilite` : comportement inchangé.
"""
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextvars import ContextVar
from pathlib import Path

import accord_action

DB = os.getenv("APPROBATIONS_DB", "/data/approbations.db")

NIVEAUX = ("lecture", "reversible", "donnees", "destructif")
NIVEAUX_SENSIBLES = ("reversible", "donnees", "destructif")
_TTL_DEFAUT_MIN = {"reversible": 30, "donnees": 120, "destructif": 15}
# Après approbation, le LLM (ou le worker) a ce délai pour rappeler l'outil.
FENETRE_EXECUTION_S = 300
ESSAIS_CODE_MAX = 3
TTL_SAISIE_CODE_S = 300
# Un refus récent bloque la redemande identique (sinon le LLM spamme l'humain).
DELAI_APRES_REFUS_S = 600

# Origine du tour courant (métadonnée journalisée) : posée par l'appelant si connue.
ORIGINE: ContextVar[str] = ContextVar("approbation_origine", default="inconnue")

_TRANSITIONS = {
    "en_attente": {"approuvee", "refusee", "expiree"},
    "approuvee": {"executee", "expiree"},
    "executee": {"echec"},
}


def ttl_secondes(niveau: str) -> int:
    """Durée de vie d'une demande, par niveau. Lue à chaque appel (env surchargeable)."""
    minutes = int(os.getenv(f"APPROBATION_TTL_{niveau.upper()}_MIN", _TTL_DEFAUT_MIN[niveau]))
    return minutes * 60


# ── Base ─────────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS approbations (
                id TEXT PRIMARY KEY,
                capacite TEXT NOT NULL,
                empreinte TEXT NOT NULL,
                resume TEXT NOT NULL,
                sensibilite TEXT NOT NULL,
                origine TEXT NOT NULL,
                statut TEXT NOT NULL,
                cree_a REAL NOT NULL,
                expire_a REAL NOT NULL,
                decide_a REAL,
                decide_par TEXT,
                canal TEXT,
                resultat TEXT,
                prerequis TEXT NOT NULL DEFAULT '{}',
                code TEXT,
                essais INTEGER NOT NULL DEFAULT 0,
                nb_relances INTEGER NOT NULL DEFAULT 0,
                relance_a REAL,
                messages TEXT NOT NULL DEFAULT '[]'
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_appr_emp ON approbations(capacite, empreinte, statut)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS approbations_journal (
                n INTEGER PRIMARY KEY AUTOINCREMENT,
                approbation_id TEXT NOT NULL,
                quand REAL NOT NULL,
                evenement TEXT NOT NULL,
                par TEXT,
                canal TEXT,
                detail TEXT
            )""")
        for op in ("UPDATE", "DELETE"):
            c.execute(f"""
                CREATE TRIGGER IF NOT EXISTS journal_no_{op.lower()}
                BEFORE {op} ON approbations_journal
                BEGIN SELECT RAISE(ABORT, 'journal append-only'); END""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS saisie_code (
                approbateur TEXT PRIMARY KEY,
                approbation_id TEXT NOT NULL,
                expire_a REAL NOT NULL
            )""")


def _journaliser(c, id_: str, evenement: str, par=None, canal=None, detail=None,
                 maintenant: float | None = None) -> None:
    c.execute(
        "INSERT INTO approbations_journal (approbation_id, quand, evenement, par, canal, detail) "
        "VALUES (?,?,?,?,?,?)",
        (id_, maintenant if maintenant is not None else time.time(), evenement, par, canal, detail))


def _vue(row) -> dict:
    d = dict(row)
    d["prerequis"] = json.loads(d.get("prerequis") or "{}")
    d["messages"] = json.loads(d.get("messages") or "[]")
    return d


def lire(id_: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM approbations WHERE id=?", (id_,)).fetchone()
    return _vue(r) if r else None


def journal(id_: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM approbations_journal WHERE approbation_id=? ORDER BY n",
                         (id_,)).fetchall()
    return [dict(r) for r in rows]


def _transition(c, id_: str, de: str, vers: str, **colonnes) -> bool:
    """Seul point où `statut` change. Atomique : 0 ligne modifiée = quelqu'un a gagné avant."""
    if vers not in _TRANSITIONS.get(de, set()):
        raise ValueError(f"transition interdite : {de} -> {vers}")
    sets = "".join(f", {k}=?" for k in colonnes)
    cur = c.execute(f"UPDATE approbations SET statut=?{sets} WHERE id=? AND statut=?",
                    (vers, *colonnes.values(), id_, de))
    return cur.rowcount == 1


# ── Création ─────────────────────────────────────────────────────────────────

def creer(capacite: str, args: dict, resume: str, sensibilite: str, origine: str | None = None,
          prerequis: tuple[str, ...] = (), maintenant: float | None = None) -> dict:
    """Crée une demande `en_attente`, ou renvoie celle déjà ouverte pour la même action."""
    if sensibilite not in NIVEAUX_SENSIBLES:
        raise ValueError(f"sensibilité non approuvable : {sensibilite!r}")
    now = maintenant if maintenant is not None else time.time()
    emp = accord_action.empreinte(capacite, args)
    with _conn() as c:
        ex = c.execute(
            "SELECT * FROM approbations WHERE capacite=? AND empreinte=? AND sensibilite=? "
            "AND statut IN ('en_attente','approuvee') AND expire_a>? "
            "ORDER BY cree_a DESC LIMIT 1", (capacite, emp, sensibilite, now)).fetchone()
        if ex:
            return _vue(ex)
        id_ = secrets.token_hex(16)
        code = f"{secrets.randbelow(10 ** 6):06d}" if sensibilite == "destructif" else None
        c.execute(
            "INSERT INTO approbations (id, capacite, empreinte, resume, sensibilite, origine, "
            "statut, cree_a, expire_a, prerequis, code) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (id_, capacite, emp, resume, sensibilite, origine or ORIGINE.get(), "en_attente",
             now, now + ttl_secondes(sensibilite),
             json.dumps({p: False for p in prerequis}), code))
        _journaliser(c, id_, "creee", detail=f"{sensibilite}/{origine or ORIGINE.get()}",
                     maintenant=now)
    return lire(id_)


# ── Décision humaine ─────────────────────────────────────────────────────────

def _expirer_une(c, id_: str, de: str, now: float) -> None:
    if _transition(c, id_, de, "expiree"):
        _journaliser(c, id_, "expiree", maintenant=now)


def approuver(id_: str, par: str, canal: str, maintenant: float | None = None) -> tuple[bool, str]:
    """Approbation par bouton. `destructif` EXIGE le code (cf. `valider_code_saisi`)."""
    now = maintenant if maintenant is not None else time.time()
    with _conn() as c:
        r = c.execute("SELECT * FROM approbations WHERE id=?", (id_,)).fetchone()
        if not r:
            return False, "introuvable"
        if r["statut"] != "en_attente":
            return False, "deja_decidee"
        if r["expire_a"] <= now:
            _expirer_une(c, id_, "en_attente", now)
            return False, "expiree"
        if r["sensibilite"] == "destructif":
            return False, "code_requis"
        if not all(json.loads(r["prerequis"]).values()):
            return False, "prerequis"
        if not _transition(c, id_, "en_attente", "approuvee", decide_a=now, decide_par=par,
                           canal=canal, expire_a=max(r["expire_a"], now + FENETRE_EXECUTION_S)):
            return False, "deja_decidee"
        _journaliser(c, id_, "approuvee", par, canal, maintenant=now)
    return True, "ok"


def refuser(id_: str, par: str, canal: str, maintenant: float | None = None) -> tuple[bool, str]:
    now = maintenant if maintenant is not None else time.time()
    with _conn() as c:
        r = c.execute("SELECT * FROM approbations WHERE id=?", (id_,)).fetchone()
        if not r:
            return False, "introuvable"
        if r["statut"] != "en_attente":
            return False, "deja_decidee"
        if r["expire_a"] <= now:
            _expirer_une(c, id_, "en_attente", now)
            return False, "expiree"
        if not _transition(c, id_, "en_attente", "refusee", decide_a=now, decide_par=par,
                           canal=canal):
            return False, "deja_decidee"
        _journaliser(c, id_, "refusee", par, canal, maintenant=now)
    return True, "ok"
