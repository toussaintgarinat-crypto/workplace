# S245 — Socle d'approbation Telegram : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** Une capacité déclarée `sensibilite` ne s'exécute que si un humain autorisé a approuvé *cette action exacte* sur Telegram (bouton, ou bouton + code à 6 chiffres pour `destructif`), avec expiration, usage unique, persistance et journal append-only.

**Architecture :** Le Cœur tient les approbations (`core/approbations.py`, SQLite) et les fait respecter dans `outils.executer` (point de passage unique chat / co-agent / MCP). La brique `connexion` porte le Telegram : elle envoie les messages à boutons, reçoit les `callback_query`, vérifie l'identité de l'approbateur (`correspondances.json`, champ `approbateur`) et relaie la décision au Cœur par HTTP authentifié (clé partagée). Le gate conversationnel de `accord_action.py` reste intact pour les 133 actions sans `sensibilite`.

**Tech Stack :** Python 3 / FastAPI / SQLite (stdlib `sqlite3`), httpx, pytest (`make test-core`, `pytest` dans `briques/connexion`), API Telegram Bot (`getUpdates`, `sendMessage`, `answerCallbackQuery`, `editMessageText`).

## Global Constraints

Décisions tranchées avec l'utilisateur le 2026-11-25 (Q1/Q2/Q3 du fichier S245) — à respecter à la lettre :

- **Approbateur explicite** : champ `approbateur: true` dans l'entrée de `correspondances.json`. Liste vide par défaut = **personne ne peut approuver**. L'approbation exige en plus `statut == "lie"` (jamais `ouvert`, même avec `CONNEXION_OUVERT=1`) **et** un chat privé (`chat.type == "private"` et `chat.id == from.id`).
- **Destructif = code à 6 chiffres**, PAS de Mini App. Le code est généré côté Cœur, **affiché dans l'app Workplace** (jamais envoyé sur Telegram), saisi dans Telegram, usage unique, **3 essais** puis la demande passe `refusee`.
- **Expirations par niveau** (défauts, surchargeables) : `reversible` 30 min, `donnees` 120 min, `destructif` 15 min. Variables : `APPROBATION_TTL_REVERSIBLE_MIN`, `APPROBATION_TTL_DONNEES_MIN`, `APPROBATION_TTL_DESTRUCTIF_MIN`. Une demande expirée n'est **jamais** exécutée automatiquement ; le mode attente la repose.
- **Niveaux** : `lecture` (aucune approbation), `reversible`, `donnees`, `destructif`. Capacité sans champ `sensibilite` = comportement actuel **inchangé**.
- Machine à états : `en_attente → approuvee | refusee | expiree`, `approuvee → executee | expiree`, `executee → echec`. Aucune autre transition. Usage unique, consommation atomique en SQL.
- `callback_data` = `ap:<id 32 hex>:<ok|ko>` (38 octets, limite Telegram 64).
- Journal **append-only** (triggers SQL qui interdisent UPDATE/DELETE).
- Fail closed : `APPROBATIONS_CLE` absente côté Cœur ⇒ les routes de décision répondent 503.
- Code, commentaires et messages en **français**, comme le reste du dépôt.
- Commits : fin de message = `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` puis `Claude-Session: https://claude.ai/code/session_01HhWGGaLbPBnwM9KTfyyUQp`.

## Écarts assumés par rapport au fichier S245 (à reporter dans l'ADR)

1. `approuvee → expiree` est autorisée (une approbation non utilisée ne doit pas rester valide indéfiniment). Fenêtre d'exécution après approbation : 5 min (`FENETRE_EXECUTION_S`).
2. La garde s'applique à **toutes** les origines (conversation comprise) pour une capacité sensible, pas seulement aux origines sans tour de parole : le « oui » conversationnel ne suffit plus pour ces capacités. `origine` n'est donc qu'une métadonnée journalisée.
3. Journal : table dédiée `approbations_journal` dans la même base SQLite. `journal_modele.py` est le journal des appels LLM (JSONL) et n'a rien à voir ; la brique `audit` est un produit client, pas un journal du Cœur.

## Structure des fichiers

| Fichier | Rôle |
|---|---|
| `core/approbations.py` (créer) | Magasin SQLite, machine à états, TTL, code destructif, consommation atomique, `exiger()` (la garde), journal. **Aucune I/O réseau.** |
| `core/approbations_canal.py` (créer) | Envoi vers la brique `connexion` (notifier / mettre à jour les messages). Best-effort, ne lève jamais. |
| `core/routers/approbations.py` (créer) | Routes : décision, armement/saisie du code (clé partagée), liste pour l'app (session), relance (horloge). |
| `core/test_approbations.py` (créer) | Machine à états, TTL, code, atomicité, journal, persistance. |
| `core/test_approbations_garde.py` (créer) | Garde dans `outils.executer` + non-régression + mutation du gate. |
| `core/test_approbations_routes.py` (créer) | Routes HTTP. |
| `core/catalogue.py` (modifier) | Propager `sensibilite` depuis le manifeste. |
| `core/outils.py` (modifier) | `est_sensible()`, garde dans `executer()`. |
| `core/assistant.py` (modifier) | Les capacités sensibles ne passent pas par le gate conversationnel. |
| `core/conftest.py`, `core/main.py` (modifier) | Chemin DB de test ; `init_db` + routeur. |
| `briques/noyau/manifest.json` (modifier) | Tâche horloge `approbations-relance`. |
| `briques/connexion/correspondance.py` (modifier) | `est_approbateur`, `approbateurs`. |
| `briques/connexion/adaptateurs.py` (modifier) | Telegram : boutons, `callback_query`, `answerCallbackQuery`, `editMessageText`. |
| `briques/connexion/client_assistant.py` (modifier) | Appels vers les routes d'approbation du Cœur. |
| `briques/connexion/pont.py` (modifier) | `traiter_callback`, interception du code à 6 chiffres. |
| `briques/connexion/main.py` (modifier) | `/approbation/notifier`, `/approbation/mettre_a_jour`, branche `callback_query` du webhook. |
| `docs/decisions/2026-11-25-approbation-telegram.md` (créer) | ADR : garanties **et non-garanties**. |

---

### Task 0 : Branche de travail

- [ ] **Step 1 : Créer l'isolation**

Invoquer `superpowers:using-git-worktrees`, branche `s245-approbation-telegram`, depuis `main`.

- [ ] **Step 2 : Versionner la conception**

Dans la branche, commiter les fichiers de conception encore non suivis :

```bash
git add docs/sprints/EPOPEE-livraison-support-assistant.md docs/sprints/S24*.md docs/superpowers/plans/2026-11-25-s245-socle-approbation-telegram.md
git commit -m "docs(s245-s249): épopée livraison+support et plan S245"
```

---

### Task 1 : Magasin d'approbations et machine à états

**Files :**
- Create : `core/approbations.py`
- Create : `core/test_approbations.py`
- Modify : `core/conftest.py` (ajouter `"APPROBATIONS_DB": "approbations.db",` dans `_CHEMINS`, ordre alphabétique, avant `"HORLOGE_DB"`)

**Interfaces :**
- Produces (utilisées par les tâches 2→8) :
  - Constantes : `NIVEAUX`, `NIVEAUX_SENSIBLES`, `FENETRE_EXECUTION_S = 300`, `ESSAIS_CODE_MAX = 3`, `ORIGINE: ContextVar[str]`
  - `ttl_secondes(niveau: str) -> int`
  - `init_db() -> None`
  - `creer(capacite: str, args: dict, resume: str, sensibilite: str, origine: str | None = None, prerequis: tuple[str, ...] = (), maintenant: float | None = None) -> dict`
  - `lire(id_: str) -> dict | None` — dict avec clés : `id, capacite, empreinte, resume, sensibilite, origine, statut, cree_a, expire_a, decide_a, decide_par, canal, resultat, prerequis (dict nom→bool), code (str|None), essais, nb_relances, relance_a, messages (list)`
  - `approuver(id_, par, canal, maintenant=None) -> tuple[bool, str]` — raisons : `ok, introuvable, deja_decidee, expiree, prerequis, code_requis`
  - `refuser(id_, par, canal, maintenant=None) -> tuple[bool, str]`
  - `journal(id_: str) -> list[dict]`

- [ ] **Step 1 : Écrire les tests qui échouent**

`core/test_approbations.py` :

```python
"""Machine à états des approbations (S245) : transitions, expiration, journal, persistance."""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import approbations  # noqa: E402

T0 = 1_000_000.0


@pytest.fixture(autouse=True)
def base_isolee(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "approbations.db"))
    approbations.init_db()


def _demande(sens="reversible", **kw):
    return approbations.creer("app_redemarrer", {"app": "crm"}, "Redémarrer crm", sens,
                              origine="incident", maintenant=T0, **kw)


def test_creation_est_en_attente_avec_ttl_par_niveau():
    for niveau, minutes in (("reversible", 30), ("donnees", 120), ("destructif", 15)):
        a = approbations.creer(f"cap_{niveau}", {}, "r", niveau, maintenant=T0)
        assert a["statut"] == "en_attente"
        assert a["expire_a"] == T0 + minutes * 60
        assert len(a["id"]) == 32


def test_ttl_surchargeable_par_env(monkeypatch):
    monkeypatch.setenv("APPROBATION_TTL_DESTRUCTIF_MIN", "5")
    assert approbations.ttl_secondes("destructif") == 300


def test_niveau_lecture_ou_inconnu_refuse():
    for niveau in ("lecture", "nimporte"):
        with pytest.raises(ValueError):
            approbations.creer("x", {}, "r", niveau, maintenant=T0)


def test_code_seulement_pour_destructif():
    assert _demande("reversible")["code"] is None
    code = _demande("destructif")["code"]
    assert code is not None and len(code) == 6 and code.isdigit()


def test_creer_est_idempotent_sur_la_meme_action():
    a, b = _demande(), _demande()
    assert a["id"] == b["id"]


def test_approuver_reversible():
    a = _demande()
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 10) == (True, "ok")
    lue = approbations.lire(a["id"])
    assert lue["statut"] == "approuvee" and lue["decide_par"] == "tg:42"


def test_double_approbation_refusee():
    a = _demande()
    approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1)
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 2) == (False, "deja_decidee")


def test_approuver_apres_expiration_marque_expiree():
    a = _demande()
    ok, raison = approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 31 * 60)
    assert (ok, raison) == (False, "expiree")
    assert approbations.lire(a["id"])["statut"] == "expiree"


def test_destructif_ne_s_approuve_pas_par_bouton_seul():
    a = _demande("destructif")
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1) == (False, "code_requis")
    assert approbations.lire(a["id"])["statut"] == "en_attente"


def test_id_inconnu():
    assert approbations.approuver("0" * 32, "tg:42", "telegram") == (False, "introuvable")
    assert approbations.refuser("0" * 32, "tg:42", "telegram") == (False, "introuvable")


def test_refuser_puis_plus_d_approbation():
    a = _demande()
    assert approbations.refuser(a["id"], "tg:42", "telegram", maintenant=T0 + 1) == (True, "ok")
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 2) == (False, "deja_decidee")


def test_journal_append_only_trace_chaque_transition():
    a = _demande()
    approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1)
    assert [e["evenement"] for e in approbations.journal(a["id"])] == ["creee", "approuvee"]
    with sqlite3.connect(approbations.DB) as c:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            c.execute("UPDATE approbations_journal SET evenement='x'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            c.execute("DELETE FROM approbations_journal")


def test_persistance_apres_redemarrage():
    a = _demande()
    approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1)
    approbations.init_db()  # « redémarrage » : la base reste, init_db est idempotent
    assert approbations.lire(a["id"])["statut"] == "approuvee"


def test_prerequis_bloquent_l_approbation():
    a = _demande("donnees", prerequis=("sauvegarde_verifiee",))
    assert a["prerequis"] == {"sauvegarde_verifiee": False}
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1) == (False, "prerequis")
```

