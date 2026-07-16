# S178 — PWA + push web + widgets + digest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre l'application web agenda `/app` installable en PWA, lui donner un canal de notification push web (nouvel adaptateur `webpush` dans la brique `connexion`, réutilisé automatiquement par les rappels S174 et les listes S176), et ajouter un digest quotidien/hebdo opt-in (push court + email riche).

**Architecture :** Le push web est un **adaptateur de plus** dans `connexion` : chaque appareil est enregistré comme une cible de correspondance `(reseau="webpush", id_externe=endpoint)`, donc `POST /pousser` (déjà appelé par S174/S176) le fanout sans changer leur code. La brique agenda relaie l'enregistrement d'appareil (Bearer Keycloak → connexion clé API), sert le service worker + le manifest, et porte le digest (composition dans `services/digest.py`, déclenché par `core/proactif.py`). L'email riche passe par un envoi direct HTML ajouté à la brique mail 6030.

**Tech Stack :** Python 3.11, FastAPI, SQLAlchemy async + Alembic (agenda) ; `pywebpush` + VAPID (connexion) ; stockage JSON (connexion) ; JS vanilla + Service Worker API + Web Push API (front `/app`, aucun CDN).

## Global Constraints

- **Anti-intrusif (non négociable)** : aucune demande de permission à l'ouverture de `/app` — seulement sur clic explicite ; coupure en un clic par appareil (retrait serveur + `unsubscribe()`) ; interrupteur global ; digest `off` par défaut ; heures calmes respectées ; purge auto d'un appareil mort (HTTP 410/404).
- **Vocabulaire** : on parle d'« **appareil** » (device push), **jamais** d'« abonnement » (confusion paiement). Seul opt-in nommé = le **digest**.
- **Aucun CDN / ressource externe** dans le front (règle projet, cf. `static/barcode.js`). Icônes PNG générées localement.
- **Repli honnête partout** : brique/clé absente ⇒ no-op silencieux, jamais d'erreur qui casse un flux (motif `services/notifications.py` S176 et `_pousser_messagerie` S174).
- **Français** dans le code, les commentaires, les messages utilisateur (convention Workplace).
- **TDD strict** : test qui échoue → implémentation minimale → test vert → commit. Suites de référence à garder vertes : agenda ~261, cœur 439.
- **Migrations** : nouvelle révision Alembic `0010` (agenda), `down_revision = "0009"`. Les tests utilisent `create_all` (pas la migration) ; smoke `alembic upgrade/downgrade` sur Postgres = RESTE avant déploiement (noté, pas dans le plan).
- **Env nouveaux** : connexion `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`/`VAPID_SUBJECT` ; agenda `VAPID_PUBLIC_KEY`/`DIGEST_KEY`/`DIGEST_HEURE` (défaut 7)/`DIGEST_TZ` (défaut `Europe/Paris`). Générés au déploiement — repli désactivé si absents.

---

## Fichiers touchés (structure)

**Brique connexion :**
- Create `briques/connexion/appareils.py` — magasin JSON des appareils push web (endpoint → clés + user), résolution pour l'adaptateur, purge.
- Modify `briques/connexion/adaptateurs.py` — classe `WebPush`, enregistrement dans `REGISTRE` + `_ORDRE_DEFAUT`.
- Modify `briques/connexion/main.py` — endpoints `/push/appareils` (POST/DELETE, clé API) + `/push/cle_publique` (public) ; modèles Pydantic.
- Modify `briques/connexion/requirements.txt` — `pywebpush`.
- Create `briques/connexion/test_appareils.py`, `briques/connexion/test_webpush.py`.

**Brique agenda :**
- Modify `briques/agenda/backend/config.py` — `VAPID_PUBLIC_KEY`, `DIGEST_KEY`, `DIGEST_HEURE`, `DIGEST_TZ`.
- Create `briques/agenda/backend/routers/push.py` — `/push/appareils` (POST/DELETE, Bearer) + `/push/cle_publique`.
- Create `briques/agenda/backend/routers/digests.py` — `POST /digests/executer` (clé interne).
- Modify `briques/agenda/backend/routers/profiles.py` — `PATCH /profiles/me/notifs` (préférences) + semis `email`.
- Create `briques/agenda/backend/services/digest.py` — composition pure du digest.
- Create `briques/agenda/backend/services/heures_calmes.py` — helper pur « maintenant dans la plage ? ».
- Modify `briques/agenda/backend/services/profils.py` — `upsert` accepte `email` ; helpers d'accès prefs.
- Modify `briques/agenda/backend/services/notifications.py` — respect des heures calmes avant push.
- Modify `briques/agenda/backend/models/orm.py` — champs `UserProfile`.
- Create `briques/agenda/backend/alembic/versions/0010_pwa_push_digest.py`.
- Modify `briques/agenda/backend/models/schemas.py` — schémas prefs notif.
- Modify `briques/agenda/backend/main.py` — monte les routers `push` + `digests`.
- Modify `briques/agenda/backend/templates_app.py` — `<link rel=manifest>`, enregistrement SW, panneau 🔔.
- Create `briques/agenda/backend/routers/pwa.py` — `/app/manifest.webmanifest` + `/app/sw.js`.
- Create `briques/agenda/backend/static/sw.js` — service worker (push + notificationclick + cache shell).
- Create `briques/agenda/backend/services/icones.py` — génération PNG locale (192/512/maskable).
- Create tests : `tests/test_push_appareils.py`, `tests/test_digest_service.py`, `tests/test_heures_calmes.py`, `tests/test_digests_executer.py`, `tests/test_pwa_assets.py`, `tests/test_profil_email_prefs.py`.

**Brique mail 6030 :**
- Modify `briques/mail/envoi.py` — `envoyer(..., corps_html: str | None = None)` (alternative HTML).
- Modify `briques/mail/main.py` — `POST /mail/envoyer` (envoi direct), schéma `EnvoiDirectEntree`.
- Modify `briques/mail/test_envoi.py` (ou create `test_envoi_direct.py`).

**Cœur :**
- Modify `core/proactif.py` — `_check_digest` ajouté à `CHECKS`.
- Modify `core/conftest.py` / tests proactif — `tests` (chemin réel à repérer) pour `_check_digest`.

**Docs :**
- Modify `briques/agenda/backend/README.md`, `briques/connexion/README.md`.
- Modify `docs/sprints/S174-S180-roadmap-agenda-best-in-class.md`.

---

# Phase A — Push web côté `connexion`

### Task A1 : Magasin d'appareils push web (`appareils.py`)

**Files:**
- Create: `briques/connexion/appareils.py`
- Test: `briques/connexion/test_appareils.py`

**Interfaces:**
- Consumes : `stockage.lire_json`/`ecrire_json` (`briques/connexion/stockage.py`).
- Produces :
  - `enregistrer(utilisateur: str, appareil: dict) -> dict` — `appareil` = `{"endpoint": str, "keys": {"p256dh": str, "auth": str}, "ua": str|None}` ; renvoie l'appareil stocké (clé = endpoint) ; upsert idempotent.
  - `retirer(endpoint: str) -> bool`.
  - `par_endpoint(endpoint: str) -> dict | None` — renvoie `{utilisateur, endpoint, keys, ua}` ou None.
  - `endpoints_de(utilisateur: str) -> list[str]`.

- [ ] **Step 1 : Test qui échoue**

```python
# briques/connexion/test_appareils.py
import os, tempfile, importlib


def _mod(tmp):
    os.environ["CONNEXION_DIR"] = tmp
    import appareils, stockage
    importlib.reload(stockage); importlib.reload(appareils)
    return appareils


def test_enregistrer_puis_resoudre(tmp_path):
    ap = _mod(str(tmp_path))
    appareil = {"endpoint": "https://push.example/AAA", "keys": {"p256dh": "k1", "auth": "k2"}, "ua": "Firefox"}
    ap.enregistrer("marina", appareil)
    trouve = ap.par_endpoint("https://push.example/AAA")
    assert trouve["utilisateur"] == "marina"
    assert trouve["keys"]["auth"] == "k2"
    assert ap.endpoints_de("marina") == ["https://push.example/AAA"]


def test_enregistrer_idempotent_et_retirer(tmp_path):
    ap = _mod(str(tmp_path))
    appareil = {"endpoint": "https://push.example/BBB", "keys": {"p256dh": "x", "auth": "y"}}
    ap.enregistrer("marina", appareil)
    ap.enregistrer("marina", appareil)  # 2e fois = pas de doublon
    assert ap.endpoints_de("marina") == ["https://push.example/BBB"]
    assert ap.retirer("https://push.example/BBB") is True
    assert ap.par_endpoint("https://push.example/BBB") is None
    assert ap.retirer("inconnu") is False
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `cd briques/connexion && python -m pytest test_appareils.py -v`
Expected: FAIL (`ModuleNotFoundError: appareils`).

- [ ] **Step 3 : Implémentation minimale**

```python
# briques/connexion/appareils.py
"""Magasin des appareils push web (S178) : endpoint → {utilisateur, clés, ua}.

Un « appareil » est une cible Web Push (l'objet PushSubscription du navigateur :
endpoint + clés p256dh/auth). PAS un abonnement payant. Stocké en JSON simple comme
le reste de la brique (`stockage`). L'adaptateur `webpush` y résout les clés à l'envoi ;
la table de correspondance, elle, ne retient que le routage (reseau=webpush, id=endpoint)."""
from __future__ import annotations

import stockage

FICHIER = "appareils_webpush.json"


def _table() -> dict:
    t = stockage.lire_json(FICHIER, {})
    return t if isinstance(t, dict) else {}


def _sauver(t: dict) -> None:
    stockage.ecrire_json(FICHIER, t)


