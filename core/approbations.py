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
import logging
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

import accord_action
import contexte_tenant

logger = logging.getLogger(__name__)

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

# Après exécution réussie, la même action (même utilisateur) n'est pas redemandée pendant ce
# délai : le LLM qui « rappelle l'outil » par habitude ne déclenche pas un 2e cycle humain.
DELAI_APRES_EXECUTION_S = 300
# Pose l'id de l'approbation en cours de REPRISE (exécution par le Cœur après approbation).
REPRISE: ContextVar[str | None] = ContextVar("approbation_reprise", default=None)

_TRANSITIONS = {
    "en_attente": {"approuvee", "refusee", "expiree"},
    "approuvee": {"executee", "expiree"},
    "executee": {"echec"},
}


def ttl_secondes(niveau: str) -> int:
    """Durée de vie d'une demande, par niveau. Lue à chaque appel (env surchargeable)."""
    nom = f"APPROBATION_TTL_{niveau.upper()}_MIN"
    try:
        minutes = int(os.getenv(nom, _TTL_DEFAUT_MIN[niveau]))
        if minutes <= 0:
            raise ValueError("TTL <= 0")
    except (TypeError, ValueError):
        minutes = _TTL_DEFAUT_MIN[niveau]
        logger.warning("%s invalide (entier > 0 attendu), repli sur %s min", nom, minutes)
    return minutes * 60


@contextmanager
def avec_origine(origine: str):
    """Pose l'origine du tour pour les demandes créées dans le bloc (ContextVar set/reset)."""
    jeton = ORIGINE.set(origine)
    try:
        yield
    finally:
        ORIGINE.reset(jeton)


@contextmanager
def avec_reprise(id_: str):
    """Pose l'id de l'approbation reprise : `exiger` consomme CET id, sans jamais créer de demande."""
    jeton = REPRISE.set(id_)
    try:
        yield
    finally:
        REPRISE.reset(jeton)


def _utilisateur(explicite: str | None) -> str:
    """Utilisateur de la demande : l'explicite, sinon celui du tour courant (contexte tenant)."""
    return explicite or contexte_tenant.contexte_actuel().utilisateur


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
                messages TEXT NOT NULL DEFAULT '[]',
                utilisateur TEXT NOT NULL DEFAULT 'perso',
                org_id TEXT,
                args TEXT
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
        # S245b : colonnes ajoutées à une base S245 déjà déployée (ALTER idempotent).
        existantes = {r["name"] for r in c.execute("PRAGMA table_info(approbations)")}
        for nom, ddl in (("utilisateur", "TEXT NOT NULL DEFAULT 'perso'"),
                         ("org_id", "TEXT"), ("args", "TEXT")):
            if nom not in existantes:
                _ajouter_colonne(c, "approbations", nom, ddl)
        c.execute("CREATE INDEX IF NOT EXISTS idx_appr_user ON approbations(utilisateur, statut)")


def _ajouter_colonne(c, table: str, nom: str, ddl: str) -> None:
    """ALTER TABLE ADD COLUMN tolérant à un autre processus qui l'aurait ajoutée avant nous."""
    try:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {nom} {ddl}")
    except sqlite3.OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise


def _journaliser(c, id_: str, evenement: str, par=None, canal=None, detail=None,
                 maintenant: float | None = None) -> None:
    c.execute(
        "INSERT INTO approbations_journal (approbation_id, quand, evenement, par, canal, detail) "
        "VALUES (?,?,?,?,?,?)",
        (id_, maintenant if maintenant is not None else time.time(), evenement, par, canal, detail))


def _vue(row) -> dict:
    d = dict(row)
    d.pop("args", None)          # S245b : arguments réels jamais exposés (cf. `args_de`)
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


_ETATS_FINAUX = ("refusee", "expiree", "echec", "executee")


def _transition(c, id_: str, de: str, vers: str, **colonnes) -> bool:
    """Seul point où `statut` change. Atomique : 0 ligne modifiée = quelqu'un a gagné avant.
    Toute sortie vers un état final purge les `args` réels (S245b)."""
    if vers not in _TRANSITIONS.get(de, set()):
        raise ValueError(f"transition interdite : {de} -> {vers}")
    if vers in _ETATS_FINAUX:
        colonnes = {**colonnes, "args": None}
    sets = "".join(f", {k}=?" for k in colonnes)
    cur = c.execute(f"UPDATE approbations SET statut=?{sets} WHERE id=? AND statut=?",
                    (vers, *colonnes.values(), id_, de))
    return cur.rowcount == 1


