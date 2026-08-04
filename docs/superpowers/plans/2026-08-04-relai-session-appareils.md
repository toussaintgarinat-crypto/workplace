# Relai de session propre entre appareils — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Empêcher qu'une deuxième connexion sur un compte écrase silencieusement le travail en cours de la première, en implémentant une éviction propre avec point de contrôle préalable — pas de blocage strict, pas de coexistence silencieuse : la nouvelle session prend la main, mais seulement après s'être assurée que rien de l'ancienne n'est perdu, et l'ancienne est prévenue au lieu de planter sans explication.

**Architecture:** Un registre de session actif par compte (SQLite, même motif que `core/horloge.py`) tenu par le Cœur. À chaque callback de login réussi (`core/routers/auth.py`), on interroge le registre : s'il existe déjà une session pour ce compte, on déclenche un point de contrôle (stub aujourd'hui, branché sur la réplication continue — Litestream/WAL-G — une fois `docs/superpowers/plans/2026-08-04-sauvegarde-continue-rpo.md` en place), PUIS on enregistre la nouvelle session avec un numéro de génération incrémenté. Chaque requête protégée (`exiger_session` dans `core/auth.py`) compare la génération portée par le cookie à la génération courante du registre : en cas d'écart, la session est révoquée et redirigée vers `/auth/login`, avec un indicateur repris par le dashboard pour afficher un message clair au lieu d'un échec silencieux.

**Tech Stack:** Python (FastAPI, SQLite via `sqlite3` stdlib — aucune nouvelle dépendance), JavaScript vanilla (bandeau du dashboard).

## Global Constraints

- Aucune nouvelle dépendance Python (le motif SQLite + `sqlite3` stdlib est déjà établi dans `core/horloge.py` et `core/proactif.py` — le suivre à l'identique).
- Ne jamais faire dépendre ce plan du plan de sauvegarde continue : `checkpoint_session.declencher_checkpoint` doit être un point d'extension (stub journalisant aujourd'hui), pas un appel bloquant vers un système qui n'existe pas encore. Chaque tâche doit rester testable isolément.
- Respecter le motif de session existant : cookie chiffré AES-GCM, **aucune table de session en base pour le contenu du cookie lui-même** (`core/auth.py`) — le nouveau registre ne stocke QUE la génération/l'appareil/l'horodatage, jamais de token.
- Suivre le style de test déjà en place dans `core/test_auth.py` / `core/test_auth_routes.py` (pytest simple, `monkeypatch`, `TestClient`) — pas de nouveau framework de test.
- `AUTH_ENABLED=false` (défaut dev/tests) doit rester totalement inchangé : ce chantier n'a d'effet que si l'authentification Keycloak est active, comme le reste de `core/auth.py`.

---

## Recherche déjà faite (pour ne pas la refaire)

- Le Cœur n'a **aucun** mécanisme de session côté serveur aujourd'hui : `core/auth.py` fonctionne en cookie chiffré AES-GCM autoporteur (`chiffrer_cookie`/`dechiffrer_cookie`), sans table de session. Il faut donc introduire un vrai état côté serveur pour détecter une deuxième connexion — ça n'existe nulle part à réutiliser.
- Il n'existe pas de canal live persistant vers le navigateur (pas de WebSocket, pas de SSE hors du flux de conversation `core/routers/assistant.py` qui ne dure qu'un tour de chat). La notification "reprise sur un autre appareil" ne peut donc pas être **poussée** instantanément — elle est portée par la redirection `/auth/login` que `exiger_session` déclenche déjà pour toute session invalide, ce qui arrive en pratique très vite (le dashboard fait des appels API en continu). C'est une limite assumée, documentée en fin de plan.
- `core/routers/auth.py` : `auth_callback` est le seul endroit où une session est créée — c'est le point d'insertion naturel du registre.
- `core/auth.py::exiger_session` est le seul endroit où une session est validée à chaque requête — c'est le point d'insertion naturel de la vérification de génération.
- Motif de redirection post-login déjà existant et réutilisable tel quel : `_next_sur()` dans `core/routers/auth.py` valide un chemin interne (`next=/dashboard?motif=...`) et le CØur le respecte déjà pour rediriger après le callback — pas besoin d'un nouvel endpoint pour porter le message.
- Motif de base SQLite à copier : `core/horloge.py` (`DB = os.getenv("HORLOGE_DB", "/data/horloge.db")`, `sqlite3.connect`, `row_factory = sqlite3.Row`, `init_db()` avec `CREATE TABLE IF NOT EXISTS`).
- `core/docker-compose.yml` monte déjà `core_data:/data` — le nouveau fichier SQLite y vivra sans changement de volume, seulement une nouvelle variable d'environnement.