- [ ] **Step 2 : Vérifier l'échec**

Run : `cd core && python3 -m pytest test_approbations.py -q`
Expected : FAIL — `ModuleNotFoundError: No module named 'approbations'`.

- [ ] **Step 3 : Implémenter**

`core/approbations.py` :

```python
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
- Que l'humain ait COMPRIS l'action : on garantit qu'il a vu le résumé et cliqué.
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
            "SELECT * FROM approbations WHERE capacite=? AND empreinte=? "
            "AND statut IN ('en_attente','approuvee') AND expire_a>? "
            "ORDER BY cree_a DESC LIMIT 1", (capacite, emp, now)).fetchone()
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
```

Ajouter dans `core/conftest.py`, dans le dict `_CHEMINS`, la ligne `"APPROBATIONS_DB": "approbations.db",`.

- [ ] **Step 4 : Vérifier**

Run : `cd core && python3 -m pytest test_approbations.py -q`
Expected : `13 passed`.

- [ ] **Step 5 : Commit**

```bash
git add core/approbations.py core/test_approbations.py core/conftest.py
git commit -m "feat(approbations): magasin SQLite, machine à états, TTL par niveau, journal append-only"
```

---

### Task 2 : Code destructif, consommation atomique, prérequis, expiration, relance

**Files :**
- Modify : `core/approbations.py` (ajouter à la suite)
- Modify : `core/test_approbations.py` (ajouter à la suite)