def enregistrer(utilisateur: str, appareil: dict) -> dict:
    """Upsert d'un appareil (clé = endpoint). Idempotent."""
    endpoint = appareil["endpoint"]
    t = _table()
    t[endpoint] = {
        "utilisateur": utilisateur,
        "endpoint": endpoint,
        "keys": appareil.get("keys") or {},
        "ua": appareil.get("ua"),
    }
    _sauver(t)
    return t[endpoint]


def retirer(endpoint: str) -> bool:
    t = _table()
    if endpoint in t:
        del t[endpoint]
        _sauver(t)
        return True
    return False


def par_endpoint(endpoint: str) -> dict | None:
    return _table().get(endpoint)


def endpoints_de(utilisateur: str) -> list[str]:
    return [e for e, v in _table().items() if v.get("utilisateur") == utilisateur]
```

- [ ] **Step 4 : Lancer, vérifier le vert**

Run: `cd briques/connexion && python -m pytest test_appareils.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5 : Commit**

```bash
git add briques/connexion/appareils.py briques/connexion/test_appareils.py
git commit -m "feat(s178): magasin d'appareils push web (connexion)"
```

---

### Task A2 : Adaptateur `WebPush` (pywebpush + VAPID) + enregistrement

**Files:**
- Modify: `briques/connexion/adaptateurs.py` (classe `WebPush` avant le `# ── Registre ──`, ~ligne 295 ; ajout au `REGISTRE` et `_ORDRE_DEFAUT`)
- Modify: `briques/connexion/requirements.txt` (ajouter `pywebpush`)
- Test: `briques/connexion/test_webpush.py`

**Interfaces:**
- Consumes : `appareils.par_endpoint`, `appareils.retirer` (Task A1).
- Produces : `WebPush().nom == "webpush"` ; `configure()` vrai si `VAPID_PRIVATE_KEY` + `VAPID_SUBJECT` présents ; `await envoyer(endpoint, texte) -> bool` ; enregistré dans `REGISTRE["webpush"]`.

**Notes :** `texte` du contrat `Adaptateur.envoyer` est le corps ; on encode un payload JSON `{"titre": ..., "corps": ...}` en découpant sur le 1er `\n` (les appelants poussent `"🔔 titre\ncorps"`, cf. `_pousser_messagerie`). Sur `WebPushException` avec `response.status_code` 404/410 → `appareils.retirer(endpoint)` et renvoyer `False`.

- [ ] **Step 1 : Test qui échoue**

```python
# briques/connexion/test_webpush.py
import os, importlib
from unittest.mock import patch, MagicMock


def _setup(tmp_path):
    os.environ["CONNEXION_DIR"] = str(tmp_path)
    os.environ["VAPID_PRIVATE_KEY"] = "cle-privee-factice"
    os.environ["VAPID_SUBJECT"] = "mailto:admin@example.org"
    import stockage, appareils, adaptateurs
    importlib.reload(stockage); importlib.reload(appareils); importlib.reload(adaptateurs)
    return appareils, adaptateurs


def test_configure_selon_env(tmp_path):
    _, ad = _setup(tmp_path)
    assert ad.obtenir("webpush").configure() is True
    del os.environ["VAPID_PRIVATE_KEY"]
    importlib.reload(ad)
    assert ad.obtenir("webpush").configure() is False


def test_envoyer_appelle_pywebpush(tmp_path):
    ap, ad = _setup(tmp_path)
    ap.enregistrer("marina", {"endpoint": "https://push/AAA", "keys": {"p256dh": "p", "auth": "a"}})
    with patch("adaptateurs.webpush") as wp:
        ok = __import__("asyncio").get_event_loop().run_until_complete(
            ad.obtenir("webpush").envoyer("https://push/AAA", "🔔 Titre\nCorps"))
    assert ok is True
    assert wp.called
    payload = wp.call_args.kwargs.get("data") or wp.call_args.args[1]
    assert "Titre" in payload and "Corps" in payload


def test_envoyer_410_purge_appareil(tmp_path):
    ap, ad = _setup(tmp_path)
    ap.enregistrer("marina", {"endpoint": "https://push/GONE", "keys": {"p256dh": "p", "auth": "a"}})
    from pywebpush import WebPushException
    resp = MagicMock(); resp.status_code = 410
    exc = WebPushException("gone"); exc.response = resp
    with patch("adaptateurs.webpush", side_effect=exc):
        ok = __import__("asyncio").get_event_loop().run_until_complete(
            ad.obtenir("webpush").envoyer("https://push/GONE", "🔔 x\ny"))
    assert ok is False
    assert ap.par_endpoint("https://push/GONE") is None
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd briques/connexion && python -m pytest test_webpush.py -v`
Expected: FAIL (`webpush` absent d'`adaptateurs`, pas de réseau `webpush`).

- [ ] **Step 3 : Implémentation**

Ajouter à `briques/connexion/requirements.txt` : `pywebpush`.

Dans `briques/connexion/adaptateurs.py`, en tête ajouter l'import (protégé pour ne pas casser si non installé en test unitaire d'autres modules) :

```python
import json
try:
    from pywebpush import webpush, WebPushException
except Exception:  # noqa: BLE001 — dépendance optionnelle, repli honnête
    webpush = None
    class WebPushException(Exception):  # type: ignore
        pass

import appareils
```

Classe `WebPush` (juste avant `# ── Registre ──`) :

```python
# ── Web Push (S178) ─────────────────────────────────────────────────────────────
class WebPush(Adaptateur):
    """Notifications push web (navigateur / PWA). `id_externe` = endpoint de l'appareil ;
    les clés sont résolues dans le magasin `appareils`. VAPID = identité du serveur push."""
    nom = "webpush"

    def _cle_privee(self):
        return os.getenv("VAPID_PRIVATE_KEY") or None

    def configure(self) -> bool:
        return bool(webpush and self._cle_privee() and os.getenv("VAPID_SUBJECT"))

    async def envoyer(self, id_externe: str, texte: str) -> bool:
        app = appareils.par_endpoint(id_externe)
        if not app or webpush is None:
            return False
        titre, _, corps = texte.partition("\n")
        payload = json.dumps({"titre": titre.strip(), "corps": corps.strip(),
                              "url": "/app", "tag": "workplace"})
        info = {"endpoint": app["endpoint"], "keys": app.get("keys") or {}}
        try:
            webpush(subscription_info=info, data=payload,
                    vapid_private_key=self._cle_privee(),
                    vapid_claims={"sub": os.getenv("VAPID_SUBJECT")})
            return True
        except WebPushException as ex:  # noqa: BLE001
            code = getattr(getattr(ex, "response", None), "status_code", None)
            if code in (404, 410):
                appareils.retirer(id_externe)   # appareil mort → purge
            return False
        except Exception:  # noqa: BLE001 — best-effort
            return False
```

Enregistrement :

```python
REGISTRE: dict[str, Adaptateur] = {
    "telegram": Telegram(),
    "whatsapp": WhatsApp(),
    "discord": Discord(),
    "email_sms": EmailSms(),
    "webpush": WebPush(),
}

_ORDRE_DEFAUT = ["telegram", "whatsapp", "discord", "email_sms", "webpush"]
```

- [ ] **Step 4 : Vérifier le vert**

Run: `cd briques/connexion && python -m pytest test_webpush.py -v`
Expected: PASS (3 tests). Si `pywebpush` non installé localement : `pip install pywebpush` d'abord.

- [ ] **Step 5 : Commit**

```bash
git add briques/connexion/adaptateurs.py briques/connexion/requirements.txt briques/connexion/test_webpush.py
git commit -m "feat(s178): adaptateur webpush (pywebpush+VAPID, purge 410)"
```

---

### Task A3 : Endpoints connexion `/push/appareils` + `/push/cle_publique`

**Files:**
- Modify: `briques/connexion/main.py` (modèles + 3 routes)
- Test: `briques/connexion/test_push_endpoints.py`

**Interfaces:**
- Consumes : `appareils.enregistrer/retirer` (A1), `correspondance.lier/delier` (`briques/connexion/correspondance.py`), `cle_api` (dépendance existante de `main.py`).
- Produces (contrat réseau) :
  - `POST /push/appareils` (clé API) `{"utilisateur": str, "appareil": {...}}` → `{"ok": true}` ; enregistre l'appareil **et** `correspondance.lier("webpush", endpoint, utilisateur)`.
  - `DELETE /push/appareils` (clé API) `{"endpoint": str}` → `{"ok": bool}` ; `appareils.retirer` + `correspondance.delier("webpush", endpoint)`.
  - `GET /push/cle_publique` (public) → `{"cle": os.getenv("VAPID_PUBLIC_KEY", "")}`.

- [ ] **Step 1 : Test qui échoue**

```python
# briques/connexion/test_push_endpoints.py
import os, importlib
from fastapi.testclient import TestClient


def _client(tmp_path):
    os.environ["CONNEXION_DIR"] = str(tmp_path)
    os.environ["CONNEXION_KEY"] = "secret"
    os.environ["VAPID_PUBLIC_KEY"] = "pub-abc"
    import stockage, appareils, correspondance, main
    for m in (stockage, appareils, correspondance, main):
        importlib.reload(m)
    return TestClient(main.app), correspondance


def test_cle_publique_est_publique(tmp_path):
    c, _ = _client(tmp_path)
    r = c.get("/push/cle_publique")
    assert r.status_code == 200 and r.json()["cle"] == "pub-abc"


def test_enregistrer_appareil_cree_correspondance(tmp_path):
    c, corr = _client(tmp_path)
    body = {"utilisateur": "marina",
            "appareil": {"endpoint": "https://push/AAA", "keys": {"p256dh": "p", "auth": "a"}}}
    r = c.post("/push/appareils", json=body, headers={"X-API-Key": "secret"})
    assert r.status_code == 200
    assert ("webpush", "https://push/AAA") in corr.cibles_pour("marina")


def test_enregistrer_exige_cle(tmp_path):
    c, _ = _client(tmp_path)
    r = c.post("/push/appareils", json={"utilisateur": "m", "appareil": {"endpoint": "x"}})
    assert r.status_code in (401, 403)


def test_retirer_appareil(tmp_path):
    c, corr = _client(tmp_path)
    body = {"utilisateur": "marina",
            "appareil": {"endpoint": "https://push/BBB", "keys": {"p256dh": "p", "auth": "a"}}}
    c.post("/push/appareils", json=body, headers={"X-API-Key": "secret"})
    r = c.request("DELETE", "/push/appareils", json={"endpoint": "https://push/BBB"},
                  headers={"X-API-Key": "secret"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert corr.cibles_pour("marina") == []
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd briques/connexion && python -m pytest test_push_endpoints.py -v`
Expected: FAIL (routes absentes → 404).