---

## File Structure

- Create: `core/session_registre.py` — registre SQLite des sessions actives par compte.
- Create: `core/test_session_registre.py` — tests du registre.
- Create: `core/checkpoint_session.py` — point d'extension du point de contrôle avant éviction.
- Create: `core/test_checkpoint_session.py` — test du stub.
- Modify: `core/routers/auth.py` — `auth_callback` enregistre/évince via le registre.
- Modify: `core/test_auth_routes.py` — nouveau test de scénario d'éviction au callback.
- Modify: `core/auth.py` — `exiger_session` vérifie la génération.
- Modify: `core/test_auth.py` — nouveaux tests de la vérification de génération.
- Modify: `core/dashboard.html` — bandeau d'information si `?motif=reprise_ailleurs`.
- Modify: `core/docker-compose.yml` — variable `SESSION_REGISTRE_DB`.

---

### Task 1: Registre de session actif par compte

**Files:**
- Create: `core/session_registre.py`
- Create: `core/test_session_registre.py`

**Interfaces:**
- Produces: `session_registre.nouvelle_session(sub: str, appareil: str | None) -> tuple[int, AncienneSession | None]`, `session_registre.generation_actuelle(sub: str) -> int | None`, `session_registre.AncienneSession` (NamedTuple : `generation: int`, `appareil: str | None`, `connecte_a: float`). Utilisé par Task 3 (`auth_callback`) et Task 4 (`exiger_session`).

- [ ] **Step 1: Écrire le test qui échoue**

Créer `/Users/garinat_t/Desktop/Workplace/core/test_session_registre.py` :

```python
"""Registre des sessions actives par compte (relai propre entre appareils).

$ cd core && python3 -m pytest test_session_registre.py -v
"""
import os
import tempfile

os.environ["SESSION_REGISTRE_DB"] = os.path.join(tempfile.mkdtemp(), "session_registre.db")

import session_registre  # noqa: E402


def test_premiere_session_ne_renvoie_aucune_ancienne_session():
    generation, ancienne = session_registre.nouvelle_session("marina", "iPhone")
    assert generation == 1
    assert ancienne is None


def test_deuxieme_session_incremente_et_renvoie_l_ancienne():
    session_registre.nouvelle_session("thomas", "iPhone")
    generation, ancienne = session_registre.nouvelle_session("thomas", "MacBook")
    assert generation == 2
    assert ancienne is not None
    assert ancienne.generation == 1
    assert ancienne.appareil == "iPhone"


def test_generation_actuelle_reflete_la_derniere_connexion():
    session_registre.nouvelle_session("alex", "iPhone")
    session_registre.nouvelle_session("alex", "MacBook")
    assert session_registre.generation_actuelle("alex") == 2


def test_generation_actuelle_compte_inconnu_renvoie_none():
    assert session_registre.generation_actuelle("jamais-connecte") is None


def test_deux_comptes_ont_des_generations_independantes():
    session_registre.nouvelle_session("compte_a", "iPhone")
    session_registre.nouvelle_session("compte_b", "iPhone")
    session_registre.nouvelle_session("compte_a", "MacBook")
    assert session_registre.generation_actuelle("compte_a") == 2
    assert session_registre.generation_actuelle("compte_b") == 1
```