**Interfaces :**
- Consumes : Task 1.
- Produces :
  - `armer_saisie_code(id_: str, par: str, maintenant=None) -> tuple[bool, str]` — raisons : `ok, introuvable, pas_destructif, deja_decidee, expiree`
  - `valider_code_saisi(par: str, code: str, maintenant=None) -> dict | None` — `None` si aucune saisie armée pour `par` (le message n'est pas un code : à laisser passer) ; sinon `{"ok": bool, "raison": str, "approbation_id": str, "restants": int}` ; raisons : `ok, code_faux, essais_epuises, expiree, deja_decidee`
  - `satisfaire_prerequis(id_: str, nom: str) -> bool` — `True` ssi TOUS les prérequis sont désormais satisfaits
  - `consommer(capacite: str, args: dict, maintenant=None) -> str | None` — id consommé, ou `None`
  - `conclure(id_: str, ok: bool, resultat: str) -> None`
  - `expirer_perimees(maintenant=None) -> list[str]`
  - `a_relancer(delai_s: int, max_relances: int, maintenant=None) -> list[dict]`
  - `marquer_relancee(id_: str, maintenant=None) -> None`
  - `enregistrer_messages(id_: str, messages: list[dict]) -> None`
  - `en_attente() -> list[dict]`

- [ ] **Step 1 : Tests qui échouent**

Ajouter à `core/test_approbations.py` :

```python
import threading


# ── Code à 6 chiffres (destructif) ───────────────────────────────────────────

def test_code_bon_approuve_un_destructif():
    a = _demande("destructif")
    assert approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1) == (True, "ok")
    r = approbations.valider_code_saisi("tg:42", a["code"], maintenant=T0 + 2)
    assert r["ok"] is True and r["approbation_id"] == a["id"]
    assert approbations.lire(a["id"])["statut"] == "approuvee"


def test_pas_de_saisie_armee_le_message_n_est_pas_un_code():
    _demande("destructif")
    assert approbations.valider_code_saisi("tg:42", "123456") is None


def test_trois_codes_faux_refusent_la_demande():
    a = _demande("destructif")
    faux = "000000" if a["code"] != "000000" else "111111"
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1)
    r1 = approbations.valider_code_saisi("tg:42", faux, maintenant=T0 + 2)
    r2 = approbations.valider_code_saisi("tg:42", faux, maintenant=T0 + 3)
    assert (r1["raison"], r1["restants"]) == ("code_faux", 2)
    assert (r2["raison"], r2["restants"]) == ("code_faux", 1)
    r3 = approbations.valider_code_saisi("tg:42", faux, maintenant=T0 + 4)
    assert r3["raison"] == "essais_epuises"
    assert approbations.lire(a["id"])["statut"] == "refusee"
    # la saisie est désarmée : un 4e message repart au LLM
    assert approbations.valider_code_saisi("tg:42", a["code"], maintenant=T0 + 5) is None


def test_le_bon_code_apres_refus_n_approuve_rien():
    a = _demande("destructif")
    faux = "000000" if a["code"] != "000000" else "111111"
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1)
    for i in range(3):
        approbations.valider_code_saisi("tg:42", faux, maintenant=T0 + 2 + i)
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 9)  # doit échouer
    assert approbations.lire(a["id"])["statut"] == "refusee"


def test_armer_refuse_hors_destructif_ou_expire():
    assert approbations.armer_saisie_code(_demande("reversible")["id"], "tg:42") == (False, "pas_destructif")
    d = _demande("destructif")
    assert approbations.armer_saisie_code(d["id"], "tg:42", maintenant=T0 + 16 * 60) == (False, "expiree")


def test_saisie_armee_expire_au_bout_de_5_minutes():
    a = _demande("destructif")
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1)
    assert approbations.valider_code_saisi("tg:42", a["code"], maintenant=T0 + 1 + 301) is None


def test_la_saisie_d_un_autre_approbateur_ne_compte_pas():
    a = _demande("destructif")
    approbations.armer_saisie_code(a["id"], "tg:42", maintenant=T0 + 1)
    assert approbations.valider_code_saisi("tg:99", a["code"], maintenant=T0 + 2) is None


# ── Consommation atomique ────────────────────────────────────────────────────

def _approuvee(**kw):
    a = _demande(**kw)
    approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1)
    return a


def test_consommer_une_seule_fois():
    a = _approuvee()
    assert approbations.consommer("app_redemarrer", {"app": "crm"}, maintenant=T0 + 2) == a["id"]
    assert approbations.consommer("app_redemarrer", {"app": "crm"}, maintenant=T0 + 3) is None
    assert approbations.lire(a["id"])["statut"] == "executee"


def test_consommer_exige_la_meme_empreinte():
    _approuvee()
    assert approbations.consommer("app_redemarrer", {"app": "autre"}, maintenant=T0 + 2) is None
    assert approbations.consommer("autre_cap", {"app": "crm"}, maintenant=T0 + 2) is None


def test_consommer_ignore_confirme():
    _approuvee()
    assert approbations.consommer("app_redemarrer", {"app": "crm", "confirme": True}, maintenant=T0 + 2)


def test_consommer_sans_approbation_ou_en_attente_ou_refusee():
    assert approbations.consommer("app_redemarrer", {"app": "crm"}) is None
    _demande()
    assert approbations.consommer("app_redemarrer", {"app": "crm"}, maintenant=T0 + 1) is None


def test_consommer_apres_la_fenetre_d_execution():
    _approuvee()
    assert approbations.consommer("app_redemarrer", {"app": "crm"}, maintenant=T0 + 1 + 301 + 30 * 60) is None


def test_consommation_concurrente_une_seule_gagne():
    _approuvee()
    gagnants = []

    def tenter():
        r = approbations.consommer("app_redemarrer", {"app": "crm"}, maintenant=T0 + 2)
        if r:
            gagnants.append(r)

    fils = [threading.Thread(target=tenter) for _ in range(12)]
    [f.start() for f in fils]
    [f.join() for f in fils]
    assert len(gagnants) == 1


def test_conclure_echec_passe_executee_a_echec():
    a = _approuvee()
    approbations.consommer("app_redemarrer", {"app": "crm"}, maintenant=T0 + 2)
    approbations.conclure(a["id"], False, "Erreur (crm) : boom")
    lue = approbations.lire(a["id"])
    assert lue["statut"] == "echec" and "boom" in lue["resultat"]


def test_conclure_succes_garde_executee_et_note_le_resultat():
    a = _approuvee()
    approbations.consommer("app_redemarrer", {"app": "crm"}, maintenant=T0 + 2)
    approbations.conclure(a["id"], True, "ok")
    assert approbations.lire(a["id"])["statut"] == "executee"


# ── Prérequis ────────────────────────────────────────────────────────────────

def test_prerequis_satisfaits_debloquent_l_approbation():
    a = _demande("donnees", prerequis=("sauvegarde_verifiee", "restauration_testee"))
    assert approbations.satisfaire_prerequis(a["id"], "sauvegarde_verifiee") is False
    assert approbations.satisfaire_prerequis(a["id"], "restauration_testee") is True
    assert approbations.approuver(a["id"], "tg:42", "telegram", maintenant=T0 + 1) == (True, "ok")


def test_prerequis_inconnu_ignore():
    a = _demande("donnees", prerequis=("sauvegarde_verifiee",))
    assert approbations.satisfaire_prerequis(a["id"], "inconnu") is False


# ── Expiration et relance ────────────────────────────────────────────────────

def test_expirer_perimees():
    vieille = _demande()
    ok = approbations.creer("autre", {}, "r", "donnees", maintenant=T0)
    assert approbations.expirer_perimees(maintenant=T0 + 31 * 60) == [vieille["id"]]
    assert approbations.lire(vieille["id"])["statut"] == "expiree"
    assert approbations.lire(ok["id"])["statut"] == "en_attente"
    assert approbations.expirer_perimees(maintenant=T0 + 31 * 60) == []  # idempotent


def test_une_approbation_non_utilisee_finit_expiree():
    a = _approuvee()
    assert a["id"] in approbations.expirer_perimees(maintenant=T0 + 3600)
    assert approbations.lire(a["id"])["statut"] == "expiree"


def test_a_relancer_respecte_delai_et_plafond():
    a = _demande()
    assert approbations.a_relancer(600, 3, maintenant=T0 + 300) == []
    assert [x["id"] for x in approbations.a_relancer(600, 3, maintenant=T0 + 601)] == [a["id"]]
    approbations.marquer_relancee(a["id"], maintenant=T0 + 601)
    assert approbations.a_relancer(600, 3, maintenant=T0 + 700) == []
    assert [x["id"] for x in approbations.a_relancer(600, 3, maintenant=T0 + 1300)] == [a["id"]]
    for i in range(3):
        approbations.marquer_relancee(a["id"], maintenant=T0 + 1300 + i)
    assert approbations.a_relancer(600, 3, maintenant=T0 + 5000) == []  # plafond atteint


def test_en_attente_et_messages():
    a = _demande()
    approbations.enregistrer_messages(a["id"], [{"chat_id": "42", "message_id": 7}])
    assert approbations.lire(a["id"])["messages"] == [{"chat_id": "42", "message_id": 7}]
    assert [x["id"] for x in approbations.en_attente()] == [a["id"]]
```

- [ ] **Step 2 : Vérifier l'échec**

Run : `cd core && python3 -m pytest test_approbations.py -q`
Expected : les nouveaux tests FAIL (`AttributeError: module 'approbations' has no attribute 'armer_saisie_code'` etc.), les 13 premiers PASS.

- [ ] **Step 3 : Implémenter**

Ajouter à la fin de `core/approbations.py` :

```python
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
        if hmac.compare_digest((code or "").strip(), r["code"] or ""):
            _transition(c, id_, "en_attente", "approuvee", decide_a=now, decide_par=par,
                        canal="telegram+code",
                        expire_a=max(r["expire_a"], now + FENETRE_EXECUTION_S))
            c.execute("DELETE FROM saisie_code WHERE approbateur=?", (par,))
            _journaliser(c, id_, "approuvee", par, "telegram+code", maintenant=now)
            return {"ok": True, "raison": "ok", "approbation_id": id_, "restants": 0}
        essais = r["essais"] + 1
        c.execute("UPDATE approbations SET essais=? WHERE id=?", (essais, id_))
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

def consommer(capacite: str, args: dict, maintenant: float | None = None) -> str | None:
    """Consomme une approbation `approuvee` de même empreinte. ATOMIQUE : l'UPDATE conditionnel
    est l'arbitre ; si deux appels concurrents la visent, un seul modifie 1 ligne."""
    now = maintenant if maintenant is not None else time.time()
    emp = accord_action.empreinte(capacite, args)
    with _conn() as c:
        ids = [r["id"] for r in c.execute(
            "SELECT id FROM approbations WHERE capacite=? AND empreinte=? AND statut='approuvee' "
            "AND expire_a>? ORDER BY decide_a", (capacite, emp, now))]
        for id_ in ids:
            cur = c.execute(
                "UPDATE approbations SET statut='executee' "
                "WHERE id=? AND statut='approuvee' AND expire_a>?", (id_, now))
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
```

- [ ] **Step 4 : Vérifier**

Run : `cd core && python3 -m pytest test_approbations.py -q`
Expected : tous PASS (≈ 34).

- [ ] **Step 5 : Commit**

```bash
git add core/approbations.py core/test_approbations.py
git commit -m "feat(approbations): code destructif 3 essais, consommation atomique, prérequis, relance"
```

---

### Task 3 : La garde `exiger()` et le câblage `outils.executer`

**Files :**
- Modify : `core/approbations.py` (ajouter `exiger`)
- Modify : `core/catalogue.py:88` (ajouter `sensibilite` dans le dict de capacité)
- Modify : `core/outils.py` (fonction `est_sensible`, garde dans `executer`, ~ligne 557)
- Modify : `core/assistant.py:370-383` (les capacités sensibles sortent du gate conversationnel)
- Create : `core/test_approbations_garde.py`

**Interfaces :**
- Consumes : Task 1-2 (`creer`, `consommer`, `lire`, `conclure`, `NIVEAUX_SENSIBLES`).
- Produces :
  - `approbations.exiger(capacite: str, args: dict, niveau: str, resume: str) -> tuple[str | None, str | None, dict | None]` → `(id_consomme, message_pour_le_llm, demande_nouvellement_creee)`. Exactement UN des deux premiers est non nul.
  - `outils.est_sensible(nom: str, registre) -> str | None` → niveau (`reversible|donnees|destructif`) ou `None`.
  - Hook d'envoi : `outils._notifier_approbation` (coroutine `async (registre, demande: dict) -> None`, remplacée en Task 5 par `approbations_canal.notifier`).

- [ ] **Step 1 : Tests qui échouent**

`core/test_approbations_garde.py` :

```python
"""La garde des capacités sensibles, DANS outils.executer (S245) — là où le trou vivait.

Même méthode que test_gate_action_bout_en_bout : on prouve le câblage, puis on vérifie que
neutraliser la garde fait échouer les tests de sécurité (et pas ceux de non-régression)."""
import asyncio
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

import approbations  # noqa: E402
import outils  # noqa: E402


class _FauxRegistre:
    def __init__(self, briques):
        self.briques = briques


REGISTRE = _FauxRegistre({
    "dokploy": {"nom": "dokploy", "port": 6300, "capacites": [
        {"nom": "app_redemarrer", "chemin": "/redemarrer", "methode": "POST", "action": True,
         "sensibilite": "reversible", "description": "Redémarre une app.",
         "params": {"app": {"type": "string", "requis": True}}},
        {"nom": "app_reset", "chemin": "/reset", "methode": "POST", "action": True,
         "sensibilite": "destructif", "description": "Remise à zéro.",
         "params": {"app": {"type": "string", "requis": True}}},
        {"nom": "app_logs", "chemin": "/logs", "sensibilite": "lecture",
         "description": "Lit les logs.", "params": {"app": {"type": "string"}}},
        {"nom": "app_ancienne", "chemin": "/x", "methode": "POST", "action": True,
         "description": "Action SANS sensibilite (comportement historique).",
         "params": {"app": {"type": "string"}}},
    ]},
})


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()
    notifs = []

    async def faux_notifier(registre, demande):
        notifs.append(demande["id"])

    monkeypatch.setattr(outils, "_notifier_approbation", faux_notifier)
    atteints = []

    async def faux_executer(nom, args, registre):
        atteints.append((nom, dict(args)))
        return '{"ok": true}'

    monkeypatch.setattr(outils, "_executer", faux_executer)
    return {"notifs": notifs, "atteints": atteints}


def _run(nom, args):
    return asyncio.run(outils.executer(nom, args, REGISTRE))


def test_est_sensible_lit_le_manifeste():
    assert outils.est_sensible("app_redemarrer", REGISTRE) == "reversible"
    assert outils.est_sensible("app_reset", REGISTRE) == "destructif"
    assert outils.est_sensible("app_logs", REGISTRE) is None       # lecture
    assert outils.est_sensible("app_ancienne", REGISTRE) is None   # pas de champ
    assert outils.est_sensible("inconnu", REGISTRE) is None


# ── Sécurité ─────────────────────────────────────────────────────────────────

def test_sans_approbation_rien_ne_s_execute_et_une_demande_est_creee(_env):
    res = _run("app_redemarrer", {"app": "crm", "confirme": True})   # même avec confirme=true
    assert _env["atteints"] == []
    assert "NON exécutée" in res and "Telegram" in res
    assert len(_env["notifs"]) == 1
    assert approbations.lire(_env["notifs"][0])["statut"] == "en_attente"


def test_le_llm_ne_peut_pas_se_confirmer_tout_seul(_env):
    for _ in range(3):
        _run("app_redemarrer", {"app": "crm", "confirme": True})
    assert _env["atteints"] == []
    assert len(_env["notifs"]) == 1          # une seule demande, pas de spam


def test_approuvee_puis_executee_une_fois(_env):
    _run("app_redemarrer", {"app": "crm"})
    approbations.approuver(_env["notifs"][0], "tg:42", "telegram")
    res = _run("app_redemarrer", {"app": "crm"})
    assert _env["atteints"] == [("app_redemarrer", {"app": "crm", "confirme": True})]
    assert '"ok": true' in res
    _run("app_redemarrer", {"app": "crm"})                           # usage unique
    assert len(_env["atteints"]) == 1


def test_approbation_pour_crm_ne_vaut_pas_pour_autre(_env):
    _run("app_redemarrer", {"app": "crm"})
    approbations.approuver(_env["notifs"][0], "tg:42", "telegram")
    _run("app_redemarrer", {"app": "autre"})
    assert _env["atteints"] == []


def test_refus_bloque_la_redemande_immediate(_env):
    _run("app_redemarrer", {"app": "crm"})
    approbations.refuser(_env["notifs"][0], "tg:42", "telegram")
    res = _run("app_redemarrer", {"app": "crm"})
    assert "refusée" in res.lower()
    assert len(_env["notifs"]) == 1 and _env["atteints"] == []


def test_destructif_exige_le_code_pas_le_bouton(_env):
    _run("app_reset", {"app": "crm"})
    id_ = _env["notifs"][0]
    assert approbations.approuver(id_, "tg:42", "telegram") == (False, "code_requis")
    _run("app_reset", {"app": "crm"})
    assert _env["atteints"] == []
    approbations.armer_saisie_code(id_, "tg:42")
    approbations.valider_code_saisi("tg:42", approbations.lire(id_)["code"])
    _run("app_reset", {"app": "crm"})
    assert [a[0] for a in _env["atteints"]] == ["app_reset"]


def test_un_echec_d_execution_est_journalise(_env, monkeypatch):
    async def casse(nom, args, registre):
        return "Erreur (dokploy) : boom"

    _run("app_redemarrer", {"app": "crm"})
    approbations.approuver(_env["notifs"][0], "tg:42", "telegram")
    monkeypatch.setattr(outils, "_executer", casse)
    _run("app_redemarrer", {"app": "crm"})
    assert approbations.lire(_env["notifs"][0])["statut"] == "echec"


# ── Non-régression (doivent passer AVANT et APRÈS la garde) ──────────────────

def test_lecture_passe_sans_approbation(_env):
    _run("app_logs", {"app": "crm"})
    assert [a[0] for a in _env["atteints"]] == ["app_logs"] and _env["notifs"] == []


def test_capacite_sans_sensibilite_garde_le_comportement_historique(_env):
    _run("app_ancienne", {"app": "crm"})
    assert [a[0] for a in _env["atteints"]] == ["app_ancienne"] and _env["notifs"] == []


# ── La garde ne doit pas dépendre du LLM ─────────────────────────────────────

def test_exiger_direct():
    id_, msg, nouvelle = approbations.exiger("c", {"a": 1}, "reversible", "résumé")
    assert id_ is None and msg and nouvelle["statut"] == "en_attente"
    id2, msg2, nouvelle2 = approbations.exiger("c", {"a": 1}, "reversible", "résumé")
    assert id2 is None and msg2 and nouvelle2 is None          # déjà en attente : pas de doublon
```

- [ ] **Step 2 : Vérifier l'échec**

Run : `cd core && python3 -m pytest test_approbations_garde.py -q`
Expected : FAIL (`AttributeError: ... 'est_sensible'` / `'exiger'`).

- [ ] **Step 3 : Implémenter**

(a) `core/approbations.py`, ajouter après `conclure` :

```python
# ── La garde ─────────────────────────────────────────────────────────────────

def _derniere(capacite: str, args: dict, statuts: tuple[str, ...]) -> dict | None:
    emp = accord_action.empreinte(capacite, args)
    marques = ",".join("?" * len(statuts))
    with _conn() as c:
        r = c.execute(f"SELECT * FROM approbations WHERE capacite=? AND empreinte=? "
                      f"AND statut IN ({marques}) ORDER BY cree_a DESC LIMIT 1",
                      (capacite, emp, *statuts)).fetchone()
    return _vue(r) if r else None


def exiger(capacite: str, args: dict, niveau: str, resume: str,
           maintenant: float | None = None) -> tuple[str | None, str | None, dict | None]:
    """Cœur de la garde. Renvoie (id_consomme, message_pour_le_llm, demande_creee).

    - une approbation valide existe  -> elle est CONSOMMÉE, l'appelant exécute ;
    - une demande est déjà ouverte   -> message d'attente, pas de doublon ;
    - un refus très récent           -> message de refus, pas de redemande ;
    - sinon                          -> une demande est créée (l'appelant la notifie)."""
    now = maintenant if maintenant is not None else time.time()
    id_ = consommer(capacite, args, maintenant=now)
    if id_:
        return id_, None, None
    ouverte = _derniere(capacite, args, ("en_attente",))
    if ouverte and ouverte["expire_a"] > now:
        return None, (
            f"Action `{capacite}` NON exécutée : la demande d'approbation {ouverte['id'][:8]} "
            "attend la réponse de l'humain sur Telegram. N'insiste pas et n'essaie pas de "
            "contourner : dis à l'utilisateur que tu attends son approbation."), None
    refusee = _derniere(capacite, args, ("refusee",))
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
```

(b) `core/catalogue.py`, dans le dict ajouté à `capacites` (après la ligne `"action": bool(decl.get("action", False)),`), ajouter :

```python
                # S245 — niveau de sensibilité : active l'approbation Telegram (core/approbations)
                "sensibilite": decl.get("sensibilite"),
```

(c) `core/outils.py` : ajouter l'import `import approbations` avec les autres imports du fichier (même bloc que `import droits`), puis, juste avant `async def executer`, et en remplaçant le corps de `executer` :

```python
async def _notifier_approbation(registre, demande: dict) -> None:
    """Remplacé par `approbations_canal.notifier` (S245, tâche 5). Par défaut : rien."""
    return None


def est_sensible(nom: str, registre) -> str | None:
    """Niveau de sensibilité (`reversible|donnees|destructif`) d'une capacité de manifeste,
    ou None (lecture, pas de champ, outil inconnu). S245."""
    cap = _capacites_dynamiques(registre).get(nom)
    niveau = (cap or {}).get("sensibilite")
    return niveau if niveau in approbations.NIVEAUX_SENSIBLES else None


def _resume_action(nom: str, args: dict) -> str:
    """Résumé lisible montré à l'humain : la capacité et ses arguments EXACTS."""
    utiles = {k: v for k, v in (args or {}).items() if k != "confirme" and v is not None}
    detail = ", ".join(f"{k}={v!r}" for k, v in sorted(utiles.items())) or "sans argument"
    return f"{nom}({detail})"[:300]


async def executer(nom: str, args: dict, registre) -> str:
    """(docstring existante inchangée, ajouter ce paragraphe)

    S245 : une capacité qui déclare `sensibilite` ne s'exécute que si `approbations.exiger`
    consomme une approbation humaine de même empreinte — QUEL QUE SOIT l'appelant (chat,
    co-agent, MCP) : c'est ce qui ferme le trou signalé dans l'ADR du gate (S222)."""
    if est_reserve_admin(nom, registre) and not droits.ADMIN_CERVEAU.get():
        resultat = droits.refus(nom)
    else:
        niveau = est_sensible(nom, registre)
        id_appr = None
        if niveau:
            id_appr, refus, nouvelle = approbations.exiger(
                nom, args or {}, niveau, _resume_action(nom, args or {}))
            if refus:
                if nouvelle:
                    await _notifier_approbation(registre, nouvelle)
                return refus
            args = {**(args or {}), "confirme": True}   # l'approbation EST la confirmation
        resultat = await _executer(nom, args, registre)
        if id_appr:
            approbations.conclure(id_appr, not est_erreur(resultat), resultat)
    _APPELS[nom] = _APPELS.get(nom, 0) + 1
    if est_erreur(resultat):
        _ECHECS[nom] = _ECHECS.get(nom, 0) + 1
    return resultat
```

Note : conserver tel quel le docstring existant de `executer` (ne garder que le paragraphe S245 en plus). `_capacites_dynamiques` est déjà utilisé dans `_executer` du même fichier : même portée.

(d) `core/assistant.py:370-383`. Remplacer `est_une_action = outils.est_action(nom, registre)` et le `if est_une_action:` du bloc gate par :

```python
                est_une_action = outils.est_action(nom, registre)
                # S245 — une capacité SENSIBLE est gardée dans outils.executer par une
                # approbation Telegram : le « oui » conversationnel ne la concerne plus.
                sensible = outils.est_sensible(nom, registre) is not None
                refus_accord = None
                if est_une_action and not sensible:
```

(le reste du bloc, y compris le `else:` des lectures, est inchangé ; une capacité sensible tombe dans le `else`, ce qui est inoffensif : au pire une annotation de lecture en lot.)

- [ ] **Step 4 : Vérifier (nouveaux tests + non-régression du gate S222)**

Run : `cd core && python3 -m pytest test_approbations_garde.py test_approbations.py test_accord_action.py test_gate_action_bout_en_bout.py test_catalogue.py -q`
Expected : tout PASS.

- [ ] **Step 5 : Commit**

```bash
git add core/approbations.py core/catalogue.py core/outils.py core/assistant.py core/test_approbations_garde.py
git commit -m "feat(approbations): garde des capacités sensibles dans outils.executer (ferme co-agent/MCP)"
```

---

### Task 4 : Routes du Cœur (décision, code, liste, relance)

**Files :**
- Create : `core/routers/approbations.py`
- Create : `core/test_approbations_routes.py`
- Modify : `core/main.py` (import, `approbations.init_db()` dans le lifespan, `include_router`)

**Interfaces :**
- Consumes : Tasks 1-3 ; `auth.exiger_session_api`.
- Produces (HTTP, consommé par `briques/connexion` en Task 7) :
  - `POST /approbations/{id}/decision` — en-tête `X-Approbations-Cle`, corps `{"decision": "ok"|"ko", "par": str, "canal": str}` → `{"ok": bool, "raison": str, "statut": str|None, "sensibilite": str|None}`
  - `POST /approbations/{id}/code/armer` — même clé, corps `{"par": str}` → `{"ok": bool, "raison": str}`
  - `POST /approbations/code` — même clé, corps `{"par": str, "code": str}` → `{"pris_en_charge": bool, "ok"?: bool, "raison"?: str, "restants"?: int, "approbation_id"?: str}`
  - `GET /approbations/en_attente` — session ; **inclut `code`** pour les destructifs (c'est le canal d'affichage du code)
  - `POST /approbations/relancer` — session OU clé ; appelé par l'horloge
- Env : `APPROBATIONS_CLE` (secret partagé Cœur↔connexion), `APPROBATION_RELANCE_MIN` (défaut 60), `APPROBATION_RELANCE_MAX` (défaut 3).

- [ ] **Step 1 : Tests qui échouent**

`core/test_approbations_routes.py` — calquer l'amorçage (client FastAPI, surcharge de `auth.exiger_session_api`) sur `core/test_recherche*.py` ou `core/test_auth_routes.py` (lire l'un d'eux d'abord pour reprendre exactement le fixture de client et la dépendance de session à surcharger). Cas à écrire, un test chacun :