# ── Création ─────────────────────────────────────────────────────────────────

def creer(capacite: str, args: dict, resume: str, sensibilite: str, origine: str | None = None,
          prerequis: tuple[str, ...] = (), maintenant: float | None = None, *,
          utilisateur: str | None = None, org_id: str | None = None) -> dict:
    """Crée une demande `en_attente`, ou renvoie celle déjà ouverte pour la même action ET le
    même utilisateur. Les `args` exacts sont conservés pour la reprise (purgés à l'état final)."""
    if sensibilite not in NIVEAUX_SENSIBLES:
        raise ValueError(f"sensibilité non approuvable : {sensibilite!r}")
    now = maintenant if maintenant is not None else time.time()
    emp = accord_action.empreinte(capacite, args)
    user = _utilisateur(utilisateur)
    org = org_id or contexte_tenant.contexte_actuel().org_id
    with _conn() as c:
        # Verrou d'écriture AVANT la lecture des preuves : une preuve qui arrive entre la lecture
        # et l'INSERT ne peut plus laisser un drapeau False périmé.
        c.execute("BEGIN IMMEDIATE")
        ex = c.execute(
            "SELECT * FROM approbations WHERE capacite=? AND empreinte=? AND sensibilite=? "
            "AND utilisateur=? AND statut IN ('en_attente','approuvee') AND expire_a>? "
            "ORDER BY cree_a DESC LIMIT 1", (capacite, emp, sensibilite, user, now)).fetchone()
        if ex:
            return _vue(ex)
        deja = {p: _preuve_valide_c(c, p, (args or {}).get("app"), user, now) for p in prerequis}
        id_ = secrets.token_hex(16)
        code = f"{secrets.randbelow(10 ** 6):06d}" if sensibilite == "destructif" else None
        c.execute(
            "INSERT INTO approbations (id, capacite, empreinte, resume, sensibilite, origine, "
            "statut, cree_a, expire_a, prerequis, code, utilisateur, org_id, args) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (id_, capacite, emp, resume, sensibilite, origine or ORIGINE.get(), "en_attente",
             now, now + ttl_secondes(sensibilite),
             json.dumps(deja), code, user, org,
             json.dumps(args or {}, default=str)))
        _journaliser(c, id_, "creee",
                     detail=f"{sensibilite}/{origine or ORIGINE.get()}/{user}", maintenant=now)
    return lire(id_)


# ── Décision humaine ─────────────────────────────────────────────────────────

def _expirer_une(c, id_: str, de: str, now: float) -> None:
    if _transition(c, id_, de, "expiree"):
        _journaliser(c, id_, "expiree", maintenant=now)


def _pas_a_lui(c, r, id_: str, par: str, canal: str, utilisateur: str, now: float) -> bool:
    """True (et journalise) si la demande appartient à un AUTRE utilisateur que `utilisateur`.
    L'appelant répond « introuvable » : on ne révèle pas l'existence d'une demande d'autrui."""
    if r["utilisateur"] == utilisateur:
        return False
    _journaliser(c, id_, "refus_autre_utilisateur", par, canal,
                 detail=f"demandeur={r['utilisateur']} approbateur={utilisateur}", maintenant=now)
    return True


def approuver(id_: str, par: str, canal: str, maintenant: float | None = None, *,
              utilisateur: str) -> tuple[bool, str]:
    """Approbation par bouton. `destructif` EXIGE le code (cf. `valider_code_saisi`)."""
    now = maintenant if maintenant is not None else time.time()
    with _conn() as c:
        r = c.execute("SELECT * FROM approbations WHERE id=?", (id_,)).fetchone()
        if not r:
            return False, "introuvable"
        if _pas_a_lui(c, r, id_, par, canal, utilisateur, now):
            return False, "introuvable"
        if r["statut"] != "en_attente":
            return False, "deja_decidee"
        if r["expire_a"] <= now:
            _expirer_une(c, id_, "en_attente", now)
            return False, "expiree"
        if r["sensibilite"] == "destructif":
            return False, "code_requis"
        if not _prerequis_tenus(c, r, _args_de_ligne(r), now):
            return False, "prerequis"
        if not _transition(c, id_, "en_attente", "approuvee", decide_a=now, decide_par=par,
                           canal=canal, expire_a=max(r["expire_a"], now + FENETRE_EXECUTION_S)):
            return False, "deja_decidee"
        _journaliser(c, id_, "approuvee", par, canal, maintenant=now)
    return True, "ok"