- [ ] **Step 2: Vérifier que le test échoue (module inexistant)**

Run: `cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest test_session_registre.py -v`
Expected: `ModuleNotFoundError: No module named 'session_registre'`

- [ ] **Step 3: Créer `core/session_registre.py`**

```python
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
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest test_session_registre.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/garinat_t/Desktop/Workplace
git add core/session_registre.py core/test_session_registre.py
git commit -m "feat(core): registre de session active par compte"
```

---

### Task 2: Point de contrôle avant éviction (stub extensible)

**Files:**
- Create: `core/checkpoint_session.py`
- Create: `core/test_checkpoint_session.py`

**Interfaces:**
- Consumes: rien (module autonome).
- Produces: `checkpoint_session.declencher_checkpoint(sub: str) -> None`. Appelé par Task 3. Remplacé plus tard (hors de ce plan) par un vrai appel vers Litestream/WAL-G une fois `docs/superpowers/plans/2026-08-04-sauvegarde-continue-rpo.md` livré.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `/Users/garinat_t/Desktop/Workplace/core/test_checkpoint_session.py` :

```python
"""Point de contrôle avant éviction d'une session (relai propre entre appareils).

$ cd core && python3 -m pytest test_checkpoint_session.py -v
"""
import logging

import checkpoint_session  # noqa: E402


def test_declencher_checkpoint_ne_leve_jamais(caplog):
    with caplog.at_level(logging.INFO):
        checkpoint_session.declencher_checkpoint("marina")
    assert "marina" in caplog.text
```

- [ ] **Step 2: Vérifier que le test échoue**

Run: `cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest test_checkpoint_session.py -v`
Expected: `ModuleNotFoundError: No module named 'checkpoint_session'`

- [ ] **Step 3: Créer `core/checkpoint_session.py`**

```python
"""Point de contrôle avant éviction d'une session — relai propre entre appareils.

Stub aujourd'hui : journalise seulement. Point d'extension volontairement isolé du reste
du chantier de session (`session_registre.py`, `core/auth.py`) pour que ce dernier reste
testable sans dépendre du chantier de sauvegarde continue.

Quand `docs/superpowers/plans/2026-08-04-sauvegarde-continue-rpo.md` sera livré, ce module
sera le seul à modifier pour déclencher un vrai cliché de réplication immédiat (appel HTTP
vers un futur point de contrôle Litestream, ou `wal-g wal-push` forcé) au lieu d'attendre le
cycle normal de réplication (quelques secondes) — aucun appelant de ce module n'aura à
changer.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def declencher_checkpoint(sub: str) -> None:
    """Point de contrôle avant de considérer une ancienne session comme close.

    Stub : journalise l'intention. Ne lève jamais — un échec de checkpoint ne doit pas
    empêcher le relai vers le nouvel appareil (la réplication continue, une fois branchée,
    tournera de toute façon dans les quelques secondes suivantes ; ce point de contrôle
    n'est qu'une garantie SUPPLÉMENTAIRE, pas la seule ligne de défense)."""
    logger.info("Relai de session pour %s : point de contrôle déclenché", sub)
```

- [ ] **Step 4: Vérifier que le test passe**

Run: `cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest test_checkpoint_session.py -v`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/garinat_t/Desktop/Workplace
git add core/checkpoint_session.py core/test_checkpoint_session.py
git commit -m "feat(core): point de contrôle avant éviction de session (stub extensible)"
```

---

### Task 3: Enregistrement/éviction au login (`auth_callback`)

**Files:**
- Modify: `core/routers/auth.py`
- Modify: `core/test_auth_routes.py`

**Interfaces:**
- Consumes: `session_registre.nouvelle_session` (Task 1), `checkpoint_session.declencher_checkpoint` (Task 2).
- Produces: le cookie de session posé par `auth_callback` porte désormais un champ `"generation": int`, consommé par Task 4.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à la fin de `/Users/garinat_t/Desktop/Workplace/core/test_auth_routes.py` :

```python
import checkpoint_session  # noqa: E402
import session_registre  # noqa: E402