```python
CLE = "cle-test-approbations"
ENT = {"X-Approbations-Cle": CLE}


def test_decision_sans_cle_ou_mauvaise_cle_401(client, demande):
    assert client.post(f"/approbations/{demande['id']}/decision",
                       json={"decision": "ok", "par": "tg:42", "canal": "telegram"}).status_code == 401
    assert client.post(f"/approbations/{demande['id']}/decision", headers={"X-Approbations-Cle": "x"},
                       json={"decision": "ok", "par": "tg:42", "canal": "telegram"}).status_code == 401


def test_decision_fail_closed_si_cle_non_configuree(client_sans_cle, demande):
    # APPROBATIONS_CLE absente => 503, JAMAIS « ouvert »
    r = client_sans_cle.post(f"/approbations/{demande['id']}/decision", headers=ENT,
                             json={"decision": "ok", "par": "tg:42", "canal": "telegram"})
    assert r.status_code == 503


def test_decision_ok_approuve(client, demande):
    r = client.post(f"/approbations/{demande['id']}/decision", headers=ENT,
                    json={"decision": "ok", "par": "tg:42", "canal": "telegram"})
    assert r.json() == {"ok": True, "raison": "ok", "statut": "approuvee", "sensibilite": "reversible"}


def test_decision_ko_refuse(client, demande): ...          # statut "refusee"
def test_decision_id_forge_ou_inconnu(client): ...           # id non hex-32 => 422 ; hex inconnu => ok False introuvable
def test_decision_destructif_renvoie_code_requis(client, demande_destructive): ...
def test_code_armer_puis_code_valide_approuve(client, demande_destructive): ...
def test_code_sans_saisie_armee_pris_en_charge_false(client): ...
def test_code_faux_decremente_restants(client, demande_destructive): ...
def test_en_attente_exige_session_et_expose_le_code_destructif(client, client_sans_session, demande_destructive): ...
def test_relancer_expire_les_perimees_et_relance_les_anciennes(client, monkeypatch): ...
```

