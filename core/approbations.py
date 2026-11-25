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


# ── Code à 6 chiffres (destructif) ───────────────────────────────────────────
# Le code n'est JAMAIS envoyé sur Telegram : il est affiché dans l'app (GET /approbations/
# en_attente, session obligatoire). Un compte Telegram compromis seul ne suffit donc pas.

def armer_saisie_code(id_: str, par: str, maintenant: float | None = None) -> tuple[bool, str]:
    """Le bouton Approuver d'un destructif « arme » la saisie : le PROCHAIN message à 6
    chiffres de cet approbateur sera lu comme le code de CETTE demande."""
    now = maintenant if maintenant is not None else time.time()
    with _conn() as c:
        r = c.execute("SELECT * FROM approbations WHERE id=?", (id_,)).fetchone()
        if not r:
            return False, "introuvable"
        if r["sensibilite"] != "destructif":
            return False, "pas_destructif"
        if r["statut"] != "en_attente":
            return False, "deja_decidee"
        if r["expire_a"] <= now:
            _expirer_une(c, id_, "en_attente", now)
            return False, "expiree"
        c.execute("INSERT OR REPLACE INTO saisie_code (approbateur, approbation_id, expire_a) "
                  "VALUES (?,?,?)", (par, id_, now + TTL_SAISIE_CODE_S))
        _journaliser(c, id_, "saisie_code_armee", par, "telegram", maintenant=now)
    return True, "ok"


def valider_code_saisi(par: str, code: str, maintenant: float | None = None) -> dict | None:
    """Vérifie un code saisi. Renvoie None si `par` n'a aucune saisie armée (le message
    n'est alors pas un code : le pont le laisse partir vers l'assistant)."""
    now = maintenant if maintenant is not None else time.time()
    with _conn() as c:
        s = c.execute("SELECT * FROM saisie_code WHERE approbateur=?", (par,)).fetchone()
        if not s:
            return None
        if s["expire_a"] <= now:
            c.execute("DELETE FROM saisie_code WHERE approbateur=?", (par,))
            return None
        id_ = s["approbation_id"]
        r = c.execute("SELECT * FROM approbations WHERE id=?", (id_,)).fetchone()
        if not r or r["statut"] != "en_attente":
            c.execute("DELETE FROM saisie_code WHERE approbateur=?", (par,))
            return {"ok": False, "raison": "deja_decidee", "approbation_id": id_, "restants": 0}
        if r["expire_a"] <= now:
            c.execute("DELETE FROM saisie_code WHERE approbateur=?", (par,))
            _expirer_une(c, id_, "en_attente", now)
            return {"ok": False, "raison": "expiree", "approbation_id": id_, "restants": 0}
        saisi = (code or "").strip()
        # Format strict AVANT toute comparaison : compare_digest(str, str) lève TypeError
        # sur du non-ASCII. Un format invalide est un essai raté, pas un crash.
        format_ok = saisi.isascii() and saisi.isdigit() and len(saisi) == 6
        if format_ok and hmac.compare_digest(saisi.encode(), (r["code"] or "").encode()):
            if not _transition(c, id_, "en_attente", "approuvee", decide_a=now, decide_par=par,
                               canal="telegram+code",
                               expire_a=max(r["expire_a"], now + FENETRE_EXECUTION_S)):
                c.execute("DELETE FROM saisie_code WHERE approbateur=?", (par,))
                return {"ok": False, "raison": "deja_decidee", "approbation_id": id_,
                        "restants": 0}
            c.execute("DELETE FROM saisie_code WHERE approbateur=?", (par,))
            _journaliser(c, id_, "approuvee", par, "telegram+code", maintenant=now)
            return {"ok": True, "raison": "ok", "approbation_id": id_, "restants": 0}
        # Incrément ATOMIQUE (l'UPDATE prend le verrou d'écriture) : pas de lecture-modif-écriture.
        cur = c.execute("UPDATE approbations SET essais=essais+1 WHERE id=? AND statut='en_attente'",
                        (id_,))
        if cur.rowcount != 1:
            c.execute("DELETE FROM saisie_code WHERE approbateur=?", (par,))
            return {"ok": False, "raison": "deja_decidee", "approbation_id": id_, "restants": 0}
        essais = c.execute("SELECT essais FROM approbations WHERE id=?", (id_,)).fetchone()["essais"]
        _journaliser(c, id_, "code_faux", par, "telegram", detail=f"essai {essais}",
                     maintenant=now)
        if essais >= ESSAIS_CODE_MAX:
            _transition(c, id_, "en_attente", "refusee", decide_a=now, decide_par=par,
                        canal="telegram+code")
            c.execute("DELETE FROM saisie_code WHERE approbateur=?", (par,))
            _journaliser(c, id_, "refusee", par, "telegram+code", detail="essais épuisés",
                         maintenant=now)
            return {"ok": False, "raison": "essais_epuises", "approbation_id": id_, "restants": 0}
        return {"ok": False, "raison": "code_faux", "approbation_id": id_,
                "restants": ESSAIS_CODE_MAX - essais}