def test_callback_pose_une_generation_dans_le_cookie(monkeypatch):
    r = client.get("/auth/login", follow_redirects=False)
    pending_cookie = r.cookies[auth.COOKIE_PENDING]
    pending = auth.dechiffrer_cookie(pending_cookie)

    async def _echanger_fake(code, code_verifier, redirect_uri):
        return {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 300}

    async def _verify_fake(token, kc):
        return {"sub": "generation-test", "nom": "Test", "avatarEmoji": "🧪"}

    monkeypatch.setattr(auth, "echanger_code", _echanger_fake)
    monkeypatch.setattr(auth, "verify_token", _verify_fake)

    r2 = client.get(
        "/auth/callback",
        params={"code": "code-abc", "state": pending["state"]},
        cookies={auth.COOKIE_PENDING: pending_cookie},
        follow_redirects=False,
    )
    session = auth.dechiffrer_cookie(r2.cookies[auth.COOKIE_SESSION])
    assert session["generation"] == 1


def test_deuxieme_callback_incremente_la_generation_et_declenche_le_checkpoint(monkeypatch):
    appels_checkpoint = []
    monkeypatch.setattr(checkpoint_session, "declencher_checkpoint", appels_checkpoint.append)

    async def _echanger_fake(code, code_verifier, redirect_uri):
        return {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 300}

    async def _verify_fake(token, kc):
        return {"sub": "generation-relai", "nom": "Test", "avatarEmoji": "🧪"}

    monkeypatch.setattr(auth, "echanger_code", _echanger_fake)
    monkeypatch.setattr(auth, "verify_token", _verify_fake)

    def _callback():
        r = client.get("/auth/login", follow_redirects=False)
        pending_cookie = r.cookies[auth.COOKIE_PENDING]
        pending = auth.dechiffrer_cookie(pending_cookie)
        r2 = client.get(
            "/auth/callback",
            params={"code": "code-abc", "state": pending["state"]},
            cookies={auth.COOKIE_PENDING: pending_cookie},
            follow_redirects=False,
        )
        return auth.dechiffrer_cookie(r2.cookies[auth.COOKIE_SESSION])

    premiere = _callback()
    assert premiere["generation"] == 1
    assert appels_checkpoint == []  # pas d'ancienne session au tout premier login

    deuxieme = _callback()
    assert deuxieme["generation"] == 2
    assert appels_checkpoint == ["generation-relai"]  # checkpoint déclenché pour CE sub
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest test_auth_routes.py -k generation -v`
Expected: `KeyError: 'generation'` (le cookie ne porte pas encore ce champ).

- [ ] **Step 3: Modifier `core/routers/auth.py`**

Ajouter les deux imports en haut du fichier, après `import auth` :

```python
import auth
import checkpoint_session
import session_registre
```

Remplacer le corps de `auth_callback` à partir de `session = {` par :

```python
    appareil = request.headers.get("user-agent", "inconnu")[:200]
    nouvelle_generation, ancienne = session_registre.nouvelle_session(sub, appareil)
    if ancienne is not None:
        # Une session existait déjà pour ce compte : on la considère comme évincée par
        # celle-ci. Le point de contrôle s'assure qu'aucune écriture en attente côté
        # ancien appareil n'est perdue avant que sa prochaine requête ne le déconnecte
        # (cf. core/auth.py::exiger_session, qui compare la génération à chaque appel).
        checkpoint_session.declencher_checkpoint(sub)

    session = {
        "sub": sub,
        "nom": payload.get("nom"),
        "avatarEmoji": payload.get("avatarEmoji"),
        "refresh_token": refresh_token,
        "generation": nouvelle_generation,
    }
```

(Le reste de la fonction — construction de `resp`, `set_cookie`, `delete_cookie` — ne change pas.)

- [ ] **Step 4: Vérifier que les tests passent**

Run: `cd /Users/garinat_t/Desktop/Workplace/core && SESSION_REGISTRE_DB=/tmp/test_session_registre_$$.db python3 -m pytest test_auth_routes.py -v`
Expected: tous les tests passent, y compris les 2 nouveaux.

- [ ] **Step 5: Commit**

```bash
cd /Users/garinat_t/Desktop/Workplace
git add core/routers/auth.py core/test_auth_routes.py
git commit -m "feat(core): enregistrement/éviction de session au login, avec checkpoint"
```

---

### Task 4: Vérification de génération à chaque requête (`exiger_session`)

**Files:**
- Modify: `core/auth.py`
- Modify: `core/test_auth.py`

**Interfaces:**
- Consumes: `session_registre.generation_actuelle` (Task 1).
- Produces: `exiger_session` redirige vers `/auth/login?next=%2Fdashboard%3Fmotif%3Dreprise_ailleurs` quand la génération du cookie est dépassée — consommé par Task 5 (bandeau dashboard).

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à la fin de `/Users/garinat_t/Desktop/Workplace/core/test_auth.py` :

```python
import session_registre  # noqa: E402


def test_exiger_session_generation_perimee_redirige_avec_motif():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    auth.httpx.AsyncClient = _FakeClient
    auth._cache_access_token.clear()

    async def _verify_fake(token, kc):
        return {"sub": "marina-perimee", "nom": "Marina", "avatarEmoji": "🌙"}

    ancien_verify = auth.verify_token
    auth.verify_token = _verify_fake
    try:
        # Le registre est déjà à la génération 2 (un autre appareil s'est reconnecté),
        # mais le cookie testé ici porte encore la génération 1.
        session_registre.nouvelle_session("marina-perimee", "iPhone")
        session_registre.nouvelle_session("marina-perimee", "MacBook")
        cookie = auth.chiffrer_cookie({
            "sub": "marina-perimee", "refresh_token": "rt-123", "generation": 1,
        })
        try:
            _run(auth.exiger_session(_fake_request({auth.COOKIE_SESSION: cookie})))
            assert False, "devait lever HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 303
            assert exc.headers["Location"] == "/auth/login?next=%2Fdashboard%3Fmotif%3Dreprise_ailleurs"
    finally:
        auth.AUTH_ENABLED = ancien
        auth.verify_token = ancien_verify
        auth._cache_access_token.clear()


def test_exiger_session_generation_a_jour_ne_redirige_pas():
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    auth.httpx.AsyncClient = _FakeClient
    auth._cache_access_token.clear()

    async def _verify_fake(token, kc):
        return {"sub": "marina-a-jour", "nom": "Marina", "avatarEmoji": "🌙"}

    ancien_verify = auth.verify_token
    auth.verify_token = _verify_fake
    try:
        generation, _ = session_registre.nouvelle_session("marina-a-jour", "iPhone")
        cookie = auth.chiffrer_cookie({
            "sub": "marina-a-jour", "refresh_token": "rt-123", "generation": generation,
        })
        r = _run(auth.exiger_session(_fake_request({auth.COOKIE_SESSION: cookie})))
        assert r["sub"] == "marina-a-jour"
    finally:
        auth.AUTH_ENABLED = ancien
        auth.verify_token = ancien_verify
        auth._cache_access_token.clear()


def test_exiger_session_cookie_sans_registre_reste_valide():
    """Cookie émis avant ce chantier (pas de champ `generation`, pas d'entrée au
    registre) : comportement historique préservé, pas de redirection surprise."""
    ancien = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    auth.httpx.AsyncClient = _FakeClient
    auth._cache_access_token.clear()

    async def _verify_fake(token, kc):
        return {"sub": "jamais-au-registre", "nom": "X", "avatarEmoji": None}

    ancien_verify = auth.verify_token
    auth.verify_token = _verify_fake
    try:
        cookie = auth.chiffrer_cookie({"sub": "jamais-au-registre", "refresh_token": "rt-1"})
        r = _run(auth.exiger_session(_fake_request({auth.COOKIE_SESSION: cookie})))
        assert r["sub"] == "jamais-au-registre"
    finally:
        auth.AUTH_ENABLED = ancien
        auth.verify_token = ancien_verify
        auth._cache_access_token.clear()
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run: `cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest test_auth.py -k generation -v`
Expected: `test_exiger_session_generation_perimee_redirige_avec_motif` échoue (aucune
redirection déclenchée aujourd'hui — la fonction accepte le cookie tel quel).

- [ ] **Step 3: Modifier `core/auth.py`**

Ajouter `import urllib.parse` en haut du fichier (après `import time`) :

```python
import time
import urllib.parse
```

Ajouter `import session_registre` après les imports existants du module (après `from shared.workplace_auth import ...`).

Dans `exiger_session`, juste après le bloc :

```python
    if not sub or not refresh_token:
        raise HTTPException(status_code=303, headers={"Location": "/auth/login"})
```

insérer :

```python
    generation_registre = session_registre.generation_actuelle(sub)
    if generation_registre is not None and session.get("generation") != generation_registre:
        # Une connexion plus récente a évincé celle-ci (relai propre entre appareils,
        # cf. core/routers/auth.py::auth_callback). `generation_registre is None` = pas
        # encore de registre pour ce compte (cookie antérieur à ce chantier) : on laisse
        # passer, comportement historique préservé.
        destination = urllib.parse.quote("/dashboard?motif=reprise_ailleurs")
        raise HTTPException(status_code=303, headers={"Location": f"/auth/login?next={destination}"})
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest test_auth.py -v`
Expected: tous les tests passent, y compris les 3 nouveaux.

- [ ] **Step 5: Lancer toute la suite auth pour vérifier l'absence de régression**

Run: `cd /Users/garinat_t/Desktop/Workplace/core && python3 -m pytest test_auth.py test_auth_routes.py test_session_registre.py test_checkpoint_session.py -v`
Expected: tous les tests passent (aucune régression sur les tests existants de Task 3/S171).

- [ ] **Step 6: Commit**

```bash
cd /Users/garinat_t/Desktop/Workplace
git add core/auth.py core/test_auth.py
git commit -m "feat(core): exiger_session révoque une session évincée par une reconnexion"
```

---

### Task 5: Bandeau d'information côté dashboard

**Files:**
- Modify: `core/dashboard.html`

**Interfaces:**
- Consumes: le paramètre `?motif=reprise_ailleurs` produit par la redirection de Task 4.
- Produces: un message visible à l'utilisateur évincé, au lieu d'un échec silencieux.

- [ ] **Step 1: Ajouter le script au tout début du bloc `<script>` existant**

Dans `/Users/garinat_t/Desktop/Workplace/core/dashboard.html`, juste après la ligne
`<script>` (ligne 1024), ajouter :

```javascript
// Relai de session entre appareils (cf. docs/superpowers/plans/2026-08-04-relai-session-appareils.md) :
// une redirection avec ?motif=reprise_ailleurs signifie que ce compte vient d'être
// utilisé sur un autre appareil et que CETTE session a été évincée puis reconnectée.
(function () {
  const params = new URLSearchParams(window.location.search);
  if (params.get('motif') === 'reprise_ailleurs') {
    const bandeau = document.createElement('div');
    bandeau.textContent = "Vous avez été reconnecté(e) : ce compte vient d'être utilisé sur un autre appareil.";
    bandeau.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9999;'
      + 'background:#7a4b00;color:#fff;padding:10px 16px;text-align:center;'
      + 'font:14px -apple-system,sans-serif;';
    document.body.prepend(bandeau);
    setTimeout(() => bandeau.remove(), 8000);
    params.delete('motif');
    const reste = params.toString();
    history.replaceState(null, '', window.location.pathname + (reste ? '?' + reste : ''));
  }
})();
```

- [ ] **Step 2: Vérifier manuellement**

Run: `cd /Users/garinat_t/Desktop/Workplace/core && python3 -c "
import re
html = open('dashboard.html').read()
assert 'motif=reprise_ailleurs' in html.split('reste_faux', 1)[0] or 'reprise_ailleurs' in html
print('OK : bandeau présent dans dashboard.html')
"`
Expected: `OK : bandeau présent dans dashboard.html`

Test visuel réel (une fois le Cœur relancé avec `AUTH_ENABLED=true` et Keycloak
disponible) : ouvrir `http://localhost:5100/dashboard?motif=reprise_ailleurs` dans un
navigateur et constater le bandeau orange en haut de page, qui disparaît après 8 secondes
et retire le paramètre de l'URL sans recharger la page.

- [ ] **Step 3: Commit**

```bash
cd /Users/garinat_t/Desktop/Workplace
git add core/dashboard.html
git commit -m "feat(core): bandeau dashboard quand une session est reprise ailleurs"
```

---

### Task 6: Variable d'environnement du registre + démarrage réel

**Files:**
- Modify: `core/docker-compose.yml`
- Modify: `.env.example`

**Interfaces:**
- Consumes: rien.
- Produces: le registre persiste dans le volume `core_data` déjà monté, survit aux redémarrages du conteneur.

- [ ] **Step 1: Ajouter la variable dans `core/docker-compose.yml`**

À côté de la ligne existante `- LIVRAISONS_DB=/data/livraisons.db`, ajouter :

```yaml
      - SESSION_REGISTRE_DB=/data/session_registre.db
```

- [ ] **Step 2: Documenter dans `.env.example`**

Ajouter, à côté des variables `AUTH_*` existantes :

```bash
# Registre de session (relai propre entre appareils, cf.
# docs/superpowers/plans/2026-08-04-relai-session-appareils.md). Défaut = /data/session_registre.db
# (dans le volume core_data déjà monté) — à ne changer que si /data change de sens.
#SESSION_REGISTRE_DB=/data/session_registre.db
```

- [ ] **Step 3: Reconstruire et vérifier le démarrage**

Run: `cd /Users/garinat_t/Desktop/Workplace/core && docker compose up -d --build`
Expected: le conteneur `core-core-1` (ou nom réel, `docker ps --filter name=core`) reste
`healthy`.

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5100/health`
Expected: `200`

- [ ] **Step 4: Commit**

```bash
cd /Users/garinat_t/Desktop/Workplace
git add core/docker-compose.yml .env.example
git commit -m "chore(core): variable SESSION_REGISTRE_DB pour le registre de session"
```

---

## Limites connues de ce plan (documentées, pas résolues ici)

- **Pas de notification instantanée (push)** : la session évincée n'apprend la nouvelle
  qu'à sa PROCHAINE requête protégée, pas à l'instant exact de l'éviction. En pratique,
  très rapide (le dashboard fait des appels API en continu), mais ce n'est pas un vrai
  WebSocket temps réel. Construire un canal live persistant serait un chantier à part,
  plus lourd, non justifié par le besoin exprimé (bascule séquentielle d'appareils, pas
  simultanéité réelle).
- **`checkpoint_session.declencher_checkpoint` reste un stub journalisant** tant que le
  plan de sauvegarde continue (`2026-08-04-sauvegarde-continue-rpo.md`) n'est pas livré.
  Une fois qu'il l'est, un plan de suivi devra remplacer le corps de cette fonction par un
  vrai déclenchement de synchronisation immédiate — sans toucher à `auth_callback` ni aux
  tests de ce plan, qui ne dépendent que de la signature.
- **Split-brain de réplication** : si une réplique Patroni est un jour ajoutée à `memoire`
  ou `gateway` pour de la haute disponibilité, il faudra vérifier/activer le
  fencing/watchdog Patroni à ce moment-là (cf. conversation utilisateur) — non traité ici,
  ce plan ne fait que du registre applicatif, aucune réplique à chaud n'existe encore sur
  ces deux briques.