Les corps `...` doivent être écrits en entier (appels `client.post/get`, assertions sur `statut` via `approbations.lire`). Le fixture `demande` crée `approbations.creer("app_redemarrer", {"app": "crm"}, "r", "reversible")` sur une base temporaire (`monkeypatch.setattr(approbations, "DB", …)` + `init_db()`), `client` pose `APPROBATIONS_CLE=CLE`, `client_sans_cle` la retire. Valider l'id par regex `^[0-9a-f]{32}$` dans la route (paramètre `Path(pattern=…)`).

- [ ] **Step 2 : Vérifier l'échec**

Run : `cd core && python3 -m pytest test_approbations_routes.py -q`
Expected : FAIL (404 / import).

- [ ] **Step 3 : Implémenter**

`core/routers/approbations.py` :

```python
"""Routes d'approbation (S245). Deux publics, deux garde-fous :

- la brique `connexion` (relais Telegram) : clé partagée `X-Approbations-Cle`, comparée en temps
  constant, FAIL CLOSED (clé non configurée => 503) ;
- le tableau de bord (affichage du code destructif, liste) : session obligatoire.
"""
from __future__ import annotations

import hmac
import os
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path
from pydantic import BaseModel

import approbations
import approbations_canal
import auth
from etat import registre

router = APIRouter(prefix="/approbations", tags=["approbations"])

_ID = Path(pattern=r"^[0-9a-f]{32}$")


def exiger_cle(x_approbations_cle: str | None = Header(None)) -> None:
    attendue = os.getenv("APPROBATIONS_CLE", "")
    if not attendue:
        raise HTTPException(503, "Approbations par Telegram non configurées (APPROBATIONS_CLE).")
    if not hmac.compare_digest(x_approbations_cle or "", attendue):
        raise HTTPException(401, "Clé d'approbation invalide.")


class Decision(BaseModel):
    decision: Literal["ok", "ko"]
    par: str
    canal: str = "telegram"


class Armer(BaseModel):
    par: str


class Saisie(BaseModel):
    par: str
    code: str


@router.post("/{id_}/decision", dependencies=[Depends(exiger_cle)])
async def decision(body: Decision, id_: str = _ID):
    agir = approbations.approuver if body.decision == "ok" else approbations.refuser
    ok, raison = agir(id_, body.par, body.canal)
    lue = approbations.lire(id_)
    if lue:
        await approbations_canal.mettre_a_jour(registre, lue)
    return {"ok": ok, "raison": raison, "statut": lue and lue["statut"],
            "sensibilite": lue and lue["sensibilite"]}


@router.post("/{id_}/code/armer", dependencies=[Depends(exiger_cle)])
async def armer(body: Armer, id_: str = _ID):
    ok, raison = approbations.armer_saisie_code(id_, body.par)
    return {"ok": ok, "raison": raison}


@router.post("/code", dependencies=[Depends(exiger_cle)])
async def code(body: Saisie):
    r = approbations.valider_code_saisi(body.par, body.code)
    if r is None:
        return {"pris_en_charge": False}
    lue = approbations.lire(r["approbation_id"])
    if lue:
        await approbations_canal.mettre_a_jour(registre, lue)
    return {"pris_en_charge": True, **r}


@router.get("/en_attente", dependencies=[Depends(auth.exiger_session_api)])
async def en_attente():
    """Demandes ouvertes. Le `code` d'un destructif n'est exposé QU'ICI (session obligatoire) :
    c'est le canal distinct de Telegram qui fait sa valeur."""
    return {"approbations": approbations.en_attente()}


@router.post("/relancer")
async def relancer(x_approbations_cle: str | None = Header(None)):
    """Mode attente (approche B) : expire les périmées, relance les anciennes. Appelé par
    l'horloge S29 (tâche `approbations-relance` du manifest noyau)."""
    exiger_cle(x_approbations_cle)
    delai = int(os.getenv("APPROBATION_RELANCE_MIN", "60")) * 60
    maxi = int(os.getenv("APPROBATION_RELANCE_MAX", "3"))
    perimees = approbations.expirer_perimees()
    for id_ in perimees:
        lue = approbations.lire(id_)
        if lue:
            await approbations_canal.mettre_a_jour(registre, lue)
    relancees = []
    for d in approbations.a_relancer(delai, maxi):
        await approbations_canal.notifier(registre, d, relance=True)
        approbations.marquer_relancee(d["id"])
        relancees.append(d["id"])
    return {"expirees": perimees, "relancees": relancees}
```

Pour l'appel horloge : la tâche du manifest (Task 6) doit pouvoir envoyer l'en-tête ; si l'horloge ne sait pas poser d'en-tête personnalisé (lire `horloge.py`, fonction qui fait le POST), faire plutôt de `relancer` une route sans clé mais appelable uniquement en interne (même réseau docker) en la montant avec `dependencies=_tenant` comme `briefing/executer`, et supprimer l'appel `exiger_cle` — **vérifier d'abord comment `briefing/executer` est protégé et copier ce choix.**

`core/main.py` : ajouter `approbations` à l'import `from routers import (...)`, `import approbations as _approbations_store` (nom distinct du router), `_approbations_store.init_db()` après `horloge.init_db()`, et `app.include_router(approbations.router)` (pas de `dependencies` globales : chaque route porte la sienne).

`core/approbations_canal.py` : créé en Task 5 ; pour cette tâche, créer le stub minimal pour que les imports passent :

```python
"""Canal d'envoi des approbations vers la brique connexion (complété en tâche 5)."""


async def notifier(registre, demande: dict, relance: bool = False) -> None:
    return None


async def mettre_a_jour(registre, demande: dict) -> None:
    return None
```

- [ ] **Step 4 : Vérifier**

Run : `cd core && python3 -m pytest test_approbations_routes.py test_approbations.py test_approbations_garde.py -q`
Expected : PASS.

- [ ] **Step 5 : Commit**

```bash
git add core/routers/approbations.py core/approbations_canal.py core/main.py core/test_approbations_routes.py
git commit -m "feat(approbations): routes du Cœur (décision, code, liste, relance), clé partagée fail-closed"
```

---

### Task 5 : Canal Cœur → connexion (notifier, mettre à jour)

**Files :**
- Modify : `core/approbations_canal.py` (remplacer le stub)
- Modify : `core/outils.py` (brancher `_notifier_approbation`)
- Create : `core/test_approbations_canal.py`

**Interfaces :**
- Consumes : `approbations.lire/enregistrer_messages`, `orchestrateur._brique_base(registre, "connexion")`, env `CONNEXION_KEY` (même motif que `proactif._pousser_messagerie`, `core/proactif.py:214-233`).
- Produces :
  - `approbations_canal.charge_notification(demande: dict, relance: bool = False) -> dict` — **ne contient JAMAIS `code`** :
    `{"id", "resume", "sensibilite", "prerequis_ok": bool, "relance": bool, "expire_a": float}`
  - `async notifier(registre, demande, relance=False) -> None` — POST `{base}/approbation/notifier` ; la réponse `{"messages": [{"chat_id", "message_id"}]}` est stockée via `enregistrer_messages`
  - `async mettre_a_jour(registre, demande) -> None` — POST `{base}/approbation/mettre_a_jour` avec `{"messages": [...], "texte": str}`
  - `texte_final(demande: dict) -> str`

- [ ] **Step 1 : Tests qui échouent**

`core/test_approbations_canal.py` :

```python
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import approbations  # noqa: E402
import approbations_canal as canal  # noqa: E402


def _d(**kw):
    base = {"id": "a" * 32, "capacite": "app_reset", "resume": "app_reset(app='crm')",
            "sensibilite": "destructif", "statut": "en_attente", "code": "424242",
            "prerequis": {}, "expire_a": 1.0, "decide_par": None}
    base.update(kw)
    return base


def test_la_charge_ne_contient_jamais_le_code():
    charge = canal.charge_notification(_d())
    assert "code" not in charge and "424242" not in str(charge)


def test_prerequis_non_reunis_pas_de_bouton():
    assert canal.charge_notification(_d(prerequis={"sauvegarde": False}))["prerequis_ok"] is False
    assert canal.charge_notification(_d(prerequis={"sauvegarde": True}))["prerequis_ok"] is True
    assert canal.charge_notification(_d(prerequis={}))["prerequis_ok"] is True


def test_texte_final_par_statut():
    assert "✅" in canal.texte_final(_d(statut="approuvee"))
    assert "❌" in canal.texte_final(_d(statut="refusee"))
    assert "⌛" in canal.texte_final(_d(statut="expiree"))
    assert "424242" not in canal.texte_final(_d(statut="approuvee"))


def test_notifier_ne_leve_jamais_et_stocke_les_messages(monkeypatch, tmp_path):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()
    a = approbations.creer("c", {}, "r", "reversible")
    # injecter un faux transport : voir approbations_canal._poster (à rendre monkeypatchable)
    async def faux_poster(registre, chemin, corps):
        return {"messages": [{"chat_id": "42", "message_id": 9}]}
    monkeypatch.setattr(canal, "_poster", faux_poster)
    asyncio.run(canal.notifier(object(), a))
    assert approbations.lire(a["id"])["messages"] == [{"chat_id": "42", "message_id": 9}]


def test_brique_injoignable_ne_leve_pas(monkeypatch):
    async def casse(registre, chemin, corps):
        raise RuntimeError("down")
    monkeypatch.setattr(canal, "_poster", casse)
    asyncio.run(canal.notifier(object(), _d()))          # ne doit pas lever
    asyncio.run(canal.mettre_a_jour(object(), _d()))
```

- [ ] **Step 2 : Échec** — `cd core && python3 -m pytest test_approbations_canal.py -q` → FAIL (`charge_notification` absent).

- [ ] **Step 3 : Implémenter**

`core/approbations_canal.py` :