- [ ] **Step 3 : Implémentation**

Dans `briques/connexion/main.py`, importer `appareils`, ajouter les modèles Pydantic près des autres (`Pousser`, `Envoi`…) :

```python
class AppareilPush(BaseModel):
    endpoint: str
    keys: dict = {}
    ua: str | None = None

class EnregistrerAppareil(BaseModel):
    utilisateur: str
    appareil: AppareilPush

class RetirerAppareil(BaseModel):
    endpoint: str
```

Routes (après `/pousser`) :

```python
@app.get("/push/cle_publique", tags=["push"])
async def push_cle_publique():
    """Clé publique VAPID (publique par nature) : le navigateur en a besoin pour s'inscrire."""
    return {"cle": os.getenv("VAPID_PUBLIC_KEY", "")}


@app.post("/push/appareils", tags=["push"])
async def push_enregistrer(body: EnregistrerAppareil, _cle: str = Depends(cle_api)):
    """Enregistre un appareil push web d'un utilisateur (device, PAS abonnement payant).
    L'appareil devient une cible de correspondance → `/pousser` le fanout ensuite."""
    app_enr = appareils.enregistrer(body.utilisateur, body.appareil.model_dump())
    correspondance.lier("webpush", app_enr["endpoint"], body.utilisateur)
    return {"ok": True}


@app.delete("/push/appareils", tags=["push"])
async def push_retirer(body: RetirerAppareil, _cle: str = Depends(cle_api)):
    """Retire un appareil (coupure des notifs sur ce navigateur)."""
    ok = appareils.retirer(body.endpoint)
    correspondance.delier("webpush", body.endpoint)
    return {"ok": ok}
```

- [ ] **Step 4 : Vérifier le vert**

Run: `cd briques/connexion && python -m pytest test_push_endpoints.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5 : Commit**

```bash
git add briques/connexion/main.py briques/connexion/test_push_endpoints.py
git commit -m "feat(s178): endpoints connexion /push/appareils + /push/cle_publique"
```

---

# Phase B — Relais agenda + front PWA

### Task B1 : Config agenda + `/push/cle_publique` + relais `/push/appareils`

**Files:**
- Modify: `briques/agenda/backend/config.py`
- Create: `briques/agenda/backend/routers/push.py`
- Modify: `briques/agenda/backend/main.py` (monter le router)
- Test: `briques/agenda/backend/tests/test_push_appareils.py`

**Interfaces:**
- Consumes : `settings.VAPID_PUBLIC_KEY`, `settings.CONNEXION_URL`, `settings.CONNEXION_KEY`, `get_current_user` (`briques/agenda/backend/auth.py`).
- Produces (contrat réseau) :
  - `GET /push/cle_publique` → `{"cle": settings.VAPID_PUBLIC_KEY}` (pas d'auth requise — clé publique).
  - `POST /push/appareils` (Bearer) `{"appareil": {...}}` → relaie à connexion `POST /push/appareils` avec `{"utilisateur": user["sub"], "appareil": ...}` + `X-API-Key` ; renvoie `{"ok": true}`. **`utilisateur` vient TOUJOURS du token, jamais du corps.**
  - `DELETE /push/appareils` (Bearer) `{"endpoint": str}` → relaie le retrait.

**Note :** repli honnête — `CONNEXION_URL` vide ⇒ `{"ok": false, "raison": "push non configuré"}` (200, pas d'erreur).

- [ ] **Step 1 : Test qui échoue**

```python
# briques/agenda/backend/tests/test_push_appareils.py
import respx, httpx
from httpx import Response


def test_cle_publique(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "pub-xyz")
    r = client.get("/push/cle_publique")
    assert r.status_code == 200 and r.json()["cle"] == "pub-xyz"


@respx.mock
def test_enregistrer_force_le_sub(client_auth, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "CONNEXION_URL", "http://connexion")
    monkeypatch.setattr(settings, "CONNEXION_KEY", "k")
    route = respx.post("http://connexion/push/appareils").mock(return_value=Response(200, json={"ok": True}))
    r = client_auth.post("/push/appareils", json={"appareil": {"endpoint": "https://p/AAA", "keys": {}},
                                                  "utilisateur": "PIRATE"})
    assert r.status_code == 200
    envoye = route.calls.last.request
    import json as _j
    corps = _j.loads(envoye.content)
    assert corps["utilisateur"] != "PIRATE"        # forcé au sub du token
```

*(`client`, `client_auth` : fixtures existantes de `conftest.py` — repérer les noms réels ; `client_auth` fournit un token Keycloak simulé avec `sub`. Adapter les noms si nécessaire.)*

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd briques/agenda/backend && python -m pytest tests/test_push_appareils.py -v`
Expected: FAIL (router absent → 404).

- [ ] **Step 3 : Implémentation**

`config.py` — ajouter dans `Settings` :

```python
    # ── Push web + PWA (S178) ──────────────────────────────────────────────────
    # Clé PUBLIQUE VAPID (même valeur que connexion) — servie au navigateur pour
    # s'inscrire. La clé PRIVÉE ne vit QUE dans connexion. Vide ⇒ push désactivé.
    VAPID_PUBLIC_KEY: str = ""
    # Clé interne gardant POST /digests/executer (déclenché par l'horloge du Cœur).
    DIGEST_KEY: str = ""
    DIGEST_HEURE: int = 7          # heure locale d'envoi du digest
    DIGEST_TZ: str = "Europe/Paris"
```

`routers/push.py` :

```python
"""Push web (S178) : le front /app enregistre son appareil ici (Bearer), on relaie au
pont `connexion` (clé API) qui stocke la cible et l'ajoute à la correspondance. La clé
publique VAPID est servie telle quelle (publique par nature)."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import get_current_user
from config import settings

router = APIRouter(tags=["push"])


class AppareilEntree(BaseModel):
    appareil: dict


class RetraitEntree(BaseModel):
    endpoint: str


@router.get("/push/cle_publique")
async def cle_publique():
    return {"cle": settings.VAPID_PUBLIC_KEY}


def _entetes() -> dict:
    return {"X-API-Key": settings.CONNEXION_KEY} if settings.CONNEXION_KEY else {}


@router.post("/push/appareils")
async def enregistrer(body: AppareilEntree, user: dict = Depends(get_current_user)):
    if not settings.CONNEXION_URL:
        return {"ok": False, "raison": "push non configuré"}
    base = settings.CONNEXION_URL.rstrip("/")
    corps = {"utilisateur": user["sub"], "appareil": body.appareil}  # sub du token, pas du corps
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{base}/push/appareils", json=corps, headers=_entetes())
        return {"ok": True}
    except Exception:  # noqa: BLE001 — best-effort
        return {"ok": False, "raison": "pont injoignable"}


@router.delete("/push/appareils")
async def retirer(body: RetraitEntree, user: dict = Depends(get_current_user)):
    if not settings.CONNEXION_URL:
        return {"ok": False}
    base = settings.CONNEXION_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.request("DELETE", f"{base}/push/appareils",
                            json={"endpoint": body.endpoint}, headers=_entetes())
        return {"ok": True}
    except Exception:  # noqa: BLE001
        return {"ok": False}
```

`main.py` — monter le router (à côté des `include_router` existants) :

```python
from routers import push as push_router
app.include_router(push_router.router)
```

- [ ] **Step 4 : Vérifier le vert**

Run: `cd briques/agenda/backend && python -m pytest tests/test_push_appareils.py -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add briques/agenda/backend/config.py briques/agenda/backend/routers/push.py briques/agenda/backend/main.py briques/agenda/backend/tests/test_push_appareils.py
git commit -m "feat(s178): agenda relaie l'enregistrement d'appareil push (sub forcé)"
```

---

### Task B2 : Génération d'icônes PNG locale (`services/icones.py`)

**Files:**
- Create: `briques/agenda/backend/services/icones.py`
- Test: `briques/agenda/backend/tests/test_pwa_assets.py` (partie icônes)

**Interfaces:**
- Produces : `png_icone(taille: int, maskable: bool = False) -> bytes` — PNG carré valide (signature `\x89PNG`), glyphe 📅/A sur fond thème. Sans dépendance lourde : PNG minimal écrit à la main (un carré de couleur unie suffit pour un MVP installable ; pas de Pillow requis).

**Note YAGNI :** un carré de couleur unie (fond thème) fait une icône installable valide. On évite d'ajouter Pillow. Le glyphe est optionnel (fast-follow). On génère un PNG uni via `zlib` + chunks PNG.

- [ ] **Step 1 : Test qui échoue**

```python
# briques/agenda/backend/tests/test_pwa_assets.py
def test_png_icone_signature():
    from services.icones import png_icone
    data = png_icone(192)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 100
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd briques/agenda/backend && python -m pytest tests/test_pwa_assets.py::test_png_icone_signature -v`
Expected: FAIL (module absent).

- [ ] **Step 3 : Implémentation**