def refuser(id_: str, par: str, canal: str, maintenant: float | None = None, *,
            utilisateur: str) -> tuple[bool, str]:
    now = maintenant if maintenant is not None else time.time()
    with _conn() as c:
        r = c.execute("SELECT * FROM approbations WHERE id=?", (id_,)).fetchone()
        if not r:
            return False, "introuvable"
        if _pas_a_lui(c, r, id_, par, canal, utilisateur, now):
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

def armer_saisie_code(id_: str, par: str, maintenant: float | None = None, *,
                      utilisateur: str) -> tuple[bool, str]:
    """Le bouton Approuver d'un destructif « arme » la saisie : le PROCHAIN message à 6
    chiffres de cet approbateur sera lu comme le code de CETTE demande."""
    now = maintenant if maintenant is not None else time.time()
    with _conn() as c:
        r = c.execute("SELECT * FROM approbations WHERE id=?", (id_,)).fetchone()
        if not r:
            return False, "introuvable"
        if _pas_a_lui(c, r, id_, par, "telegram", utilisateur, now):
            return False, "introuvable"
        if r["sensibilite"] != "destructif":
            return False, "pas_destructif"
        if r["statut"] != "en_attente":
            return False, "deja_decidee"
        if r["expire_a"] <= now:
            _expirer_une(c, id_, "en_attente", now)
            return False, "expiree"
        if not _prerequis_tenus(c, r, _args_de_ligne(r), now):
            return False, "prerequis"
        c.execute("INSERT OR REPLACE INTO saisie_code (approbateur, approbation_id, expire_a) "
                  "VALUES (?,?,?)", (par, id_, now + TTL_SAISIE_CODE_S))
        _journaliser(c, id_, "saisie_code_armee", par, "telegram", maintenant=now)
    return True, "ok"


def valider_code_saisi(par: str, code: str, maintenant: float | None = None, *,
                       utilisateur: str) -> dict | None:
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
        if r and r["utilisateur"] != utilisateur:
            c.execute("DELETE FROM saisie_code WHERE approbateur=?", (par,))
            _journaliser(c, id_, "refus_autre_utilisateur", par, "telegram",
                         detail=f"demandeur={r['utilisateur']} approbateur={utilisateur}",
                         maintenant=now)
            return None
        if not r or r["statut"] != "en_attente":
            c.execute("DELETE FROM saisie_code WHERE approbateur=?", (par,))
            return {"ok": False, "raison": "deja_decidee", "approbation_id": id_, "restants": 0}
        if r["expire_a"] <= now:
            c.execute("DELETE FROM saisie_code WHERE approbateur=?", (par,))
            _expirer_une(c, id_, "en_attente", now)
            return {"ok": False, "raison": "expiree", "approbation_id": id_, "restants": 0}
        if not _prerequis_tenus(c, r, _args_de_ligne(r), now):
            # Prérequis non réunis : jamais d'approbation, pas un essai raté, saisie désarmée.
            c.execute("DELETE FROM saisie_code WHERE approbateur=?", (par,))
            return {"ok": False, "raison": "prerequis", "approbation_id": id_, "restants": 0}
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
        c.execute("BEGIN IMMEDIATE")
        r = c.execute("SELECT prerequis FROM approbations WHERE id=?", (id_,)).fetchone()
        if not r:
            return False
        p = json.loads(r["prerequis"])
        if nom in p:
            p[nom] = True
            c.execute("UPDATE approbations SET prerequis=? WHERE id=?", (json.dumps(p), id_))
            _journaliser(c, id_, "prerequis_satisfait", detail=nom)
        return bool(p) and all(p.values())


# ── Preuves (S247 : « sauvegarde vérifiée ») ─────────────────────────────────

PREUVE_TTL_MAX_S = 24 * 3600


def _norm_cle(cle) -> str:
    return str(cle or "").strip().lower()