```python
"""Canal d'envoi des approbations vers la brique `connexion` (Telegram) — S245.

Best-effort : une brique injoignable ne doit JAMAIS faire échouer ni l'exécution d'un outil
ni une décision déjà enregistrée. Le code à 6 chiffres d'un destructif n'est JAMAIS envoyé ici :
il ne vit que dans l'app (GET /approbations/en_attente)."""
import logging
import os

import httpx

import approbations
import orchestrateur

logger = logging.getLogger(__name__)

_ICONES = {"approuvee": "✅ Approuvée", "refusee": "❌ Refusée", "expiree": "⌛ Expirée",
           "executee": "✅ Exécutée", "echec": "⚠️ Échec"}


def charge_notification(demande: dict, relance: bool = False) -> dict:
    prerequis = demande.get("prerequis") or {}
    return {"id": demande["id"], "resume": demande["resume"],
            "sensibilite": demande["sensibilite"],
            "prerequis_ok": all(prerequis.values()) if prerequis else True,
            "relance": relance, "expire_a": demande["expire_a"]}


def texte_final(demande: dict) -> str:
    etat = _ICONES.get(demande["statut"], demande["statut"])
    par = f" par {demande['decide_par']}" if demande.get("decide_par") else ""
    return f"{etat}{par}\n{demande['resume']}"


async def _poster(registre, chemin: str, corps: dict) -> dict:
    base = orchestrateur._brique_base(registre, "connexion")
    entetes = {"X-API-Key": os.getenv("CONNEXION_KEY")} if os.getenv("CONNEXION_KEY") else {}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{base}{chemin}", json=corps, headers=entetes)
        r.raise_for_status()
        return r.json()


async def notifier(registre, demande: dict, relance: bool = False) -> None:
    try:
        rep = await _poster(registre, "/approbation/notifier",
                            charge_notification(demande, relance))
        messages = rep.get("messages") or []
        if messages and demande.get("id"):
            approbations.enregistrer_messages(demande["id"], messages)
    except Exception as ex:  # noqa: BLE001 — jamais bloquant
        logger.warning("Approbation %s : notification Telegram impossible : %s",
                       demande.get("id", "?")[:8], ex)


async def mettre_a_jour(registre, demande: dict) -> None:
    """Édite les messages Telegram vers l'état final (✅ / ❌ / ⌛)."""
    if not demande.get("messages") or demande.get("statut") == "en_attente":
        return
    try:
        await _poster(registre, "/approbation/mettre_a_jour",
                      {"messages": demande["messages"], "texte": texte_final(demande)})
    except Exception as ex:  # noqa: BLE001
        logger.warning("Approbation %s : mise à jour Telegram impossible : %s",
                       demande.get("id", "?")[:8], ex)
```

Dans `core/outils.py`, après la définition de `_notifier_approbation` (stub de la Task 3), brancher le vrai canal :

```python
import approbations_canal   # en tête de fichier avec les autres imports


async def _notifier_approbation(registre, demande: dict) -> None:
    await approbations_canal.notifier(registre, demande)
```

(remplacer le corps du stub, ne pas en garder deux). Vérifier l'absence d'import circulaire (`approbations_canal` importe `orchestrateur`, qui ne doit pas importer `outils` — sinon importer `approbations_canal` paresseusement dans la fonction).

- [ ] **Step 4 : Vérifier**

Run : `cd core && python3 -m pytest test_approbations_canal.py test_approbations_garde.py test_approbations_routes.py -q`
Expected : PASS (le test de garde remplace `outils._notifier_approbation`, donc reste indépendant du réseau).

- [ ] **Step 5 : Commit**

```bash
git add core/approbations_canal.py core/outils.py core/test_approbations_canal.py
git commit -m "feat(approbations): canal vers connexion (notifier/mettre à jour), jamais le code sur Telegram"
```

---

### Task 6 : Brique connexion — approbateur, boutons Telegram, callbacks

**Files :**
- Modify : `briques/connexion/correspondance.py` (fin de fichier)
- Modify : `briques/connexion/adaptateurs.py` (classe `Telegram`, + dataclass `Callback`)
- Modify : `briques/connexion/client_assistant.py` (fin de fichier)
- Modify : `briques/connexion/pont.py` (`traiter_callback`, interception du code, `sonder`)
- Modify : `briques/connexion/main.py` (routes `/approbation/*`, webhook)
- Test : `briques/connexion/test_correspondance.py`, `test_adaptateurs.py`, `test_pont.py`, `test_main.py` (ajouts)

**Interfaces :**
- Consumes : routes Task 4 ; env `APPROBATIONS_CLE`, `NOYAU_ASSISTANT_URL` (déjà utilisée par `client_assistant.url_chat`).
- Produces :
  - `correspondance.est_approbateur(reseau: str, id_externe: str) -> bool` — vrai ssi l'entrée existe, `statut == "lie"` ET `approbateur is True`
  - `correspondance.approbateurs(reseau: str) -> list[str]` — `id_externe` des approbateurs `lie`
  - `adaptateurs.Callback` (dataclass) : `reseau, from_id, chat_id, chat_type, message_id, callback_id, data`
  - `Telegram.parser_callback(payload: dict) -> Callback | None`
  - `Telegram.envoyer_boutons(id_externe: str, texte: str, boutons: list[list[dict]]) -> dict | None` → `{"chat_id": str, "message_id": int}`
  - `Telegram.repondre_callback(callback_id: str, texte: str = "") -> None`
  - `Telegram.editer_message(chat_id: str, message_id: int, texte: str) -> None` (retire aussi le clavier)
  - `Telegram.recuperer()` renvoie désormais des `Entrant` **et** des `Callback` ; `allowed_updates=["message","callback_query"]`
  - `client_assistant.decider_approbation(id_, decision, par) -> dict`, `armer_code(id_, par) -> dict`, `soumettre_code(par, code) -> dict`
  - `pont.traiter_callback(reseau, cb) -> dict`
  - routes connexion : `POST /approbation/notifier`, `POST /approbation/mettre_a_jour` (toutes deux `Depends(cle_api)`)

- [ ] **Step 1 : Tests qui échouent**

Ajouter, en lisant d'abord le style de chaque fichier de test existant (fixtures, fausse table de correspondances, `FauxAdaptateur`, `_run`) :

`test_correspondance.py` :
```python
def test_approbateur_exige_lie_et_drapeau(...):
    # lie + approbateur True => True
    # lie sans drapeau => False ; en_attente + drapeau => False
    # statut "ouvert" + drapeau => False  (CONNEXION_OUVERT=1 n'ouvre JAMAIS l'approbation)
    # inconnu => False
def test_approbateurs_liste_seulement_les_lies_du_reseau(...): ...
```

`test_adaptateurs.py` (Telegram, `httpx` mocké comme les tests existants) :
```python
def test_parser_callback_extrait_les_champs():
    payload = {"update_id": 1, "callback_query": {"id": "cb1", "from": {"id": 42},
               "message": {"message_id": 7, "chat": {"id": 42, "type": "private"}},
               "data": "ap:" + "a" * 32 + ":ok"}}
    cb = A.Telegram().parser_callback(payload)
    assert (cb.from_id, cb.chat_id, cb.chat_type, cb.message_id, cb.callback_id) == ("42", "42", "private", 7, "cb1")

def test_parser_callback_ignore_un_message_normal(): ...
def test_parser_entrant_ignore_un_callback_query():   # [] — le message normal n'est pas affecté
def test_recuperer_demande_les_callback_query():       # params contient allowed_updates (JSON) avec "callback_query"
def test_envoyer_boutons_poste_un_inline_keyboard():  # reply_markup.inline_keyboard présent, retourne chat_id/message_id
def test_editer_message_retire_le_clavier():          # editMessageText avec reply_markup {"inline_keyboard": []}
def test_repondre_callback_appelle_answerCallbackQuery(): ...
```

`test_pont.py` — cas de sécurité de `traiter_callback` (tous obligatoires, un test chacun) :
```python
# 1. callback d'un from_id qui n'est PAS approbateur  -> ignoré, aucun appel au Cœur, journalisé
# 2. approbateur mais chat_type "group"               -> ignoré
# 3. approbateur mais chat_id != from_id              -> ignoré
# 4. callback_data forgé ("ap:zzz:ok", "x:..:ok", trop long, décision inconnue) -> ignoré
# 5. callback valide "ok" sur réversible  -> POST décision ok au Cœur ; answerCallbackQuery ; message édité
# 6. callback valide "ko"                 -> POST décision ko
# 7. destructif + "ok" (Cœur répond raison=code_requis) -> armer_code appelé ; message « saisis le code
#    affiché dans l'app » ; AUCUN code dans le texte envoyé
# 8. raison expiree / deja_decidee        -> message édité en ⌛ / info, jamais d'exécution côté brique
# 9. un message texte « 123456 » d'un approbateur AVEC saisie armée (soumettre_code -> pris_en_charge True)
#    n'est PAS relayé à l'assistant ; réponse : « ✅ Code bon » / « Code faux, N essais restants » / « refusée »
# 10. même message « 123456 » avec pris_en_charge False -> relayé à l'assistant comme avant (non-régression)
# 11. un non-approbateur envoie « 123456 » -> relayé à l'assistant, soumettre_code JAMAIS appelé
```
Mocker `client_assistant.decider_approbation/armer_code/soumettre_code` (monkeypatch) et utiliser `FauxAdaptateur` étendu de `parser_callback/repondre_callback/editer_message/envoyer_boutons` qui enregistrent leurs appels.

`test_main.py` :
```python
def test_notifier_envoie_a_chaque_approbateur_avec_boutons(...)   # 2 approbateurs lie => 2 messages ; retourne messages[]
def test_notifier_sans_approbateur_n_envoie_rien(...)             # {"messages": []} (fail closed)
def test_notifier_prerequis_non_reunis_sans_bouton_approuver(...) # texte « en attente de preuves », pas de clavier
def test_notifier_destructif_dit_que_le_code_est_dans_l_app(...)  # aucun code dans le texte
def test_mettre_a_jour_edite_chaque_message(...)
def test_webhook_callback_query_est_route_vers_traiter_callback(...)
def test_notifier_exige_la_cle_api(...)                            # avec API_KEYS posée => 401 sans clé
```

- [ ] **Step 2 : Échec** — `cd briques/connexion && python3 -m pytest -q` → les nouveaux tests FAIL.

- [ ] **Step 3 : Implémenter**

`correspondance.py` (fin de fichier) :
```python
def est_approbateur(reseau: str, id_externe: str) -> bool:
    """Droit d'APPROUVER une action sensible (S245). Triple condition, vide par défaut :
    entrée connue, statut « lie » (JAMAIS « ouvert » : CONNEXION_OUVERT=1 ne donne aucun
    droit d'approbation) et drapeau `approbateur` explicite."""
    e = table().get(_cle(reseau, str(id_externe)))
    return bool(e) and e.get("statut") == "lie" and e.get("approbateur") is True


def approbateurs(reseau: str) -> list[str]:
    return [e["id_externe"] for e in table().values()
            if e.get("reseau") == reseau and e.get("statut") == "lie"
            and e.get("approbateur") is True]
```
Vérifier dans `main.py` (`/correspondances`, route de liaison) comment un admin pose `utilisateur`/`statut` et **ajouter la possibilité de poser `approbateur`** (route admin existante, ou petite route `POST /correspondances/{cle}/approbateur` sous `cle_api`) — sans cela personne ne peut devenir approbateur. Test associé dans `test_main.py`.