```python
# briques/agenda/backend/services/icones.py
"""Icônes PWA générées LOCALEMENT (aucun CDN, règle projet). MVP : carré uni au thème
sombre/or de l'app — suffisant pour une PWA installable. Glyphe = fast-follow."""
from __future__ import annotations

import struct
import zlib

FOND = (26, 22, 18)   # #1A1612, brun sombre du thème


def _chunk(typ: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + typ + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))


def png_icone(taille: int, maskable: bool = False) -> bytes:
    """PNG carré `taille`×`taille` de couleur unie (thème). `maskable` = même image
    (la safe-zone est respectée puisque le fond est plein)."""
    r, g, b = FOND
    ligne = b"\x00" + bytes([r, g, b]) * taille       # filtre 0 + pixels RGB
    brut = ligne * taille
    ihdr = struct.pack(">IIBBBBB", taille, taille, 8, 2, 0, 0, 0)  # 8 bits, RGB
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(brut, 9))
            + _chunk(b"IEND", b""))
```

- [ ] **Step 4 : Vérifier le vert**

Run: `cd briques/agenda/backend && python -m pytest tests/test_pwa_assets.py::test_png_icone_signature -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add briques/agenda/backend/services/icones.py briques/agenda/backend/tests/test_pwa_assets.py
git commit -m "feat(s178): génération locale des icônes PWA (PNG uni, sans Pillow)"
```

---

### Task B3 : Manifest + service worker + icônes servis (`routers/pwa.py`, `static/sw.js`)

**Files:**
- Create: `briques/agenda/backend/routers/pwa.py`
- Create: `briques/agenda/backend/static/sw.js`
- Modify: `briques/agenda/backend/main.py` (monter le router)
- Test: `briques/agenda/backend/tests/test_pwa_assets.py` (routes)

**Interfaces:**
- Consumes : `services.icones.png_icone` (B2).
- Produces (contrat réseau) :
  - `GET /app/manifest.webmanifest` → JSON manifest (`content-type: application/manifest+json`), avec `shortcuts` (widgets), `start_url:"/app"`, `scope:"/app"`, icônes 192/512/maskable.
  - `GET /app/sw.js` → JS du SW, en-tête `Service-Worker-Allowed: /` + `content-type: application/javascript`.
  - `GET /app/icone-{taille}.png` (taille ∈ {192,512}) et `GET /app/icone-maskable.png` → PNG.

- [ ] **Step 1 : Test qui échoue**

```python
# (dans tests/test_pwa_assets.py)
def test_manifest_servi(client):
    r = client.get("/app/manifest.webmanifest")
    assert r.status_code == 200
    m = r.json()
    assert m["start_url"] == "/app" and m["display"] == "standalone"
    assert any(i["sizes"] == "512x512" for i in m["icons"])
    assert any(s["url"].startswith("/app") for s in m["shortcuts"])


def test_sw_servi_avec_scope(client):
    r = client.get("/app/sw.js")
    assert r.status_code == 200
    assert "application/javascript" in r.headers["content-type"]
    assert r.headers.get("service-worker-allowed") == "/"
    assert "addEventListener('push'" in r.text or 'addEventListener("push"' in r.text


def test_icone_png(client):
    r = client.get("/app/icone-192.png")
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd briques/agenda/backend && python -m pytest tests/test_pwa_assets.py -v`
Expected: FAIL (routes absentes).

- [ ] **Step 3 : Implémentation**

`static/sw.js` :

```javascript
// Service worker PWA agenda (S178). Anti-intrusif : ne montre une notif QUE sur push.
const CACHE = "agenda-shell-v1";
const SHELL = ["/app"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) =>
    Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("push", (e) => {
  let d = { titre: "Agenda", corps: "", url: "/app", tag: "workplace" };
  try { d = Object.assign(d, e.data.json()); } catch (_) { if (e.data) d.corps = e.data.text(); }
  e.waitUntil(self.registration.showNotification(d.titre, {
    body: d.corps, tag: d.tag, data: { url: d.url }, badge: "/app/icone-192.png", icon: "/app/icone-192.png",
  }));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/app";
  e.waitUntil(clients.matchAll({ type: "window" }).then((ws) => {
    for (const w of ws) { if (w.url.includes("/app") && "focus" in w) return w.focus(); }
    return clients.openWindow(url);
  }));
});
```

`routers/pwa.py` :

```python
"""Assets PWA de l'app agenda (S178) : manifest, service worker, icônes. Servis sous
/app/* pour rester dans le scope du SW."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from services.icones import png_icone

router = APIRouter(tags=["pwa"])

_SW = (Path(__file__).resolve().parent.parent / "static" / "sw.js")

MANIFEST = {
    "name": "Agenda", "short_name": "Agenda", "start_url": "/app", "scope": "/app",
    "display": "standalone", "background_color": "#1A1612", "theme_color": "#1A1612",
    "lang": "fr",
    "icons": [
        {"src": "/app/icone-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/app/icone-512.png", "sizes": "512x512", "type": "image/png"},
        {"src": "/app/icone-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
    "shortcuts": [
        {"name": "Nouvel événement", "url": "/app#nouvel-event"},
        {"name": "Listes", "url": "/app#listes"},
        {"name": "Sondages", "url": "/app#sondages"},
    ],
}


@router.get("/app/manifest.webmanifest", include_in_schema=False)
async def manifest():
    return Response(json.dumps(MANIFEST, ensure_ascii=False),
                    media_type="application/manifest+json")


@router.get("/app/sw.js", include_in_schema=False)
async def service_worker():
    return Response(_SW.read_text(encoding="utf-8"),
                    media_type="application/javascript",
                    headers={"Service-Worker-Allowed": "/"})


@router.get("/app/icone-{taille}.png", include_in_schema=False)
async def icone(taille: str):
    if taille == "maskable":
        return Response(png_icone(512, maskable=True), media_type="image/png")
    if taille not in ("192", "512"):
        raise HTTPException(404)
    return Response(png_icone(int(taille)), media_type="image/png")
```

`main.py` — monter :

```python
from routers import pwa as pwa_router
app.include_router(pwa_router.router)
```

- [ ] **Step 4 : Vérifier le vert**

Run: `cd briques/agenda/backend && python -m pytest tests/test_pwa_assets.py -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add briques/agenda/backend/routers/pwa.py briques/agenda/backend/static/sw.js briques/agenda/backend/main.py briques/agenda/backend/tests/test_pwa_assets.py
git commit -m "feat(s178): manifest + service worker + icônes PWA servis sous /app"
```

---

### Task B4 : Front `/app` — enregistrement SW + panneau 🔔 (activer/couper appareil)

**Files:**
- Modify: `briques/agenda/backend/templates_app.py` (dans `page_app` : `<link rel=manifest>` + `<meta theme-color>` dans le `<head>` ; bloc JS PWA + panneau 🔔)
- Test: `briques/agenda/backend/tests/test_pwa_assets.py` (présence dans le HTML)

**Interfaces:**
- Consumes : `GET /push/cle_publique`, `POST/DELETE /push/appareils` (B1), `GET /app/sw.js` + manifest (B3).
- Produces : la page `/app` référence le manifest, enregistre le SW, expose un bouton « Activer les notifications sur cet appareil » qui **ne demande la permission que sur clic**.

**Contenu JS à insérer** (helpers autonomes, aucun framework) :

```javascript
// ── PWA + push web (S178) — anti-intrusif : RIEN au chargement, tout sur clic ──
const b64ToUint8 = (s) => {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const b = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...b].map((c) => c.charCodeAt(0)));
};
let swReg = null;
async function initPWA() {
  if (!("serviceWorker" in navigator)) return;
  try { swReg = await navigator.serviceWorker.register("/app/sw.js", { scope: "/app" }); }
  catch (e) { console.warn("SW non enregistré", e); }
  majEtatPush();
}
async function majEtatPush() {
  const el = document.getElementById("etat-push");
  if (!el) return;
  if (!("Notification" in window) || !swReg) { el.textContent = "Non supporté sur ce navigateur."; return; }
  const sub = await swReg.pushManager.getSubscription();
  el.textContent = sub ? "🔔 Notifications activées sur cet appareil." : "🔕 Notifications coupées ici.";
  document.getElementById("btn-activer-push").style.display = sub ? "none" : "";
  document.getElementById("btn-couper-push").style.display = sub ? "" : "none";
}
async function activerPush() {
  if (Notification.permission === "denied") { alert("Autorise les notifications dans les réglages du navigateur."); return; }
  const perm = await Notification.requestPermission();      // ← demande UNIQUEMENT ici
  if (perm !== "granted") return;
  const { cle } = await (await fetch("/push/cle_publique")).json();
  if (!cle) { alert("Push non configuré côté serveur."); return; }
  const sub = await swReg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToUint8(cle) });
  await fetch("/push/appareils", { method: "POST", headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ appareil: sub.toJSON() }) });
  majEtatPush();
}
async function couperPush() {
  const sub = await swReg.pushManager.getSubscription();
  if (sub) {
    await fetch("/push/appareils", { method: "DELETE", headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ endpoint: sub.endpoint }) });
    await sub.unsubscribe();
  }
  majEtatPush();
}
```

*(`authHeaders(...)` : réutiliser le helper existant qui ajoute `Authorization: Bearer <token>` dans `templates_app.py` ; repérer son nom réel et l'employer. `initPWA()` est appelé à la fin de l'init de la page, après le login.)*

HTML du panneau (dans la zone réglages) :

```html
<section id="panneau-notifs" style="margin-top:16px">
  <h3>🔔 Notifications</h3>
  <p id="etat-push">…</p>
  <button id="btn-activer-push" onclick="activerPush()">Activer les notifications sur cet appareil</button>
  <button id="btn-couper-push" onclick="couperPush()" style="display:none">Couper sur cet appareil</button>
</section>
```

Dans le `<head>` de `page_app` :

```html
<link rel="manifest" href="/app/manifest.webmanifest">
<meta name="theme-color" content="#1A1612">
```

- [ ] **Step 1 : Test qui échoue**