def _assurer_preuves(c) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS preuves (
                    nom TEXT NOT NULL, cle TEXT NOT NULL, utilisateur TEXT NOT NULL,
                    preuve_id TEXT NOT NULL, expire_a REAL NOT NULL,
                    PRIMARY KEY (nom, cle, utilisateur))""")


def _preuve_valide_c(c, nom: str, cle, utilisateur: str, maintenant: float) -> bool:
    _assurer_preuves(c)
    r = c.execute("SELECT expire_a FROM preuves WHERE nom=? AND cle=? AND utilisateur=?",
                  (nom, _norm_cle(cle), utilisateur)).fetchone()
    return bool(r and r["expire_a"] > maintenant)


def preuve_valide(nom: str, cle: str, utilisateur: str, maintenant: float) -> bool:
    with _conn() as c:
        return _preuve_valide_c(c, nom, cle, utilisateur, maintenant)


def _args_de_ligne(r) -> dict:
    try:
        v = json.loads(r["args"] or "{}")
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def _prerequis_tenus(c, r, args: dict, now: float) -> bool:
    """Revérifie, à l'INSTANT de l'usage, chaque prérequis déclaré : drapeau levé ET preuve encore
    valide. Un drapeau dont la preuve a expiré ou été révoquée est rebaissé en base (fail closed).
    Sans prérequis déclaré : toujours vrai (comportement historique)."""
    p = json.loads(r["prerequis"] or "{}")
    if not p:
        return True
    changes = False
    for nom, v in p.items():
        # La PREUVE fait foi, pas le drapeau : une preuve disparue ou expirée rebaisse le drapeau ;
        # une preuve valide (ex. nouvelle vérification après l'approbation) le relève, sinon une
        # approbation `approuvee` resterait bloquée jusqu'à son expiration.
        tenu = _preuve_valide_c(c, nom, (args or {}).get("app"), r["utilisateur"], now)
        if tenu != bool(v):
            p[nom] = tenu
            changes = True
    if changes:
        c.execute("UPDATE approbations SET prerequis=? WHERE id=?", (json.dumps(p), r["id"]))
        _journaliser(c, r["id"], "prerequis_perdu" if not all(p.values()) else "prerequis_retabli",
                     maintenant=now)
    return all(p.values())


def revoquer_preuve(nom: str, cles: list[str], *, utilisateur: str | None = None) -> list[str]:
    """Annule la preuve (verdict `invalide` plus récent) : supprime l'enregistrement et rebaisse le
    drapeau sur les demandes `en_attente`/`approuvee` de CET utilisateur visant ces apps."""
    user = _utilisateur(utilisateur)
    cles_n = {_norm_cle(k) for k in cles if _norm_cle(k)}
    if not cles_n:
        return []
    baissees = []
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        _assurer_preuves(c)
        for k in cles_n:
            c.execute("DELETE FROM preuves WHERE nom=? AND cle=? AND utilisateur=?", (nom, k, user))
        for r in c.execute("SELECT id, prerequis, args FROM approbations WHERE utilisateur=? "
                           "AND statut IN ('en_attente','approuvee')", (user,)).fetchall():
            try:
                cle_demande = _norm_cle(json.loads(r["args"] or "{}").get("app"))
                prereq = json.loads(r["prerequis"] or "{}")
            except (ValueError, AttributeError):
                continue
            if cle_demande in cles_n and prereq.get(nom) is True:
                prereq[nom] = False
                c.execute("UPDATE approbations SET prerequis=? WHERE id=?",
                          (json.dumps(prereq), r["id"]))
                _journaliser(c, r["id"], "prerequis_revoque", detail=nom)
                baissees.append(r["id"])
    return baissees


def enregistrer_preuve(nom: str, cles: list[str], preuve_id: str, expire_a: float, *,
                       utilisateur: str | None = None,
                       maintenant: float | None = None) -> list[str]:
    """Enregistre une preuve (par utilisateur ET par clé d'app) puis lève ce prérequis sur les
    demandes `en_attente` de CET utilisateur visant cette app. Renvoie les ids des demandes dont
    tous les prérequis sont désormais réunis (à renotifier avec boutons)."""
    now = maintenant if maintenant is not None else time.time()
    user = _utilisateur(utilisateur)
    expire_a = min(float(expire_a), now + PREUVE_TTL_MAX_S)
    cles_n = {_norm_cle(k) for k in cles if _norm_cle(k)}
    if expire_a <= now or not cles_n or not preuve_id:
        return []
    with _conn() as c:
        _assurer_preuves(c)
        for k in cles_n:
            c.execute("INSERT OR REPLACE INTO preuves (nom, cle, utilisateur, preuve_id, expire_a) "
                      "VALUES (?,?,?,?,?)", (nom, k, user, preuve_id, expire_a))
        rows = c.execute(
            "SELECT id, prerequis, args FROM approbations WHERE statut='en_attente' "
            "AND utilisateur=? AND expire_a>?", (user, now)).fetchall()
    liberees = []
    for r in rows:
        try:
            cle_demande = _norm_cle(json.loads(r["args"] or "{}").get("app"))
            prereq = json.loads(r["prerequis"] or "{}")
        except (ValueError, AttributeError):
            continue
        if cle_demande in cles_n and prereq.get(nom) is False:
            if satisfaire_prerequis(r["id"], nom):
                liberees.append(r["id"])
    return liberees


# ── Exécution ────────────────────────────────────────────────────────────────

def consommer(capacite: str, args: dict, niveau: str | None = None,
              maintenant: float | None = None, *, utilisateur: str | None = None) -> str | None:
    """Consomme une approbation `approuvee` de même empreinte ET du même utilisateur. ATOMIQUE :
    l'UPDATE conditionnel est l'arbitre. Si `niveau` est donné, seule une approbation de CE
    niveau est consommable (un `reversible` ne débloque jamais un `destructif`)."""
    now = maintenant if maintenant is not None else time.time()
    emp = accord_action.empreinte(capacite, args)
    user = _utilisateur(utilisateur)
    filtre = "" if niveau is None else " AND sensibilite=?"
    extra = () if niveau is None else (niveau,)
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        rows = c.execute(
            "SELECT * FROM approbations WHERE capacite=? AND empreinte=? AND utilisateur=? "
            "AND statut='approuvee' AND expire_a>?" + filtre + " ORDER BY decide_a",
            (capacite, emp, user, now, *extra)).fetchall()
        for r in rows:
            id_ = r["id"]
            if not _prerequis_tenus(c, r, args, now):
                continue
            cur = c.execute(
                "UPDATE approbations SET statut='executee', args=NULL "
                "WHERE id=? AND statut='approuvee' AND expire_a>?" + filtre,
                (id_, now, *extra))
            if cur.rowcount == 1:
                _journaliser(c, id_, "executee", maintenant=now)
                return id_
    return None


def consommer_id(id_: str, capacite: str, args: dict, niveau: str, utilisateur: str,
                 maintenant: float | None = None) -> bool:
    """Consomme CETTE approbation (reprise après approbation) : `approuvee`, non expirée,
    même capacité/empreinte/niveau/utilisateur. ATOMIQUE, usage unique."""
    now = maintenant if maintenant is not None else time.time()
    emp = accord_action.empreinte(capacite, args)
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        r = c.execute("SELECT * FROM approbations WHERE id=?", (id_,)).fetchone()
        if not r or not _prerequis_tenus(c, r, args, now):
            return False
        cur = c.execute(
            "UPDATE approbations SET statut='executee', args=NULL "
            "WHERE id=? AND capacite=? AND empreinte=? AND sensibilite=? AND utilisateur=? "
            "AND statut='approuvee' AND expire_a>?",
            (id_, capacite, emp, niveau, utilisateur, now))
        if cur.rowcount != 1:
            return False
        _journaliser(c, id_, "executee", detail="reprise", maintenant=now)
    return True


def args_de(id_: str) -> dict | None:
    """Arguments RÉELS d'une demande non terminée (None si purgés/absents). Usage interne :
    ne jamais renvoyer ce résultat par une route ni l'envoyer au canal."""
    with _conn() as c:
        r = c.execute("SELECT args FROM approbations WHERE id=?", (id_,)).fetchone()
    if not r or r["args"] is None:
        return None
    try:
        v = json.loads(r["args"])
    except (TypeError, ValueError):
        return None
    return v if isinstance(v, dict) else None


def a_reprendre(maintenant: float | None = None, delai_s: int = 60) -> list[str]:
    """Approuvées, non expirées, avec args, décidées depuis plus de `delai_s` : leur reprise
    n'a pas abouti (Cœur redémarré entre l'approbation et l'exécution)."""
    now = maintenant if maintenant is not None else time.time()
    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM approbations WHERE statut='approuvee' AND args IS NOT NULL "
            "AND expire_a>? AND decide_a<=? ORDER BY decide_a", (now, now - delai_s)).fetchall()
    return [r["id"] for r in rows]