# ── Prérequis (utilisés dès S247 : « sauvegarde vérifiée ») ──────────────────

def satisfaire_prerequis(id_: str, nom: str) -> bool:
    """Marque un prérequis comme réuni. True ssi TOUS le sont désormais."""
    with _conn() as c:
        r = c.execute("SELECT prerequis FROM approbations WHERE id=?", (id_,)).fetchone()
        if not r:
            return False
        p = json.loads(r["prerequis"])
        if nom in p:
            p[nom] = True
            c.execute("UPDATE approbations SET prerequis=? WHERE id=?", (json.dumps(p), id_))
            _journaliser(c, id_, "prerequis_satisfait", detail=nom)
        return bool(p) and all(p.values())


# ── Exécution ────────────────────────────────────────────────────────────────

def consommer(capacite: str, args: dict, niveau: str | None = None,
              maintenant: float | None = None) -> str | None:
    """Consomme une approbation `approuvee` de même empreinte. ATOMIQUE : l'UPDATE conditionnel
    est l'arbitre ; si deux appels concurrents la visent, un seul modifie 1 ligne.
    Si `niveau` est donné, seule une approbation de CE niveau est consommable : une approbation
    `reversible` ne débloque jamais un `destructif` (même action, même empreinte)."""
    now = maintenant if maintenant is not None else time.time()
    emp = accord_action.empreinte(capacite, args)
    filtre = "" if niveau is None else " AND sensibilite=?"
    extra = () if niveau is None else (niveau,)
    with _conn() as c:
        ids = [r["id"] for r in c.execute(
            "SELECT id FROM approbations WHERE capacite=? AND empreinte=? AND statut='approuvee' "
            "AND expire_a>?" + filtre + " ORDER BY decide_a", (capacite, emp, now, *extra))]
        for id_ in ids:
            cur = c.execute(
                "UPDATE approbations SET statut='executee' "
                "WHERE id=? AND statut='approuvee' AND expire_a>?" + filtre,
                (id_, now, *extra))
            if cur.rowcount == 1:
                _journaliser(c, id_, "executee", maintenant=now)
                return id_
    return None


def conclure(id_: str, ok: bool, resultat: str) -> None:
    """Note le résultat de l'exécution ; un échec fait passer `executee` à `echec`."""
    with _conn() as c:
        if ok:
            c.execute("UPDATE approbations SET resultat=? WHERE id=?", ((resultat or "")[:500], id_))
            return
        if _transition(c, id_, "executee", "echec", resultat=(resultat or "")[:500]):
            _journaliser(c, id_, "echec", detail=(resultat or "")[:200])


# ── Expiration, attente, relance (mode attente, approche B) ──────────────────

def expirer_perimees(maintenant: float | None = None) -> list[str]:
    now = maintenant if maintenant is not None else time.time()
    faites: list[str] = []
    with _conn() as c:
        for r in c.execute("SELECT id, statut FROM approbations WHERE statut IN "
                           "('en_attente','approuvee') AND expire_a<=?", (now,)).fetchall():
            if _transition(c, r["id"], r["statut"], "expiree"):
                _journaliser(c, r["id"], "expiree", maintenant=now)
                faites.append(r["id"])
        c.execute("DELETE FROM saisie_code WHERE expire_a<=?", (now,))
    return faites