```python
# (dans tests/test_pwa_assets.py)
def test_page_app_reference_pwa(client):
    html = client.get("/app").text
    assert 'rel="manifest"' in html and "/app/manifest.webmanifest" in html
    assert "serviceWorker.register" in html
    assert "Activer les notifications sur cet appareil" in html
    # anti-intrusif : la permission n'est demandée que dans activerPush, pas au chargement
    assert "requestPermission" in html
    assert "initPWA(" in html
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd briques/agenda/backend && python -m pytest tests/test_pwa_assets.py::test_page_app_reference_pwa -v`
Expected: FAIL.

- [ ] **Step 3 : Implémentation**

Éditer `templates_app.py` : insérer le `<link>`/`<meta>` dans le `<head>`, le `<section id="panneau-notifs">` dans la zone réglages, le bloc JS ci-dessus, et appeler `initPWA()` à la fin de la séquence d'initialisation post-login. Vérifier le nom réel du helper d'en-têtes auth et l'utiliser.

- [ ] **Step 4 : Vérifier le vert**

Run: `cd briques/agenda/backend && python -m pytest tests/test_pwa_assets.py -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add briques/agenda/backend/templates_app.py briques/agenda/backend/tests/test_pwa_assets.py
git commit -m "feat(s178): front /app — SW + panneau notifications (opt-in sur clic)"
```

---

# Phase C — Digest

### Task C1 : Migration 0010 + champs `UserProfile` + semis `email`

**Files:**
- Modify: `briques/agenda/backend/models/orm.py` (`UserProfile`)
- Create: `briques/agenda/backend/alembic/versions/0010_pwa_push_digest.py`
- Modify: `briques/agenda/backend/services/profils.py` (`upsert` accepte `email`)
- Modify: `briques/agenda/backend/routers/profiles.py` (semer `email` depuis les claims)
- Test: `briques/agenda/backend/tests/test_profil_email_prefs.py`

**Interfaces:**
- Produces : `UserProfile` gagne `email: str|None`, `digest_cadence: str` (`"off"`), `digest_push: bool` (True), `digest_email: bool` (False), `heures_calmes: str|None`, `dernier_digest_quotidien: str|None` (ISO date), `dernier_digest_hebdo: str|None`. `profils.upsert(db, user_id, display_name, avatar_color=None, email=None)`.

- [ ] **Step 1 : Test qui échoue**

```python
# briques/agenda/backend/tests/test_profil_email_prefs.py
import pytest
from services import profils


@pytest.mark.asyncio
async def test_upsert_seme_email_et_defauts(db_session):
    p = await profils.upsert(db_session, "marina", "Marina", email="marina@example.org")
    assert p.email == "marina@example.org"
    assert p.digest_cadence == "off"
    assert p.digest_push is True and p.digest_email is False
    assert p.heures_calmes is None
```

*(`db_session` : fixture async existante — repérer son nom réel dans `conftest.py`.)*

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd briques/agenda/backend && python -m pytest tests/test_profil_email_prefs.py -v`
Expected: FAIL (`AttributeError: email`).

- [ ] **Step 3 : Implémentation**

`models/orm.py` — dans `UserProfile`, après `avatar_color` :

```python
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    digest_cadence: Mapped[str] = mapped_column(String(10), nullable=False, default="off")
    digest_push: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    digest_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    heures_calmes: Mapped[str | None] = mapped_column(String(20), nullable=True)
    dernier_digest_quotidien: Mapped[str | None] = mapped_column(String(10), nullable=True)
    dernier_digest_hebdo: Mapped[str | None] = mapped_column(String(10), nullable=True)
```

*(importer `Boolean` depuis sqlalchemy si absent.)*

`services/profils.py` — `upsert` :

```python
async def upsert(db: AsyncSession, user_id: str, display_name: str,
                 avatar_color: str | None = None, email: str | None = None) -> UserProfile:
    prof = await db.get(UserProfile, user_id)
    couleur = avatar_color or couleur_pour(user_id)
    if prof is None:
        prof = UserProfile(user_id=user_id, display_name=display_name,
                           avatar_color=couleur, email=email)
        db.add(prof)
    else:
        prof.display_name = display_name
        if avatar_color:
            prof.avatar_color = avatar_color
        if email:
            prof.email = email
    await db.commit()
    await db.refresh(prof)
    return prof
```

`routers/profiles.py` — `upsert_me` sème l'email :

```python
    nom = user.get("name") or user.get("preferred_username") or user["sub"]
    return await profils.upsert(db, user["sub"], nom, email=user.get("email"))
```

`alembic/versions/0010_pwa_push_digest.py` :

```python
"""S178 : champs push/digest sur user_profiles.

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("email", sa.String(320), nullable=True))
    op.add_column("user_profiles", sa.Column("digest_cadence", sa.String(10), nullable=False, server_default="off"))
    op.add_column("user_profiles", sa.Column("digest_push", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("user_profiles", sa.Column("digest_email", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("user_profiles", sa.Column("heures_calmes", sa.String(20), nullable=True))
    op.add_column("user_profiles", sa.Column("dernier_digest_quotidien", sa.String(10), nullable=True))
    op.add_column("user_profiles", sa.Column("dernier_digest_hebdo", sa.String(10), nullable=True))


def downgrade() -> None:
    for col in ("dernier_digest_hebdo", "dernier_digest_quotidien", "heures_calmes",
                "digest_email", "digest_push", "digest_cadence", "email"):
        op.drop_column("user_profiles", col)
```

- [ ] **Step 4 : Vérifier le vert**

Run: `cd briques/agenda/backend && python -m pytest tests/test_profil_email_prefs.py -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add briques/agenda/backend/models/orm.py briques/agenda/backend/services/profils.py briques/agenda/backend/routers/profiles.py briques/agenda/backend/alembic/versions/0010_pwa_push_digest.py briques/agenda/backend/tests/test_profil_email_prefs.py
git commit -m "feat(s178): migration 0010 — champs push/digest + semis email"
```

---

### Task C2 : Helper heures calmes (`services/heures_calmes.py`)

**Files:**
- Create: `briques/agenda/backend/services/heures_calmes.py`
- Test: `briques/agenda/backend/tests/test_heures_calmes.py`

**Interfaces:**
- Produces : `dans_les_heures_calmes(plage: str | None, maintenant: datetime) -> bool` — `plage` = `"22:00-07:00"` (peut enjamber minuit) ; `None`/vide ⇒ `False`. `maintenant` = heure locale (naïve).

- [ ] **Step 1 : Test qui échoue**

```python
# briques/agenda/backend/tests/test_heures_calmes.py
from datetime import datetime
from services.heures_calmes import dans_les_heures_calmes


def test_none_jamais_calme():
    assert dans_les_heures_calmes(None, datetime(2026, 7, 16, 3, 0)) is False


def test_plage_enjambe_minuit():
    p = "22:00-07:00"
    assert dans_les_heures_calmes(p, datetime(2026, 7, 16, 23, 30)) is True
    assert dans_les_heures_calmes(p, datetime(2026, 7, 16, 3, 0)) is True
    assert dans_les_heures_calmes(p, datetime(2026, 7, 16, 12, 0)) is False


def test_plage_meme_jour():
    p = "09:00-17:00"
    assert dans_les_heures_calmes(p, datetime(2026, 7, 16, 12, 0)) is True
    assert dans_les_heures_calmes(p, datetime(2026, 7, 16, 20, 0)) is False
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd briques/agenda/backend && python -m pytest tests/test_heures_calmes.py -v`
Expected: FAIL (module absent).

- [ ] **Step 3 : Implémentation**

```python
# briques/agenda/backend/services/heures_calmes.py
"""Heures calmes (S178) : plage « HH:MM-HH:MM » pendant laquelle on ne notifie pas.
Pur, sans I/O. Gère l'enjambement de minuit (22:00-07:00)."""
from __future__ import annotations

from datetime import datetime


def dans_les_heures_calmes(plage: str | None, maintenant: datetime) -> bool:
    if not plage or "-" not in plage:
        return False
    try:
        deb, fin = plage.split("-", 1)
        hd, md = (int(x) for x in deb.strip().split(":"))
        hf, mf = (int(x) for x in fin.strip().split(":"))
    except (ValueError, TypeError):
        return False
    m = maintenant.hour * 60 + maintenant.minute
    d = hd * 60 + md
    f = hf * 60 + mf
    if d == f:
        return False
    if d < f:                       # même jour : [d, f)
        return d <= m < f
    return m >= d or m < f          # enjambe minuit
```

- [ ] **Step 4 : Vérifier le vert**

Run: `cd briques/agenda/backend && python -m pytest tests/test_heures_calmes.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5 : Commit**

```bash
git add briques/agenda/backend/services/heures_calmes.py briques/agenda/backend/tests/test_heures_calmes.py
git commit -m "feat(s178): helper heures calmes (pur, enjambe minuit)"
```

---

### Task C3 : Composition du digest (`services/digest.py`)

**Files:**
- Create: `briques/agenda/backend/services/digest.py`
- Test: `briques/agenda/backend/tests/test_digest_service.py`

**Interfaces:**
- Consumes : des dicts d'events déjà chargés (pas d'I/O dans la composition pure).
- Produces :
  - `composer(nom: str, events: list[dict], cadence: str) -> dict` → `{"texte": str, "html": str, "sujet": str}`. `events` = `[{"titre","debut","calendrier"}]` triés. `texte` = résumé court (push) ; `html` = email riche ; `sujet` = « Ton agenda du jour »/« … de la semaine ». Liste vide ⇒ texte « Rien de prévu ».

- [ ] **Step 1 : Test qui échoue**