def abandonner(id_: str, raison: str, maintenant: float | None = None) -> bool:
    """Abandonne une demande `approuvee` que la reprise ne peut plus exécuter légitimement
    (capacité plus sensible, garde refusée) : `approuvee -> expiree` (args purgés), journalisée
    `abandonnee`, pour que l'horloge cesse de la rejouer. True si la transition a eu lieu."""
    now = maintenant if maintenant is not None else time.time()
    with _conn() as c:
        if not _transition(c, id_, "approuvee", "expiree"):
            return False
        _journaliser(c, id_, "abandonnee", detail=(raison or "")[:200], maintenant=now)
    return True


def noter(id_: str, evenement: str, detail: str | None = None) -> None:
    """Journalise un événement sans transition d'état (ex. `reprise_echec`)."""
    with _conn() as c:
        _journaliser(c, id_, evenement, detail=(detail or "")[:200])


def nb_evenements(id_: str, evenement: str) -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM approbations_journal WHERE approbation_id=? "
                         "AND evenement=?", (id_, evenement)).fetchone()[0]


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


def en_attente(utilisateur: str | None = None) -> list[dict]:
    """Demandes ouvertes. `utilisateur=None` : toutes (usage interne) ; sinon seulement les siennes."""
    with _conn() as c:
        if utilisateur is None:
            rows = c.execute("SELECT * FROM approbations WHERE statut='en_attente' "
                             "ORDER BY cree_a").fetchall()
        else:
            rows = c.execute("SELECT * FROM approbations WHERE statut='en_attente' "
                             "AND utilisateur=? ORDER BY cree_a", (utilisateur,)).fetchall()
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