def en_attente() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM approbations WHERE statut='en_attente' "
                         "ORDER BY cree_a").fetchall()
    return [_vue(r) for r in rows]


def a_relancer(delai_s: int, max_relances: int, maintenant: float | None = None) -> list[dict]:
    now = maintenant if maintenant is not None else time.time()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM approbations WHERE statut='en_attente' AND expire_a>? "
            "AND nb_relances<? AND COALESCE(relance_a, cree_a)+?<=? ORDER BY cree_a",
            (now, max_relances, delai_s, now)).fetchall()
    return [_vue(r) for r in rows]


def marquer_relancee(id_: str, maintenant: float | None = None) -> None:
    now = maintenant if maintenant is not None else time.time()
    with _conn() as c:
        c.execute("UPDATE approbations SET nb_relances=nb_relances+1, relance_a=? WHERE id=?",
                  (now, id_))
        _journaliser(c, id_, "relancee", maintenant=now)


def enregistrer_messages(id_: str, messages: list[dict]) -> None:
    """Mémorise les messages Telegram (chat_id, message_id) pour pouvoir les éditer ensuite."""
    with _conn() as c:
        c.execute("UPDATE approbations SET messages=? WHERE id=?", (json.dumps(messages), id_))


# ── La garde ─────────────────────────────────────────────────────────────────

def _derniere(capacite: str, args: dict, statuts: tuple[str, ...], niveau: str) -> dict | None:
    emp = accord_action.empreinte(capacite, args)
    marques = ",".join("?" * len(statuts))
    with _conn() as c:
        r = c.execute(f"SELECT * FROM approbations WHERE capacite=? AND empreinte=? "
                      f"AND sensibilite=? AND statut IN ({marques}) ORDER BY cree_a DESC LIMIT 1",
                      (capacite, emp, niveau, *statuts)).fetchone()
    return _vue(r) if r else None


def exiger(capacite: str, args: dict, niveau: str, resume: str,
           maintenant: float | None = None) -> tuple[str | None, str | None, dict | None]:
    """Cœur de la garde. Renvoie (id_consomme, message_pour_le_llm, demande_creee).

    - une approbation valide existe  -> elle est CONSOMMÉE, l'appelant exécute ;
    - une demande est déjà ouverte   -> message d'attente, pas de doublon ;
    - un refus très récent           -> message de refus, pas de redemande ;
    - sinon                          -> une demande est créée (l'appelant la notifie)."""
    now = maintenant if maintenant is not None else time.time()
    id_ = consommer(capacite, args, niveau=niveau, maintenant=now)
    if id_:
        return id_, None, None
    ouverte = _derniere(capacite, args, ("en_attente",), niveau)
    if ouverte and ouverte["expire_a"] > now:
        return None, (
            f"Action `{capacite}` NON exécutée : la demande d'approbation {ouverte['id'][:8]} "
            "attend la réponse de l'humain sur Telegram. N'insiste pas et n'essaie pas de "
            "contourner : dis à l'utilisateur que tu attends son approbation."), None
    refusee = _derniere(capacite, args, ("refusee",), niveau)
    if refusee and (refusee["decide_a"] or 0) + DELAI_APRES_REFUS_S > now:
        return None, (
            f"Action `{capacite}` NON exécutée : l'humain a REFUSÉ cette action. Ne la "
            "redemande pas ; propose une alternative ou demande-lui ce qu'il veut."), None
    demande = creer(capacite, args, resume, niveau, maintenant=now)
    return None, (
        f"Action `{capacite}` NON exécutée : une demande d'approbation ({demande['id'][:8]}, "
        f"niveau {niveau}) vient d'être envoyée à l'humain sur Telegram. Dis-lui que tu "
        "attends son approbation. Quand il aura approuvé, rappelle le MÊME outil avec les "
        "MÊMES arguments."), demande