```python
# briques/agenda/backend/tests/test_digest_service.py
from services.digest import composer


def test_composer_quotidien_liste_events():
    events = [{"titre": "Dentiste", "debut": "2026-07-16T09:00", "calendrier": "Perso"},
              {"titre": "Réunion", "debut": "2026-07-16T14:00", "calendrier": "Boulot"}]
    d = composer("Marina", events, "quotidien")
    assert "jour" in d["sujet"].lower()
    assert "Dentiste" in d["texte"] and "Réunion" in d["texte"]
    assert "Dentiste" in d["html"] and "<" in d["html"]     # html balisé
    assert "Marina" in d["html"]


def test_composer_vide():
    d = composer("Marina", [], "quotidien")
    assert "Rien" in d["texte"]


def test_composer_hebdo_sujet():
    d = composer("Marina", [], "hebdo")
    assert "semaine" in d["sujet"].lower()
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd briques/agenda/backend && python -m pytest tests/test_digest_service.py -v`
Expected: FAIL.

- [ ] **Step 3 : Implémentation**

```python
# briques/agenda/backend/services/digest.py
"""Composition du digest (S178) : texte court (push) + HTML riche (email). PUR — reçoit
les events déjà chargés, ne fait pas d'I/O. Gabarit déterministe, aucun LLM."""
from __future__ import annotations

import html as _h


def _heure(iso: str) -> str:
    return iso[11:16] if len(iso) >= 16 else iso


def composer(nom: str, events: list[dict], cadence: str) -> dict:
    quand = "du jour" if cadence == "quotidien" else "de la semaine"
    sujet = f"Ton agenda {quand}"
    if not events:
        texte = f"{sujet} : rien de prévu. Bonne journée !"
        html = f"<h2>Bonjour {_h.escape(nom)}</h2><p>Rien de prévu {quand}. 🌤️</p>"
        return {"texte": texte, "html": html, "sujet": sujet}

    lignes = [f"• {_heure(e['debut'])} {e['titre']}" for e in events]
    texte = f"{sujet} ({len(events)}) :\n" + "\n".join(lignes)

    items = "".join(
        f"<li><strong>{_h.escape(_heure(e['debut']))}</strong> — {_h.escape(e['titre'])}"
        f" <em style='color:#9a8f80'>({_h.escape(e.get('calendrier',''))})</em></li>"
        for e in events)
    html = (f"<div style='font-family:sans-serif;color:#1A1612'>"
            f"<h2>Bonjour {_h.escape(nom)}</h2>"
            f"<p>Voici ton agenda {quand} — {len(events)} événement(s) :</p>"
            f"<ul>{items}</ul></div>")
    return {"texte": texte, "html": html, "sujet": sujet}
```

- [ ] **Step 4 : Vérifier le vert**

Run: `cd briques/agenda/backend && python -m pytest tests/test_digest_service.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5 : Commit**

```bash
git add briques/agenda/backend/services/digest.py briques/agenda/backend/tests/test_digest_service.py
git commit -m "feat(s178): composition du digest (texte push + HTML email, pur)"
```

---

### Task C4 : Brique mail — envoi HTML direct (`POST /mail/envoyer`)

**Files:**
- Modify: `briques/mail/envoi.py` (`envoyer(..., corps_html=None)`)
- Modify: `briques/mail/main.py` (schéma `EnvoiDirectEntree` + route `POST /mail/envoyer`)
- Test: `briques/mail/test_envoi_direct.py`

**Interfaces:**
- Consumes : `stockage.lister_comptes(tenant)`, `_compte_du_brouillon`-like auto-pick (réutiliser la logique de `/mail/composer`), `tenant_actuel` (dépendance existante).
- Produces (contrat réseau) :
  - `POST /mail/envoyer` `{a, sujet, corps, corps_html?}` (tenant) → `{ok, envoye, mode}`. Auto-sélectionne l'unique boîte réelle ; aucune ⇒ envoi **simulé** honnête (`mode:"simule"`).
  - `envoi.envoyer(compte, *, a, sujet, corps, corps_html=None, en_reponse_a_uid="")` : si `corps_html`, `msg.add_alternative(corps_html, subtype="html")`.

- [ ] **Step 1 : Test qui échoue**

```python
# briques/mail/test_envoi_direct.py
from fastapi.testclient import TestClient
import main


def test_envoyer_direct_simule_sans_boite():
    c = TestClient(main.app)
    r = c.post("/mail/envoyer", json={"a": "x@example.org", "sujet": "Digest",
                                      "corps": "texte", "corps_html": "<b>hi</b>"})
    assert r.status_code == 200
    assert r.json()["mode"] == "simule" and r.json()["envoye"] is True


def test_envoi_html_alternative():
    from envoi import envoyer
    # compte None ⇒ simulé, mais l'appel ne doit pas lever avec corps_html
    res = envoyer(None, a="x@example.org", sujet="s", corps="t", corps_html="<b>h</b>")
    assert res["mode"] == "simule"
```

*(adapter à d'éventuelles fixtures/headers de tenant de la brique mail ; par défaut le tenant est mock.)*

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd briques/mail && python -m pytest test_envoi_direct.py -v`
Expected: FAIL (route absente).

- [ ] **Step 3 : Implémentation**

`envoi.py` — signature + alternative HTML :

```python
def _construire(de, a, sujet, corps, en_reponse_a_uid="", corps_html=None):
    msg = EmailMessage()
    msg["From"] = de; msg["To"] = a; msg["Subject"] = sujet
    if en_reponse_a_uid:
        msg["In-Reply-To"] = en_reponse_a_uid
        msg["References"] = en_reponse_a_uid
    msg.set_content(corps)
    if corps_html:
        msg.add_alternative(corps_html, subtype="html")
    return msg


def envoyer(compte, *, a, sujet, corps, en_reponse_a_uid="", corps_html=None):
    if not a:
        raise RuntimeError("Pas de destinataire.")
    if compte is None:
        return {"envoye": True, "mode": "simule", "de": "simulé",
                "message": "Envoi SIMULÉ (boîte mock) : aucun email réel n'a été envoyé."}
    de = compte["utilisateur"]
    host, port = serveur_smtp(compte)
    msg = _construire(de, a, sujet, corps, en_reponse_a_uid, corps_html)
    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo(); s.starttls(); s.login(de, compte["mot_de_passe"]); s.send_message(msg)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Envoi SMTP refusé via {host}:{port}.") from e
    return {"envoye": True, "mode": "reel", "de": de, "message": f"Envoyé à {a}."}
```