`adaptateurs.py` : ajouter, à côté de `Entrant` :
```python
@dataclass
class Callback:
    """Un clic sur un bouton inline (Telegram `callback_query`)."""
    reseau: str
    from_id: str
    chat_id: str
    chat_type: str
    message_id: int
    callback_id: str
    data: str
```
et dans `Telegram` :
```python
    def parser_callback(self, payload: dict) -> "Callback | None":
        cq = (payload or {}).get("callback_query")
        if not cq:
            return None
        msg = cq.get("message") or {}
        chat = msg.get("chat") or {}
        de = cq.get("from") or {}
        if not (de.get("id") and chat.get("id") and cq.get("id")):
            return None
        return Callback(self.nom, str(de["id"]), str(chat["id"]), chat.get("type") or "",
                        int(msg.get("message_id") or 0), str(cq["id"]), cq.get("data") or "")

    async def envoyer_boutons(self, id_externe: str, texte: str, boutons: list) -> dict | None:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(self._api("sendMessage"), json={
                "chat_id": id_externe, "text": texte,
                "reply_markup": {"inline_keyboard": boutons}} if boutons else
                {"chat_id": id_externe, "text": texte})
            r.raise_for_status()
            m = (r.json().get("result") or {})
        return {"chat_id": str((m.get("chat") or {}).get("id", id_externe)),
                "message_id": m.get("message_id")}

    async def repondre_callback(self, callback_id: str, texte: str = "") -> None:
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(self._api("answerCallbackQuery"),
                         json={"callback_query_id": callback_id, "text": texte[:200]})

    async def editer_message(self, chat_id: str, message_id: int, texte: str) -> None:
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(self._api("editMessageText"), json={
                "chat_id": chat_id, "message_id": message_id, "text": texte,
                "reply_markup": {"inline_keyboard": []}})
```
Dans `Telegram.recuperer`, remplacer l'appel `getUpdates` par `params={"offset": offset, "timeout": 0, "allowed_updates": json.dumps(["message", "callback_query"])}` (ajouter `import json` s'il manque) et, dans la boucle, après `entrants.extend(self.parser_entrant(upd))`, ajouter :
```python
            cb = self.parser_callback(upd)
            if cb:
                entrants.append(cb)
```
`parser_entrant` reste inchangé (un `callback_query` n'a pas de `message` de premier niveau → `[]`).

`client_assistant.py` (fin de fichier) :
```python
def _base_noyau() -> str:
    return os.getenv("NOYAU_ASSISTANT_URL", "http://host.docker.internal:5100").rstrip("/")


def _entetes_approbation() -> dict:
    return {"X-Approbations-Cle": os.getenv("APPROBATIONS_CLE", "")}


async def _poster_approbation(chemin: str, corps: dict, timeout: float = 15.0) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"{_base_noyau()}{chemin}", json=corps, headers=_entetes_approbation())
        r.raise_for_status()
        return r.json()


async def decider_approbation(id_: str, decision: str, par: str) -> dict:
    return await _poster_approbation(f"/approbations/{id_}/decision",
                                     {"decision": decision, "par": par, "canal": "telegram"})


async def armer_code(id_: str, par: str) -> dict:
    return await _poster_approbation(f"/approbations/{id_}/code/armer", {"par": par})


async def soumettre_code(par: str, code: str) -> dict:
    return await _poster_approbation("/approbations/code", {"par": par, "code": code})
```

`pont.py` : ajouter en tête `import re` (s'il manque) et :
```python
_CB = re.compile(r"^ap:([0-9a-f]{32}):(ok|ko)$")
_CODE = re.compile(r"^\d{6}$")


async def traiter_callback(reseau: str, cb) -> dict:
    """Clic sur un bouton d'approbation. TOUTE vérification d'identité est ici, avant le Cœur :
    approbateur explicite (lie), chat privé, callback_data strict. Un émetteur non autorisé est
    ignoré SANS réponse utile (pas d'oracle) et journalisé."""
    ad = adaptateurs.obtenir(reseau)
    m = _CB.match(cb.data or "")
    if (ad is None or not m or cb.chat_type != "private" or cb.chat_id != cb.from_id
            or not correspondance.est_approbateur(reseau, cb.from_id)):
        logging.getLogger(__name__).warning(
            "Approbation : callback ignoré (from=%s chat=%s type=%s)", cb.from_id, cb.chat_id,
            cb.chat_type)
        return {"ok": False, "raison": "ignore"}
    id_, decision = m.group(1), m.group(2)
    par = f"{reseau}:{cb.from_id}"
    try:
        rep = await client_assistant.decider_approbation(id_, decision, par)
        if rep.get("raison") == "code_requis" and decision == "ok":
            armement = await client_assistant.armer_code(id_, par)
            if armement.get("ok"):
                await ad.repondre_callback(cb.callback_id, "Code requis")
                await ad.envoyer(cb.chat_id, "🔐 Action destructive : saisis ici le code à "
                                             "6 chiffres affiché dans l'app Workplace "
                                             "(3 essais, 5 min).")
                return {"ok": True, "raison": "code_demande"}
            rep = armement
        message = {"ok": "Décision enregistrée", "expiree": "⌛ Demande expirée",
                   "deja_decidee": "Déjà traitée", "prerequis": "Pas encore prête",
                   "introuvable": "Demande inconnue"}.get(rep.get("raison"), "Impossible")
        await ad.repondre_callback(cb.callback_id, message)
        return {"ok": bool(rep.get("ok")), "raison": rep.get("raison")}
    except Exception:  # noqa: BLE001 — Cœur injoignable : repli honnête, aucune exécution
        try:
            await ad.repondre_callback(cb.callback_id, "Service indisponible, réessaie")
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "raison": "noyau_injoignable"}


async def _tenter_code(reseau: str, ad, entrant) -> dict | None:
    """Un message « 123456 » d'un approbateur qui a une saisie armée est un CODE, pas une
    question pour l'assistant. None => message ordinaire (relayé comme avant)."""
    if not _CODE.match((entrant.texte or "").strip()):
        return None
    if not correspondance.est_approbateur(reseau, entrant.id_externe):
        return None
    try:
        r = await client_assistant.soumettre_code(f"{reseau}:{entrant.id_externe}",
                                                  entrant.texte.strip())
    except Exception:  # noqa: BLE001 — en cas de doute, on ne mange pas le message
        return None
    if not r.get("pris_en_charge"):
        return None
    texte = {"ok": "✅ Code bon, action approuvée.",
             "code_faux": f"❌ Code faux — {r.get('restants', 0)} essai(s) restant(s).",
             "essais_epuises": "❌ 3 codes faux : demande REFUSÉE.",
             "expiree": "⌛ Demande expirée.",
             "deja_decidee": "Déjà traitée."}.get(r.get("raison"), "Code non pris en compte.")
    await ad.envoyer(entrant.id_externe, texte)
    return {"ok": True, "code": r.get("raison")}
```
Dans `traiter`, juste après le bloc `if not corr["autorise"]: … return …` et la transcription vocale (donc après que `entrant.texte` est connu), insérer :
```python
    if envoyer and ad.configure():
        pris = await _tenter_code(reseau, ad, entrant)
        if pris:
            return pris
```
Dans `sonder`, remplacer la compréhension de listes par :
```python
    comptes = []
    for e in entrants:
        if isinstance(e, adaptateurs.Callback):
            comptes.append(await traiter_callback(reseau, e))
        else:
            comptes.append(await traiter(reseau, e))
```

`main.py` :
```python
class NotifApprobation(BaseModel):
    id: str
    resume: str
    sensibilite: str
    prerequis_ok: bool = True
    relance: bool = False
    expire_a: float = 0


class MajApprobation(BaseModel):
    messages: list[dict]
    texte: str


_ICONE = {"reversible": "🟡", "donnees": "🟠", "destructif": "🔴"}


@app.post("/approbation/notifier", tags=["admin"])
async def approbation_notifier(body: NotifApprobation, _cle: str = Depends(cle_api)):
    """Envoie la demande à CHAQUE approbateur lié, avec boutons. Aucun approbateur => rien n'est
    envoyé (fail closed : on ne diffuse jamais une demande à un non-approbateur)."""
    ad = adaptateurs.obtenir("telegram")
    messages = []
    if ad is not None and ad.configure():
        entete = "🔁 Rappel — " if body.relance else ""
        for dest in correspondance.approbateurs("telegram"):
            if not body.prerequis_ok:
                texte = f"{entete}{_ICONE.get(body.sensibilite, '')} Approbation en attente de preuves\n{body.resume}"
                clavier = []
            else:
                suffixe = ("\n🔐 Après avoir appuyé, saisis le code à 6 chiffres affiché dans l'app."
                           if body.sensibilite == "destructif" else "")
                texte = f"{entete}{_ICONE.get(body.sensibilite, '')} Approbation demandée ({body.sensibilite})\n{body.resume}{suffixe}"
                clavier = [[{"text": "✅ Approuver", "callback_data": f"ap:{body.id}:ok"},
                            {"text": "❌ Refuser", "callback_data": f"ap:{body.id}:ko"}]]
            try:
                m = await ad.envoyer_boutons(dest, texte, clavier)
                if m:
                    messages.append(m)
            except Exception:  # noqa: BLE001 — un destinataire KO ne bloque pas les autres
                continue
    return {"messages": messages}


@app.post("/approbation/mettre_a_jour", tags=["admin"])
async def approbation_mettre_a_jour(body: MajApprobation, _cle: str = Depends(cle_api)):
    ad = adaptateurs.obtenir("telegram")
    faits = 0
    if ad is not None and ad.configure():
        for m in body.messages:
            try:
                await ad.editer_message(m["chat_id"], m["message_id"], body.texte)
                faits += 1
            except Exception:  # noqa: BLE001
                continue
    return {"edites": faits}
```
et dans le webhook, **avant** `entrants = ad.parser_entrant(payload)` :
```python
    parse_cb = getattr(ad, "parser_callback", None)
    cb = parse_cb(payload) if parse_cb else None
    if cb:
        return {"ok": True, "callback": (await pont.traiter_callback(reseau, cb)).get("raison")}
```
(importer `correspondance` et `BaseModel` s'ils ne le sont pas déjà dans `main.py`.)

- [ ] **Step 4 : Vérifier**

Run : `cd briques/connexion && python3 -m pytest -q`
Expected : tout PASS, y compris les tests existants (non-régression du pont et du sondage).

- [ ] **Step 5 : Commit**

```bash
git add briques/connexion/
git commit -m "feat(connexion): approbation Telegram — boutons, callback_query, approbateur explicite, code à 6 chiffres"
```

---

### Task 7 : Mode attente (horloge) et variables d'environnement

**Files :**
- Modify : `briques/noyau/manifest.json` (tâche `approbations-relance`)
- Modify : `core/docker-compose.yml`, `briques/connexion/docker-compose.yml`, `.env.example` (ou l'équivalent trouvé par `grep -rn "CONNEXION_KEY" --include="*.yml" --include=".env*" .`) — ajouter `APPROBATIONS_CLE`, `APPROBATION_RELANCE_MIN`, `APPROBATION_RELANCE_MAX`, `APPROBATION_TTL_*_MIN`
- Test : `core/test_approbations_routes.py` (cas `relancer`, déjà listé en Task 4) + un test de contrat manifeste

- [ ] **Step 1 : Test qui échoue** — dans `core/test_approbations_routes.py` :

```python
def test_le_manifeste_noyau_declare_la_tache_de_relance():
    import json, pathlib
    m = json.loads((pathlib.Path(__file__).parents[1] / "briques/noyau/manifest.json").read_text())
    t = {x["nom"]: x for x in m["taches"]}["approbations-relance"]
    assert t["methode"] == "POST" and t["chemin"] == "/approbations/relancer"
    assert t["cadence_heures"] <= 0.25          # l'horloge bat toutes les 15 min
```
Run : `cd core && python3 -m pytest test_approbations_routes.py::test_le_manifeste_noyau_declare_la_tache_de_relance -q` → FAIL (`KeyError`).

- [ ] **Step 2 : Implémenter** — ajouter dans `taches` de `briques/noyau/manifest.json`, calqué sur `briefing-quotidien` :

```json
  {
    "nom": "approbations-relance",
    "description": "Mode attente (S245) : expire les demandes d'approbation périmées et relance sur Telegram celles qui attendent depuis APPROBATION_RELANCE_MIN. L'assistant n'agit JAMAIS sans validation : la relance ne fait que reposer la question.",
    "methode": "POST",
    "chemin": "/approbations/relancer",
    "cadence_heures": 0.25,
    "idempotent": true,
    "tolere_echec": true
  }
```
et ajouter les variables d'environnement aux fichiers compose (Cœur : `APPROBATIONS_CLE`, `APPROBATION_RELANCE_MIN`, `APPROBATION_RELANCE_MAX`, `APPROBATION_TTL_REVERSIBLE_MIN`, `APPROBATION_TTL_DONNEES_MIN`, `APPROBATION_TTL_DESTRUCTIF_MIN` ; connexion : `APPROBATIONS_CLE` **de même valeur**). Piège connu du dépôt (`fix-env-shadow-composes`) : vérifier qu'un `environment:` explicite ne masque pas une valeur du `.env`.

Reprendre le choix d'auth de la Task 4 pour `/approbations/relancer` : si l'horloge ne peut pas poser `X-Approbations-Cle`, appliquer le même régime que `/briefing/executer`.

- [ ] **Step 3 : Vérifier** — `cd core && python3 -m pytest test_approbations_routes.py test_catalogue.py -q` → PASS ; puis `make test-core` (la suite complète du Cœur doit rester verte : le manifeste noyau est lu par plusieurs tests).

- [ ] **Step 4 : Commit**

```bash
git add briques/noyau/manifest.json core/docker-compose.yml briques/connexion/docker-compose.yml core/test_approbations_routes.py
git commit -m "feat(approbations): mode attente — tâche d'horloge de relance + variables d'environnement"
```

---

### Task 8 : Mutation de la garde, ADR, clôture

**Files :**
- Create : `docs/decisions/2026-11-25-approbation-telegram.md`
- Modify : `docs/sprints/S245-socle-approbation-telegram.md` (statut + « Questions tranchées »)
- Modify : `docs/sprints/EPOPEE-livraison-support-assistant.md` (ligne S245 du tableau + statut global)

- [ ] **Step 1 : Preuve par mutation (convention du dépôt, cf. S222)**

Neutraliser temporairement la garde dans `core/outils.py` : remplacer `niveau = est_sensible(nom, registre)` par `niveau = None`.

Run : `cd core && python3 -m pytest test_approbations_garde.py -q`
Expected : les tests de **sécurité** échouent (`test_sans_approbation_rien_ne_s_execute…`, `test_le_llm_ne_peut_pas_se_confirmer_tout_seul`, `test_approbation_pour_crm_ne_vaut_pas_pour_autre`, `test_refus_bloque…`, `test_destructif_exige_le_code…`) ; les tests de **non-régression** (`test_lecture_passe…`, `test_capacite_sans_sensibilite…`) passent. Noter les comptes **mesurés** (ne pas reprendre ce plan) dans l'ADR.

Faire la même chose pour une 2e mutation côté connexion : dans `pont.traiter_callback`, retirer `or not correspondance.est_approbateur(...)` → les tests « callback d'un non-approbateur » et « mauvais chat » doivent échouer. **Restaurer ensuite les deux mutations** (`git diff` doit être vide sur `core/outils.py` et `pont.py` par rapport au dernier commit).

- [ ] **Step 2 : Suites complètes**

Run : `make test-core` puis `cd briques/connexion && python3 -m pytest -q`
Expected : verts. Rapporter les comptes réellement affichés (les comptages de sous-agents se sont déjà révélés peu fiables : relancer soi-même).

- [ ] **Step 3 : ADR**

`docs/decisions/2026-11-25-approbation-telegram.md`, calqué sur `docs/decisions/2026-08-09-gate-action-structurel.md` (en-tête Date/Statut/Portée/Fichiers liés), sections : **Le trou** (gate conversationnel : pas de fil pour un incident, pas de boutons, rien de persistant, pas de niveaux, trou co-agent/MCP), **La décision** (Cœur = autorité, `exiger()` dans `outils.executer`, brique connexion = relais), **Décisions tranchées** (approbateur explicite ; code à 6 chiffres affiché dans l'app ; TTL 30/120/15 min configurables), **Écarts assumés** (les 3 de ce plan), **Ce que ça ne garantit PAS** (compréhension de l'humain ; compte Telegram compromis seul atténué par le code mais pas pour réversible/données ; Cœur compromis ; `APPROBATIONS_CLE` fuitée = n'importe quel client réseau interne peut décider : à garder dans le réseau docker ; capacités sans `sensibilite` inchangées ; les messages Telegram ne sont édités que si la brique est joignable), **Limites assumées** (SQLite mono-processus ; pas de migration des 133 actions ; page « maintenance » = S246/S247), **Filet** (fichiers de test + résultat de la mutation, chiffres mesurés).

- [ ] **Step 4 : Mettre à jour les documents de suivi**

Dans `docs/sprints/S245-…md` : statut « CODÉ, preuve LIVE Telegram différée (SLIVE) » ; remplacer la section « Questions à trancher » par les 3 réponses du 2026-11-25. Dans l'épopée : tableau → S245 « codé (LIVE à prouver) » ; statut global à jour.

- [ ] **Step 5 : Commit**

```bash
git add docs/
git commit -m "docs(s245): ADR approbation Telegram, S245 et épopée à jour"
```

- [ ] **Step 6 : Clôture de branche**

Invoquer `superpowers:finishing-a-development-branch`. Rappel du régime « preuve Docker différé » : la preuve avec le vrai bot sur le HP est regroupée en SLIVE (poser `APPROBATIONS_CLE` des deux côtés, marquer son compte `approbateur: true` dans `correspondances.json`, déclencher une capacité `sensibilite: reversible` de test, vérifier bouton → exécution → message ✅ ; puis un destructif : bouton → code lu dans l'app → saisie).

---

## Self-review

**Couverture du fichier S245 :**
- Enregistrement persistant + champs (`id` 128 bits, empreinte réutilisée, résumé, sensibilité, origine, statut, dates, `decide_par`, canal, résultat) → Task 1.
- Machine à états stricte, usage unique, consommation atomique → Tasks 1-2 (`_transition`, `consommer`, test concurrent 12 threads).
- Niveaux dans `manifest.json`, capacité sans champ inchangée → Task 3 (`catalogue.py`, tests de non-régression).
- Prérequis (message sans bouton puis édité) → Task 2 (`satisfaire_prerequis`), Task 6 (notifier sans clavier), Task 5/4 (`mettre_a_jour`). Le re-notify quand les preuves sont réunies est appelé par S247 (`satisfaire_prerequis` + `approbations_canal.notifier`) : hors périmètre S245, noté comme point d'accroche.
- Garde dans le chemin commun `outils.executer` / ferme le trou co-agent-MCP → Task 3.
- Telegram : `inline_keyboard`, `callback_data ap:<id>:<ok|ko>`, `callback_query`, `answerCallbackQuery`, `editMessageText`, autorisation par identité, chat privé → Task 6.
- Destructif : code à 6 chiffres (décision Q2) → Tasks 2 et 6.
- Mode attente (relance X min) → Tasks 2, 4, 7. Page « maintenance » : explicitement S246/S247.
- Journal append-only → Task 1 (triggers). Réutilisation du journal existant : écart assumé n°3.
- Tests demandés : transitions interdites (`_transition` lève ; test via API), expiration, rejeu, double consommation, mauvais `from.id`/chat/callback forgé/id inconnu/empreinte modifiée, persistance, mutation testing → Tasks 1, 2, 3, 6, 8.
- Q1 (approbateur explicite), Q2 (code), Q3 (TTL configurables) → Global Constraints + Tasks 1, 2, 6.

**Écart de la garde « origine non conversation »** : voir écart n°2 (la garde s'applique à toutes les origines pour les capacités sensibles). À valider si l'utilisateur voulait garder le simple « oui » conversationnel pour un `reversible`.

**Cohérence des signatures :** `exiger` → `(id|None, msg|None, demande|None)` utilisé tel quel par `outils.executer` ; `valider_code_saisi` → `dict|None` consommé par la route `/approbations/code` (`pris_en_charge`) puis par `pont._tenter_code` ; `approuver`/`refuser` → `(bool, str)` consommés par la route `decision` ; `Callback` défini en Task 6 avant son usage dans `sonder`.

**Points à vérifier par l'exécutant (lus en survol, pas en entier) :**
1. Fixture de client FastAPI et surcharge de session pour `test_approbations_routes.py` (copier un test de route existant).
2. Protection de `/briefing/executer` (Task 4/7) pour décider de l'auth de `/approbations/relancer`.
3. Route d'admin de `correspondance` pour poser `approbateur: true` (Task 6) — sans elle personne ne peut approuver.
4. Import circulaire éventuel `outils` ↔ `approbations_canal` ↔ `orchestrateur` (Task 5).
5. Les clés de messages d'édition ne sont stockées que si la brique répond au `notifier` ; un message jamais enregistré ne sera pas édité (le clic ultérieur sur un bouton expiré le met à jour via la réponse `answerCallbackQuery`).