def _derniere(capacite: str, args: dict, statuts: tuple[str, ...], niveau: str,
              utilisateur: str) -> dict | None:
    emp = accord_action.empreinte(capacite, args)
    marques = ",".join("?" * len(statuts))
    with _conn() as c:
        r = c.execute(f"SELECT * FROM approbations WHERE capacite=? AND empreinte=? "
                      f"AND sensibilite=? AND utilisateur=? AND statut IN ({marques}) "
                      f"ORDER BY cree_a DESC LIMIT 1",
                      (capacite, emp, niveau, utilisateur, *statuts)).fetchone()
    return _vue(r) if r else None


def exiger(capacite: str, args: dict, niveau: str, resume: str,
           maintenant: float | None = None, *,
           prerequis: tuple[str, ...] = ()) -> tuple[str | None, str | None, dict | None]:
    """Cœur de la garde. Renvoie (id_consomme, message_pour_le_llm, demande_creee).

    - une approbation valide existe  -> elle est CONSOMMÉE, l'appelant exécute ;
    - une demande est déjà ouverte   -> message d'attente, pas de doublon ;
    - un refus très récent           -> message de refus, pas de redemande ;
    - sinon                          -> une demande est créée (l'appelant la notifie)."""
    now = maintenant if maintenant is not None else time.time()
    user = _utilisateur(None)
    rid = REPRISE.get()
    if rid:
        if consommer_id(rid, capacite, args, niveau, user, now):
            return rid, None, None
        return None, (
            f"Reprise de l'approbation {rid[:8]} impossible (expirée, déjà utilisée ou "
            "arguments différents) : action NON exécutée."), None
    id_ = consommer(capacite, args, niveau=niveau, maintenant=now, utilisateur=user)
    if id_:
        return id_, None, None
    ouverte = _derniere(capacite, args, ("en_attente",), niveau, user)
    if ouverte and ouverte["expire_a"] > now:
        return None, (
            f"Action `{capacite}` NON exécutée : la demande d'approbation {ouverte['id'][:8]} "
            "attend la réponse de l'humain sur Telegram. N'insiste pas et n'essaie pas de "
            "contourner : dis à l'utilisateur que tu attends son approbation."), None
    refusee = _derniere(capacite, args, ("refusee",), niveau, user)
    if refusee and (refusee["decide_a"] or 0) + DELAI_APRES_REFUS_S > now:
        return None, (
            f"Action `{capacite}` NON exécutée : l'humain a REFUSÉ cette action. Ne la "
            "redemande pas ; propose une alternative ou demande-lui ce qu'il veut."), None
    faite = _derniere(capacite, args, ("executee",), niveau, user)
    if faite and (faite["decide_a"] or 0) + DELAI_APRES_EXECUTION_S > now:
        return None, (
            f"Action `{capacite}` : cette action vient déjà d'être exécutée après approbation "
            "(résultat dans le message Telegram de l'humain). Ne la redemande pas."), None
    demande = creer(capacite, args, resume, niveau, maintenant=now, utilisateur=user,
                    prerequis=prerequis)
    return None, (
        f"Action `{capacite}` NON exécutée : une demande d'approbation ({demande['id'][:8]}, "
        f"niveau {niveau}) vient d'être envoyée à l'humain sur Telegram. Dis-lui que tu "
        "attends son approbation. Quand il aura approuvé, l'action s'exécutera AUTOMATIQUEMENT : "
        "ne rappelle pas l'outil et ne cherche pas à la relancer."), demande