`main.py` — schéma + route (réutiliser l'auto-pick de `/mail/composer`) :

```python
class EnvoiDirectEntree(BaseModel):
    a: str
    sujet: str
    corps: str
    corps_html: str | None = None
    compte: str = ""


@app.post("/mail/envoyer", status_code=200)
def envoyer_direct(corps: EnvoiDirectEntree, tenant: str = Depends(tenant_actuel)):
    """Envoi DIRECT (pas un brouillon) — sert le digest S178. Auto-boîte si une seule
    réelle ; sinon SIMULÉ honnête."""
    if not corps.a.strip():
        raise HTTPException(422, "Destinataire requis.")
    comptes = stockage.lister_comptes(tenant)
    addr = corps.compte.strip() or (comptes[0]["utilisateur"] if len(comptes) == 1 else "")
    compte = next((c for c in comptes if c["utilisateur"] == addr), None) if addr else None
    if addr and compte is None:
        raise HTTPException(404, f"Boîte « {addr} » non connectée.")
    # compte réel : recharger avec secret déchiffré comme le fait _compte_du_brouillon
    reel = _compte_du_brouillon(tenant, {"compte": addr}) if addr else None
    res = envoi.envoyer(reel, a=corps.a.strip(), sujet=corps.sujet,
                        corps=corps.corps, corps_html=corps.corps_html)
    return {"ok": True, "envoye": res["envoye"], "mode": res["mode"]}
```

*(vérifier la signature exacte de `_compte_du_brouillon` — il prend `(tenant, br_dict)` et lit `br["compte"]` ; l'appel ci-dessus lui passe un dict minimal.)*

- [ ] **Step 4 : Vérifier le vert**

Run: `cd briques/mail && python -m pytest test_envoi_direct.py -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add briques/mail/envoi.py briques/mail/main.py briques/mail/test_envoi_direct.py
git commit -m "feat(s178): brique mail — envoi HTML direct /mail/envoyer (pour digest)"
```

---

### Task C5 : Endpoint `POST /digests/executer` (agenda)

**Files:**
- Create: `briques/agenda/backend/routers/digests.py`
- Modify: `briques/agenda/backend/main.py` (monter le router)
- Test: `briques/agenda/backend/tests/test_digests_executer.py`

**Interfaces:**
- Consumes : `services.digest.composer` (C3), `services.heures_calmes.dans_les_heures_calmes` (C2), `UserProfile` (C1), lecture d'events du jour/semaine (réutiliser la logique de `routers/events.py`/`services` d'agrégation — charger les events où le user participe sur la fenêtre), `settings.DIGEST_KEY/DIGEST_HEURE/DIGEST_TZ/CONNEXION_URL/CONNEXION_KEY`, brique mail via `settings` (ajouter `MAIL_URL` si absent — voir note).
- Produces (contrat réseau) : `POST /digests/executer` (en-tête `X-API-Key: DIGEST_KEY`) → `{"traites": int, "envoyes_push": int, "envoyes_email": int}`. Idempotent par (user, jour) via `dernier_digest_*`.

**Logique :**
1. Rejeter si `X-API-Key != settings.DIGEST_KEY` (403). Si `DIGEST_KEY` vide ⇒ 503 (« digest non configuré »).
2. `maintenant = datetime.now(ZoneInfo(settings.DIGEST_TZ))`. Si `maintenant.hour < settings.DIGEST_HEURE` ⇒ no-op `{"traites":0,...}` (pas encore l'heure).
3. Charger les profils avec `digest_cadence != "off"`.
4. Pour chacun :
   - `quotidien` : si `dernier_digest_quotidien == aujourd_hui` → skip (idempotence).
   - `hebdo` : n'agir que si `maintenant.weekday() == 0` (lundi) et `dernier_digest_hebdo != cle_semaine`.
   - si `dans_les_heures_calmes(prof.heures_calmes, maintenant)` → skip.
   - charger events (jour ou semaine), `composer(...)`.
   - si `digest_push` : POST `/pousser` `{utilisateur: user_id, texte: f"{sujet}\n{texte}"}` (best-effort).
   - si `digest_email` et `prof.email` : POST brique mail `/mail/envoyer` `{a: prof.email, sujet, corps: texte, corps_html: html}` (best-effort).
   - marquer `dernier_digest_*` = aujourd'hui / clé semaine ; commit.

**Note MAIL_URL :** ajouter `MAIL_URL: str = ""` et `MAIL_KEY: str = ""` à `config.py` (repli : email désactivé si vide). L'ajouter dans le même commit que ce task.

- [ ] **Step 1 : Test qui échoue**

```python
# briques/agenda/backend/tests/test_digests_executer.py
import pytest, respx
from httpx import Response
from datetime import datetime


@pytest.mark.asyncio
async def test_executer_exige_cle(client):
    r = client.post("/digests/executer")           # sans X-API-Key
    assert r.status_code in (403, 503)


@respx.mock
def test_executer_pousse_et_marque_idempotent(client, monkeypatch, seed_profil_quotidien):
    from config import settings
    monkeypatch.setattr(settings, "DIGEST_KEY", "dk")
    monkeypatch.setattr(settings, "DIGEST_HEURE", 0)   # toujours l'heure en test
    monkeypatch.setattr(settings, "CONNEXION_URL", "http://connexion")
    pousser = respx.post("http://connexion/pousser").mock(return_value=Response(200, json={"ok": True}))
    r1 = client.post("/digests/executer", headers={"X-API-Key": "dk"})
    assert r1.status_code == 200 and r1.json()["traites"] >= 1
    n = pousser.call_count
    r2 = client.post("/digests/executer", headers={"X-API-Key": "dk"})   # 2e fois même jour
    assert pousser.call_count == n                 # idempotent : rien de re-poussé
```

*(`seed_profil_quotidien` : fixture à créer dans ce test — insère un `UserProfile` `digest_cadence="quotidien", digest_push=True` + un event du jour pour ce user. S'appuyer sur les fixtures DB existantes.)*

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd briques/agenda/backend && python -m pytest tests/test_digests_executer.py -v`
Expected: FAIL (route absente).

- [ ] **Step 3 : Implémentation**

Ajouter à `config.py` : `MAIL_URL: str = ""`, `MAIL_KEY: str = ""`.

`routers/digests.py` (charger les events via le service d'agrégation existant — repérer la fonction réelle qui liste les events d'un user sur une fenêtre, ex. dans `routers/service.py`/`services`; ci-dessous un helper local `_events_fenetre`) :

```python
"""Digest quotidien/hebdo (S178) : composé ici, poussé (connexion) et/ou emailé (mail
6030). Déclenché par l'horloge du Cœur (POST /digests/executer, clé interne DIGEST_KEY).
Idempotent par (user, jour). Anti-intrusif : off par défaut + heures calmes respectées."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db import get_db
from models.orm import UserProfile
from services.digest import composer
from services.heures_calmes import dans_les_heures_calmes

router = APIRouter(tags=["digests"])


async def _events_fenetre(db, user_id, debut, fin) -> list[dict]:
    """Events où `user_id` participe entre debut/fin (triés). Réutiliser la logique
    d'agrégation existante ; forme attendue par composer : titre/debut/calendrier."""
    # ... requête sur Event + EventParticipant, mappée en dicts ...
    return []


def _garde(cle: str | None):
    if not settings.DIGEST_KEY:
        raise HTTPException(503, "Digest non configuré.")
    if cle != settings.DIGEST_KEY:
        raise HTTPException(403, "Clé digest invalide.")


@router.post("/digests/executer")
async def executer(x_api_key: str | None = Header(default=None),
                   db: AsyncSession = Depends(get_db)):
    _garde(x_api_key)
    tz = ZoneInfo(settings.DIGEST_TZ)
    maintenant = datetime.now(tz)
    if maintenant.hour < settings.DIGEST_HEURE:
        return {"traites": 0, "envoyes_push": 0, "envoyes_email": 0}
    aujourd = maintenant.date().isoformat()
    cle_sem = f"{maintenant.isocalendar().year}-W{maintenant.isocalendar().week}"

    profs = (await db.execute(
        select(UserProfile).where(UserProfile.digest_cadence != "off"))).scalars().all()
    traites = push_n = mail_n = 0
    for p in profs:
        if dans_les_heures_calmes(p.heures_calmes, maintenant):
            continue
        if p.digest_cadence == "quotidien":
            if p.dernier_digest_quotidien == aujourd:
                continue
            debut = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)
            fin = debut + timedelta(days=1)
        else:  # hebdo
            if maintenant.weekday() != 0 or p.dernier_digest_hebdo == cle_sem:
                continue
            debut = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)
            fin = debut + timedelta(days=7)
        events = await _events_fenetre(db, p.user_id, debut, fin)
        d = composer(p.display_name, events, p.digest_cadence)
        if p.digest_push and settings.CONNEXION_URL:
            if await _pousser(p.user_id, f"{d['sujet']}\n{d['texte']}"):
                push_n += 1
        if p.digest_email and p.email and settings.MAIL_URL:
            if await _emailer(p.email, d["sujet"], d["texte"], d["html"]):
                mail_n += 1
        if p.digest_cadence == "quotidien":
            p.dernier_digest_quotidien = aujourd
        else:
            p.dernier_digest_hebdo = cle_sem
        traites += 1
    await db.commit()
    return {"traites": traites, "envoyes_push": push_n, "envoyes_email": mail_n}


async def _pousser(user_id: str, texte: str) -> bool:
    ent = {"X-API-Key": settings.CONNEXION_KEY} if settings.CONNEXION_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{settings.CONNEXION_URL.rstrip('/')}/pousser",
                         json={"utilisateur": user_id, "texte": texte}, headers=ent)
        return True
    except Exception:  # noqa: BLE001
        return False


async def _emailer(a: str, sujet: str, corps: str, html: str) -> bool:
    ent = {"X-API-Key": settings.MAIL_KEY} if settings.MAIL_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(f"{settings.MAIL_URL.rstrip('/')}/mail/envoyer",
                         json={"a": a, "sujet": sujet, "corps": corps, "corps_html": html},
                         headers=ent)
        return True
    except Exception:  # noqa: BLE001
        return False
```

**Implémenter `_events_fenetre`** en réutilisant la requête existante d'agrégation d'events par participant (repérer dans `routers/service.py`/`services` la fonction qui joint `Event`+`EventParticipant` et applique la récurrence S175 ; à défaut, requête directe `Event` filtrée sur la fenêtre + participants). Forme de sortie : `{"titre","debut" (ISO), "calendrier"}`.

`main.py` — monter :

```python
from routers import digests as digests_router
app.include_router(digests_router.router)
```

- [ ] **Step 4 : Vérifier le vert**

Run: `cd briques/agenda/backend && python -m pytest tests/test_digests_executer.py -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add briques/agenda/backend/routers/digests.py briques/agenda/backend/config.py briques/agenda/backend/main.py briques/agenda/backend/tests/test_digests_executer.py
git commit -m "feat(s178): POST /digests/executer (idempotent, heures calmes, push+email)"
```

---

### Task C6 : Déclencheur `_check_digest` dans le Cœur

**Files:**
- Modify: `core/proactif.py` (fonction `_check_digest` + ajout à `CHECKS`)
- Test: fichier de test proactif existant (repérer, ex. `core/test_proactif.py` ou `tests/`)

**Interfaces:**
- Consumes : `orchestrateur._brique_base(registre, "agenda")` (motif de `_pousser_messagerie`), `os.getenv("AGENDA_KEY")` (clé S2S agenda) ou `DIGEST_KEY`.
- Produces : `async def _check_digest(registre) -> int` — POST `agenda /digests/executer` avec `X-API-Key: DIGEST_KEY` ; renvoie 0 (le digest n'alimente pas le magasin de rappels). Ajouté à `CHECKS`.

**Note :** l'agenda no-op si ce n'est pas l'heure / déjà envoyé, donc appeler à chaque tick proactif est sûr et idempotent.

- [ ] **Step 1 : Test qui échoue**

```python
# dans le test proactif du Cœur
import asyncio
from unittest.mock import patch, AsyncMock
import proactif


def test_check_digest_appelle_agenda(monkeypatch):
    monkeypatch.setenv("DIGEST_KEY", "dk")
    with patch.object(proactif.orchestrateur, "_brique_base", return_value="http://agenda"), \
         patch("proactif.httpx.AsyncClient") as cli:
        inst = cli.return_value.__aenter__.return_value
        inst.post = AsyncMock(return_value=None)
        n = asyncio.get_event_loop().run_until_complete(proactif._check_digest({}))
        assert n == 0
        assert inst.post.await_args.args[0].endswith("/digests/executer")
```

*(adapter l'accès `orchestrateur`/`httpx` au style réel du module.)*

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd core && python -m pytest test_proactif.py -k digest -v` (adapter le chemin réel).
Expected: FAIL (`_check_digest` absent).

- [ ] **Step 3 : Implémentation**

Dans `core/proactif.py`, après `_check_geo` :

```python
async def _check_digest(registre) -> int:
    """Déclenche le digest agenda (S178). L'agenda décide seul cadence/heure/idempotence :
    on peut appeler à chaque tick sans risque. Best-effort, ne lève jamais."""
    cle = os.getenv("DIGEST_KEY", "")
    if not cle:
        return 0
    try:
        base = orchestrateur._brique_base(registre, "agenda")
    except Exception:  # noqa: BLE001
        return 0
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(f"{base}/digests/executer", headers={"X-API-Key": cle})
    except Exception as ex:  # noqa: BLE001
        logger.warning("Proactif digest : %s", ex)
    return 0


CHECKS = [_check_agenda, _check_documents, _check_geo, _check_digest]
```

- [ ] **Step 4 : Vérifier le vert**

Run: `cd core && python -m pytest test_proactif.py -k digest -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add core/proactif.py core/test_proactif.py
git commit -m "feat(s178): _check_digest — l'horloge du Cœur déclenche le digest agenda"
```

---

### Task C7 : Préférences notif — `PATCH /profiles/me/notifs` + panneau UI

**Files:**
- Modify: `briques/agenda/backend/routers/profiles.py` (route PATCH)
- Modify: `briques/agenda/backend/models/schemas.py` (schéma `NotifPrefsEntree` + `NotifPrefsOut`)
- Modify: `briques/agenda/backend/templates_app.py` (contrôles digest dans le panneau 🔔)
- Test: `briques/agenda/backend/tests/test_profil_email_prefs.py` (ajout)

**Interfaces:**
- Produces (contrat réseau) : `PATCH /profiles/me/notifs` (Bearer) `{digest_cadence?, digest_push?, digest_email?, heures_calmes?}` → profil à jour. Valide `digest_cadence ∈ {off,quotidien,hebdo}`, `heures_calmes` au format `HH:MM-HH:MM` ou vide.

- [ ] **Step 1 : Test qui échoue**

```python
# (ajout à tests/test_profil_email_prefs.py)
def test_patch_notifs(client_auth):
    r = client_auth.patch("/profiles/me/notifs",
                          json={"digest_cadence": "hebdo", "digest_email": True,
                                "heures_calmes": "22:00-07:00"})
    assert r.status_code == 200
    body = r.json()
    assert body["digest_cadence"] == "hebdo" and body["digest_email"] is True


def test_patch_notifs_cadence_invalide(client_auth):
    r = client_auth.patch("/profiles/me/notifs", json={"digest_cadence": "toujours"})
    assert r.status_code == 422
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd briques/agenda/backend && python -m pytest tests/test_profil_email_prefs.py -k notifs -v`
Expected: FAIL.

- [ ] **Step 3 : Implémentation**

`models/schemas.py` :

```python
from pydantic import BaseModel, field_validator

class NotifPrefsEntree(BaseModel):
    digest_cadence: str | None = None
    digest_push: bool | None = None
    digest_email: bool | None = None
    heures_calmes: str | None = None

    @field_validator("digest_cadence")
    @classmethod
    def _cadence(cls, v):
        if v is not None and v not in ("off", "quotidien", "hebdo"):
            raise ValueError("cadence invalide")
        return v
```

`routers/profiles.py` :

```python
from models.schemas import NotifPrefsEntree

@router.patch("/profiles/me/notifs")
async def patch_notifs(body: NotifPrefsEntree,
                       db: AsyncSession = Depends(get_db),
                       user: dict = Depends(get_current_user)):
    prof = await db.get(UserProfile, user["sub"])
    if prof is None:
        nom = user.get("name") or user.get("preferred_username") or user["sub"]
        prof = await profils.upsert(db, user["sub"], nom, email=user.get("email"))
    for champ in ("digest_cadence", "digest_push", "digest_email", "heures_calmes"):
        val = getattr(body, champ)
        if val is not None:
            setattr(prof, champ, val)
    await db.commit(); await db.refresh(prof)
    return {"digest_cadence": prof.digest_cadence, "digest_push": prof.digest_push,
            "digest_email": prof.digest_email, "heures_calmes": prof.heures_calmes}
```

*(importer `UserProfile` et `get_db` dans `profiles.py` si absents.)*

`templates_app.py` — dans `#panneau-notifs`, ajouter les contrôles (select cadence, cases push/email, champ heures calmes) + un `enregistrerNotifs()` qui `PATCH /profiles/me/notifs`. Code JS :

```javascript
async function enregistrerNotifs() {
  const body = {
    digest_cadence: document.getElementById("digest-cadence").value,
    digest_push: document.getElementById("digest-push").checked,
    digest_email: document.getElementById("digest-email").checked,
    heures_calmes: document.getElementById("heures-calmes").value.trim(),
  };
  await fetch("/profiles/me/notifs", { method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }), body: JSON.stringify(body) });
  alert("Préférences enregistrées.");
}
```

HTML (dans le panneau) :

```html
<label>Digest :
  <select id="digest-cadence"><option value="off">Aucun</option>
  <option value="quotidien">Quotidien</option><option value="hebdo">Hebdo</option></select></label>
<label><input type="checkbox" id="digest-push"> par notification</label>
<label><input type="checkbox" id="digest-email"> par email</label>
<label>Heures calmes : <input id="heures-calmes" placeholder="22:00-07:00"></label>
<button onclick="enregistrerNotifs()">Enregistrer</button>
```

- [ ] **Step 4 : Vérifier le vert**

Run: `cd briques/agenda/backend && python -m pytest tests/test_profil_email_prefs.py -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add briques/agenda/backend/routers/profiles.py briques/agenda/backend/models/schemas.py briques/agenda/backend/templates_app.py briques/agenda/backend/tests/test_profil_email_prefs.py
git commit -m "feat(s178): préférences digest (PATCH /profiles/me/notifs + panneau UI)"
```

---

### Task C8 : Heures calmes appliquées aux notifs de listes (S176)

**Files:**
- Modify: `briques/agenda/backend/services/notifications.py` (`notifier_membres` saute les cibles en heures calmes)
- Test: `briques/agenda/backend/tests/test_shopping_notifications.py` (ajout)

**Interfaces:**
- Consumes : `services.heures_calmes.dans_les_heures_calmes` (C2), `UserProfile.heures_calmes` (C1).
- Produces : `notifier_membres` ne pousse pas vers un membre actuellement dans ses heures calmes.

- [ ] **Step 1 : Test qui échoue**

```python
# (ajout à tests/test_shopping_notifications.py)
@pytest.mark.asyncio
async def test_heures_calmes_saute_le_push(db_session, monkeypatch):
    # profil membre en heures calmes 00:00-23:59 → aucun push
    ...
    from services import notifications
    n = await notifications.notifier_membres(db_session, liste, acteur_id="autre", texte="🔔 x\ny")
    assert n == 0
```

*(compléter le seed liste/membre en réutilisant les fixtures existantes du fichier.)*

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_notifications.py -k calmes -v`
Expected: FAIL.

- [ ] **Step 3 : Implémentation**

Dans `services/notifications.py`, avant de pousser vers `uid`, charger le profil et sauter s'il est en heures calmes :

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from services.heures_calmes import dans_les_heures_calmes
from models.orm import UserProfile

# ... dans la boucle for uid in cibles :
    prof = await db.get(UserProfile, uid)
    if prof and dans_les_heures_calmes(prof.heures_calmes,
                                       datetime.now(ZoneInfo(settings.DIGEST_TZ))):
        continue
```

- [ ] **Step 4 : Vérifier le vert**

Run: `cd briques/agenda/backend && python -m pytest tests/test_shopping_notifications.py -v`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add briques/agenda/backend/services/notifications.py briques/agenda/backend/tests/test_shopping_notifications.py
git commit -m "feat(s178): heures calmes respectées par les notifs de listes (S176)"
```

---

# Phase D — Finition

### Task D1 : Suites complètes + README + roadmap

**Files:**
- Modify: `briques/agenda/backend/README.md` (section `## S178`), `briques/connexion/README.md` (adaptateur webpush + endpoints /push).
- Modify: `docs/sprints/S174-S180-roadmap-agenda-best-in-class.md` (statut S178 → CODE-COMPLET).

- [ ] **Step 1 : Suite agenda complète**

Run: `cd briques/agenda/backend && python -m pytest -q`
Expected: PASS (≈261 + nouveaux tests, 0 échec ; skips redis tolérés).

- [ ] **Step 2 : Suite connexion**

Run: `cd briques/connexion && python -m pytest -q`
Expected: PASS.

- [ ] **Step 3 : Suite mail + cœur**

Run: `cd briques/mail && python -m pytest -q` puis (racine) `make test-core`
Expected: PASS (cœur 439 + test `_check_digest`).

- [ ] **Step 4 : Docs**

Rédiger la section README agenda `## S178 — PWA + push web + digest` (comportement livré, env, anti-intrusif, limites : iOS écran d'accueil, offline lecture seule, heures calmes du rappel temps-réel du Cœur = fast-follow) ; README connexion (adaptateur `webpush`, `/push/*`, VAPID). Mettre le statut S178 à jour dans la roadmap.

- [ ] **Step 5 : Commit**

```bash
git add briques/agenda/backend/README.md briques/connexion/README.md docs/sprints/S174-S180-roadmap-agenda-best-in-class.md
git commit -m "docs(s178): README agenda+connexion + roadmap CODE-COMPLET"
```

---

## RESTE avant déploiement (hors plan, noté)

- Smoke `alembic upgrade head` puis `downgrade 0009` de la migration 0010 sur **Postgres** (les tests utilisent `create_all`).
- Générer les clés VAPID (`vapid --gen` / `py-vapid`) et poser `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`/`VAPID_SUBJECT` (connexion), `VAPID_PUBLIC_KEY`/`DIGEST_KEY`/`MAIL_URL`/`MAIL_KEY` (agenda).
- Vérifier `pywebpush` dans l'image Docker de connexion (requirements + rebuild).
- Vérif LIVE (fin S180) : install PWA + réception d'un push réel + un digest réel.

## Fast-follow (noté dans la roadmap)

- Heures calmes sur le rappel temps-réel du Cœur (`core/proactif.py._check_agenda`).
- Outil LLM `digest_reglages` (piloter le digest à la voix).
- Glyphe/emoji dans les icônes PWA (au-delà du carré uni).
- Sync offline réelle du service worker (écriture).
- PWA du dashboard du Cœur (port 5100).
```
