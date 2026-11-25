# S246 partie 2 — brique `livraison` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** une brique `briques/livraison/` (port 6240) qui donne à l'assistant la lecture de l'état/logs des apps déployées sur Dokploy (VM 100) et trois actions gardées par approbation Telegram : redémarrer, déployer, revenir en arrière.

**Architecture:** FastAPI autonome, client HTTP Dokploy (`x-api-key`) testé contre un **faux serveur** (`httpx.MockTransport`) qui reproduit les contrats relevés en partie 1 (`docs/s246/contrats/`, journal `docs/s246/vm100-installation.md`). Capacités déclarées dans `manifest.json` (zéro code Cœur) ; les 3 actions portent `"sensibilite": "reversible"` (garde S245, reprise S245b). Aucune brique n'accède au socket Docker : seule l'API HTTP de Dokploy est appelée.

**Tech Stack:** Python 3.12, FastAPI 0.115.6, httpx 0.28.1, pydantic, uvicorn 0.34.0 (versions du filet `constraints-workplace.txt`), pytest.

## Global Constraints

- Port **6240** (vérifié libre : 6220 = jeu-factions-public, 6230 = world-engine). Santé `GET /sante`.
- Variables d'env : `DOKPLOY_URL`, `DOKPLOY_API_KEY`, `FORGEJO_URL`, `FORGEJO_TOKEN`, `LIVRAISON_API_KEYS` (variable **propre** à la brique ; jamais `API_KEYS`, lue par ~20 briques). Jamais littérales dans un compose (piège gateway-sync) ; pas de `VAR=${VAR:-}` dans `environment` (piège env-shadow).
- Valeurs réelles (VM 100) : Dokploy `http://100.124.176.122:3000`, Forgejo `http://100.124.176.122:3001` (mesh ; le HP est dans le mesh, ping prouvé).
- Contrats Dokploy v0.31.4 : auth `x-api-key` ; lectures en `GET` + query, mutations en `POST` JSON ; `application.reload` exige `appName` ET `applicationId` ; `application.start|stop` renvoient **l'objet application entier (~5 Ko, contient `refreshToken`)** → n'en extraire que `applicationId, name, appName, applicationStatus` ; `registry.create` renvoie un mot de passe en clair (jamais relayé) ; rollback par `rollbackId` lu dans `application.one → deployments[].rollbackId` (présent seulement si `rollbackActive` + registre).
- Aucune réponse brute de Dokploy n'est renvoyée à l'assistant : on **construit** une réponse minimale (liste blanche de champs).
- Logs : masquage des jetons, e-mails, mots de passe d'URL, `Bearer …` **avant** toute sortie (S249 fera mieux ; ce masque est le minimum).
- Les trois actions : `"action": true`, `"sensibilite": "reversible"`. Lectures : `"action": false`, sans `sensibilite`.
- Style des tests : un fichier de test par module, faux serveur, aucun appel réseau réel. Vérifier les comptes via junit XML (`rtk proxy python3 -m pytest ... -p no:cacheprovider --junitxml=…`).

---

### Task 6 : Squelette de brique

**Files:**
- Create: `briques/livraison/{main.py,conftest.py,Dockerfile,docker-compose.yml,requirements.txt,manifest.json,.env.example,README.md,test_api.py}`

**Interfaces:**
- Produces : `main.app` (FastAPI) avec `GET /sante` → `{"ok": true, "brique": "livraison", "dokploy": bool_configuré}` ; dépendance `cle_api` ; `LIVRAISON_API_KEYS`.

- [ ] **Step 1 : test qui échoue** (`test_api.py`)

```python
from fastapi.testclient import TestClient
import main

c = TestClient(main.app)

def test_sante():
    r = c.get("/sante")
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True and d["brique"] == "livraison"

def test_sante_ne_fuit_aucun_secret():
    assert "key" not in c.get("/sante").text.lower()
```
Run : `cd briques/livraison && python3 -m pytest -q -p no:cacheprovider test_api.py` → FAIL (module absent).

- [ ] **Step 2 : implémentation**

`conftest.py` :
```python
import os
os.environ["LIVRAISON_API_KEYS"] = ""      # mode ouvert en test
os.environ["DOKPLOY_URL"] = "http://dokploy.test"
os.environ["DOKPLOY_API_KEY"] = "cle-de-test"
```
`main.py` :
```python
"""Brique « livraison » — exploitation des apps déployées sur Dokploy (S246)."""
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Livraison — exploitation Dokploy", version="0.1.0")
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])


def _lire_cles_api() -> set[str]:
    """`LIVRAISON_API_KEYS` seule (jamais `API_KEYS`). Absente ou vide = mode ouvert."""
    return {k.strip() for k in os.getenv("LIVRAISON_API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    cles = _lire_cles_api()
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not cles:
        return presentee or "public"
    if presentee in cles:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


@app.get("/sante")
def sante():
    return {"ok": True, "brique": "livraison",
            "dokploy_configure": bool(os.getenv("DOKPLOY_URL") and os.getenv("DOKPLOY_API_KEY"))}
```
`requirements.txt` : `fastapi==0.115.6`, `uvicorn[standard]==0.34.0`, `httpx==0.28.1` (une par ligne).
`Dockerfile` : `FROM python:3.12-slim`, `WORKDIR /app`, `COPY requirements.txt .`, `RUN pip install --no-cache-dir -r requirements.txt`, `COPY . .`, `CMD ["uvicorn","main:app","--host","0.0.0.0","--port","6240"]`.
`docker-compose.yml` : calqué sur `briques/export/docker-compose.yml` (service/conteneur `livraison`, `image: workplace/livraison:0.1.0`, port `6240:6240`, `extra_hosts` host-gateway, `restart: unless-stopped`, healthcheck sur `/sante`) avec **uniquement** `env_file: path ../../.env required: false` — **pas** de bloc `environment` pour les secrets. `.env.example` : `DOKPLOY_URL=`, `DOKPLOY_API_KEY=`, `FORGEJO_URL=`, `FORGEJO_TOKEN=`, `LIVRAISON_API_KEYS=` (tous vides) + un commentaire « jamais `API_KEYS` ».
`manifest.json` : nom `livraison`, famille `infra`, version `0.1.0`, role `livraison`, couche `backend`, statut `a_tester`, port `6240`, `url_sante` `http://host.docker.internal:6240/sante`, `depends_on: []`, `capacites: []`, `taches: []` (les capacités arrivent en Tasks 9-10).

- [ ] **Step 3 :** tests verts ; puis depuis la racine `make smoke` (doit passer : port non collisionné, santé `/sante`).
- [ ] **Step 4 : Commit** `feat(livraison): squelette de brique (port 6240, CLE propre)`.

---

### Task 7 : Client Dokploy + faux serveur

**Files:**
- Create: `briques/livraison/dokploy.py`, `briques/livraison/faux_dokploy.py`, `briques/livraison/test_dokploy.py`

**Interfaces:**
- Produces (`dokploy.py`) :
  - `class DokployErreur(Exception)` avec `.message` (honnête, sans secret) et `.statut`.
  - `class Dokploy: __init__(self, base_url: str, cle: str, transport: httpx.AsyncBaseTransport | None = None, delai: float = 20.0)`.
  - `async apps() -> list[dict]` → `[{"id","nom","app_name","projet","environnement","statut"}]` (via `GET /api/project.all`, aplatit `projects[].environments[].applications[]`).
  - `async app(id_) -> dict` → `{"id","nom","app_name","statut","rollback_actif","deploiements":[{"id","titre","statut","debut","fin","rollback_id"}]}` (via `GET /api/application.one`).
  - `async logs_deploiement(deploiement_id, tail=200) -> str` (via `GET /api/deployment.readLogs`).
  - `async redemarrer(id_) -> dict` : lit `app_name` via `app`, puis `POST /api/application.reload {applicationId, appName}`.
  - `async deployer(id_, titre) -> dict` : `POST /api/application.redeploy {applicationId, title}`.
  - `async rollback(rollback_id) -> dict` : `POST /api/rollback.rollback {rollbackId}`.
- Produces (`faux_dokploy.py`) : `fabrique_transport(etat: dict) -> httpx.MockTransport` qui répond comme le vrai Dokploy (401 sans `x-api-key` correcte, 404 pour un id inconnu, 429 si `etat["limite"]`, **réponses de `start/stop` volontairement grasses** avec un `refreshToken`) et enregistre les appels dans `etat["appels"]` (méthode, chemin, corps).

- [ ] **Step 1 : tests qui échouent** (`test_dokploy.py`)

```python
import asyncio, pytest
from dokploy import Dokploy, DokployErreur
from faux_dokploy import fabrique_transport

def etat():
    return {"cle": "k", "appels": [], "limite": False, "apps": {
        "A1": {"applicationId": "A1", "name": "calendrier", "appName": "calendrier-x",
               "applicationStatus": "done", "rollbackActive": True,
               "deployments": [
                   {"deploymentId": "D2", "title": "v2", "status": "done", "createdAt": "t2",
                    "finishedAt": "t2b", "rollbackId": "R2"},
                   {"deploymentId": "D1", "title": "v1", "status": "done", "createdAt": "t1",
                    "finishedAt": "t1b", "rollbackId": "R1"}]}}}

def cli(e, cle="k"):
    return Dokploy("http://d.test", cle, transport=fabrique_transport(e))

def run(c): return asyncio.run(c)

def test_apps_aplati_sans_champs_inutiles():
    r = run(cli(etat()).apps())
    assert r == [{"id": "A1", "nom": "calendrier", "app_name": "calendrier-x",
                  "projet": "temoin", "environnement": "production", "statut": "done"}]

def test_cle_invalide_message_honnete_sans_secret():
    with pytest.raises(DokployErreur) as e:
        run(cli(etat(), cle="mauvaise").apps())
    assert e.value.statut == 401 and "mauvaise" not in e.value.message

def test_limite_429_dit_clairement_la_cause():
    e = etat(); e["limite"] = True
    with pytest.raises(DokployErreur) as ex:
        run(cli(e).apps())
    assert ex.value.statut == 429 and "limite" in ex.value.message.lower()

def test_app_inconnue_404():
    with pytest.raises(DokployErreur) as ex:
        run(cli(etat()).app("ZZ"))
    assert ex.value.statut == 404

def test_redemarrer_envoie_app_name_et_id_et_ne_renvoie_pas_le_gras():
    e = etat()
    r = run(cli(e).redemarrer("A1"))
    corps = [a for a in e["appels"] if a["chemin"] == "/api/application.reload"][0]["corps"]
    assert corps == {"applicationId": "A1", "appName": "calendrier-x"}
    assert "refreshToken" not in str(r)

def test_rollback_envoie_rollback_id():
    e = etat()
    run(cli(e).rollback("R1"))
    assert e["appels"][-1]["corps"] == {"rollbackId": "R1"}

def test_reseau_coupe_message_honnete():
    import httpx
    def boom(req): raise httpx.ConnectError("x")
    c = Dokploy("http://d.test", "k", transport=httpx.MockTransport(boom))
    with pytest.raises(DokployErreur) as ex:
        run(c.apps())
    assert "joignable" in ex.value.message.lower()

def test_timeout_message_honnete():
    import httpx
    def lent(req): raise httpx.ReadTimeout("x")
    c = Dokploy("http://d.test", "k", transport=httpx.MockTransport(lent))
    with pytest.raises(DokployErreur) as ex:
        run(c.apps())
    assert "délai" in ex.value.message.lower()
```
Run → FAIL (modules absents).

- [ ] **Step 2 : implémenter** `faux_dokploy.py` (routes : `/api/project.all` → `[{"projectId":"P1","name":"temoin","environments":[{"environmentId":"E1","name":"production","applications":[…liste courte {applicationId,name,appName,applicationStatus}]}]}]` ; `/api/application.one` ; `/api/application.reload|redeploy|start|stop` (renvoient l'app entière + `"refreshToken":"SECRET"`) ; `/api/rollback.rollback` → `true` ; `/api/deployment.readLogs` → chaîne). **Vérifier cette forme contre `docs/s246/contrats/dokploy-v0.31.4.openapi.extrait.json` et contre un appel réel de `project.all`** (fait en partie 1 : réponse `[]` sans projet ; avec projet, relever la forme réelle avant de figer le faux — `curl -H "x-api-key: $K" $DOKPLOY_URL/api/project.all`, clé dans `~/.workplace-secrets/s246-comptes.txt`). Puis `dokploy.py` : un `_requete(methode, chemin, params=None, json=None)` unique qui pose `x-api-key`, traduit : `ConnectError/ConnectTimeout` → « Dokploy injoignable », `ReadTimeout` → « Délai dépassé », 401 → « Clé API Dokploy refusée », 404 → « introuvable », 429 → « Limite de débit de l'API Dokploy atteinte (clé créée sans `rateLimitEnabled:false` ?) », autre ≥400 → « Dokploy a répondu <code> » (jamais le corps brut).
- [ ] **Step 3 :** tests verts (`python3 -m pytest -q -p no:cacheprovider test_dokploy.py --junitxml=/tmp/j.xml`, lire les comptes dans le XML).
- [ ] **Step 4 : Commit** `feat(livraison): client Dokploy + faux serveur (contrats v0.31.4)`.

---

### Task 8 : Client Forgejo (lecture des dépôts) + faux serveur

**Files:**
- Create: `briques/livraison/forgejo.py`, `briques/livraison/test_forgejo.py`

**Interfaces:**
- Produces : `class Forgejo: __init__(self, base_url, jeton, transport=None)` ; `async depots() -> list[{"nom","branche","miroir","dernier_commit"}]` (via `GET /api/v1/user/repos` avec `Authorization: token …`, puis `branches/{b}` pour le dernier commit court) ; mêmes règles de traduction d'erreurs que Task 7 (extraire `_traduire` commun dans `erreurs.py` si dupliqué — DRY).
- But : permettre à `livraison_etat` d'afficher « la version déployée = commit X du dépôt Y » ; lecture seule en v1.

- [ ] **Step 1 :** tests (faux transport inline) : liste aplatie, 401 sans jeton, réseau coupé, **aucun jeton dans le message d'erreur**.
- [ ] **Step 2 :** implémenter, tests verts. **Step 3 : Commit** `feat(livraison): client Forgejo lecture seule`.

---

### Task 9 : Capacités de lecture + masquage des logs

**Files:**
- Create: `briques/livraison/masque.py`, `briques/livraison/test_masque.py`
- Modify: `briques/livraison/main.py`, `briques/livraison/manifest.json`, `briques/livraison/test_api.py`

**Interfaces:**
- Produces : `masque.masquer(texte: str) -> str` ; routes `GET /apps`, `GET /apps/{app}/etat`, `GET /apps/{app}/logs?tail=` où `{app}` accepte l'id **ou** le nom (résolution via `Dokploy.apps()` ; ambigu/inconnu → 404 « app introuvable : dites laquelle parmi … ») ; capacités `livraison_apps`, `livraison_etat`, `livraison_logs` (`action:false`).

- [ ] **Step 1 : tests du masque (échec d'abord)**

```python
from masque import masquer

def test_jeton_long_masque():
    assert "abcdef0123456789abcdef0123456789abcd" not in masquer("tok abcdef0123456789abcdef0123456789abcd")

def test_email_masque():
    assert "a@b.fr" not in masquer("contact a@b.fr ok")

def test_bearer_masque():
    assert "XYZ" not in masquer("Authorization: Bearer XYZ.abc")

def test_mdp_dans_url_masque():
    assert "s3cr3t" not in masquer("git clone http://u:s3cr3t@h/x.git")

def test_texte_normal_intact():
    assert masquer("build ok en 12s") == "build ok en 12s"
```
(Reprendre les expressions de `core/outils.py` : `_RE_URL_IDENTIFIANTS`, `_RE_JETON_OPAQUE`, `_RE_QUERY_SECRET`, `_RE_BEARER` ; **copier** les regex dans `masque.py` — la brique est autonome, elle n'importe pas le Cœur — et ajouter l'e-mail `[\w.+-]+@[\w-]+\.[\w.-]+`.)
- [ ] **Step 2 :** implémenter `masque.py`. **Step 3 : tests d'API** (injection du faux serveur : `main.fournisseur = lambda: Dokploy(..., transport=fabrique_transport(etat))`) : `/apps` renvoie la liste blanche ; `/apps/calendrier/etat` (par nom) renvoie statut + dernier déploiement + `rollback_disponible: bool` ; `/apps/A1/logs` renvoie des logs **masqués** (le faux serveur y glisse un jeton et un e-mail) et borne `tail` à ≤ 500 ; Dokploy injoignable → 502 avec message honnête ; app inconnue → 404.
- [ ] **Step 4 :** implémenter les routes + déclarer les 3 capacités dans `manifest.json` (descriptions précises : « liste les applications déployées… », « état d'une app : statut, dernier déploiement, retour arrière possible ? », « dernières lignes de log du dernier déploiement, secrets masqués »). Paramètres : `app` (string, requis), `tail` (integer). Chemins avec `{app}` (le Cœur sait substituer, cf. `_url_dynamique`).
- [ ] **Step 5 :** tests verts + `make smoke`. **Step 6 : Commit** `feat(livraison): capacités de lecture (apps, état, logs masqués)`.

---

### Task 10 : Actions réversibles (redémarrer, déployer, rollback) gardées

**Files:**
- Modify: `briques/livraison/main.py`, `briques/livraison/manifest.json`, `briques/livraison/test_api.py`
- Create: `core/test_livraison_garde.py` (test d'intégration côté Cœur)

**Interfaces:**
- Produces : `POST /apps/{app}/redemarrer`, `POST /apps/{app}/deployer {titre?}`, `POST /apps/{app}/rollback {version?}` ; capacités `livraison_redemarrer`, `livraison_deployer`, `livraison_rollback`, chacune `"action": true, "sensibilite": "reversible"`.
- Règle rollback : sans `version`, prend le **déploiement précédent** portant un `rollback_id` (le courant est le premier de la liste) ; avec `version` (id de déploiement ou titre), prend celui-là ; aucun `rollback_id` disponible → 409 « retour arrière impossible : le rollback n'est pas activé sur cette app ou il n'y a pas de version antérieure » (jamais d'invention d'identifiant). La réponse inclut `version_visee` (titre) pour que le résumé d'approbation soit lisible.

- [ ] **Step 1 : tests qui échouent** — redémarrer appelle `reload` avec `appName`+`applicationId` ; déployer appelle `redeploy` avec le titre ; rollback par défaut cible `R1` (précédent) ; rollback sans version antérieure → 409 ; rollback avec `version="v2"` cible `R2` ; **aucune réponse ne contient `refreshToken`** ; Dokploy 429/injoignable → 502 honnête ; app ambiguë → 404.
- [ ] **Step 2 :** implémenter. **Step 3 :** déclarer les 3 capacités (`"sensibilite": "reversible"` ; descriptions : *« …À n'appeler qu'après que l'utilisateur l'ait demandé ; l'exécution attend son approbation sur Telegram. »*).
- [ ] **Step 4 : test Cœur** (`core/test_livraison_garde.py`, motif de `core/test_approbations_bout_en_bout.py`) : le manifeste de `briques/livraison` chargé dans le registre ⇒ `outils.est_sensible("livraison_redemarrer", registre) == "reversible"` pour les 3 actions et `None` pour les 3 lectures ; un appel `outils.executer` sans approbation est **refusé** (aucun appel HTTP vers la brique : faux client) ; après approbation + reprise (`approbations_reprise.reprendre`) l'appel part **une seule fois**.
- [ ] **Step 5 :** tests verts (brique + `core/test_livraison_garde.py` + `core/test_approbations_*.py` non régressés, comptes lus dans le XML junit). **Step 6 : Commit** `feat(livraison): actions réversibles gardées par approbation`.

---

### Task 11 : Contrat manifeste↔route, launcher, profil Ansible

**Files:**
- Modify: `Lancer Workplace.command`, `infra/ansible/profiles/hp.yml` (entrée `livraison`, port 6240, sonde `/sante`, `env_file`), `docs/sprints/S246-forgejo-dokploy-exploitation.md` (statut), `GUIDE-…` si une liste de briques y figure ; `.env.example` racine (variables `DOKPLOY_URL`, `DOKPLOY_API_KEY`, `FORGEJO_URL`, `FORGEJO_TOKEN`, `LIVRAISON_API_KEYS` **vides**).
- Test : le filet S210 (contrat manifeste↔route, `tests/`) et `make smoke`.

- [ ] **Step 1 :** localiser et lancer le filet S210 (grep `test_contrat_manifeste` / `S210`) : il doit échouer si une capacité de `livraison` pointe une route absente ; le faire passer (vérifier aussi qu'une route renommée à dessein le fait échouer, puis restaurer).
- [ ] **Step 2 :** ajouter la ligne launcher `"livraison|$RACINE/briques/livraison|http://localhost:6240/sante"` (avant `core`) et l'entrée du profil `hp.yml` en copiant celle de `export`.
- [ ] **Step 3 :** `make smoke` + tests Ansible (`infra/ansible/tests`) verts. **Step 4 : Commit** `feat(livraison): launcher, profil HP, contrat manifeste↔route`.

---

### Task 12 : Preuve LIVE (SLIVE) et activation des clés d'approbation

**Ordre imposé : ne rien activer avant que les étapes 1-3 soient vertes.**

- [ ] **Step 1 : Déployer la brique sur le HP** (image construite sur le Mac, `docker save | gzip | ssh docker load`, cf. piège DNS NetBird) avec, dans le `.env` racine du HP : `DOKPLOY_URL=http://100.124.176.122:3000`, `DOKPLOY_API_KEY=<clé de ~/.workplace-secrets>`, `FORGEJO_URL=http://100.124.176.122:3001`, `FORGEJO_TOKEN=<jeton lecture>`, `LIVRAISON_API_KEYS=<openssl rand -hex 32>`. Vérifier `/sante` et `curl $HP:6240/apps` (la liste doit contenir `calendrier-familial`).
- [ ] **Step 2 : Lecture réelle** : `livraison_apps`, `livraison_etat`, `livraison_logs` depuis l'assistant (CORS/clé Cœur→brique : la clé `LIVRAISON_API_KEYS` doit aussi être celle que le Cœur envoie — vérifier `_entetes_brique`).
- [ ] **Step 3 : Activation des approbations (S245/S245b)** : `.env` racine du HP — `APPROBATIONS_CLE` identique des deux côtés, `CONNEXION_KEY` = `CONNEXION_API_KEYS` (**jamais `API_KEYS`**) ; recréer **ensemble** Cœur + connexion + geo + agenda + standard-telephonique + livraison ; marquer l'approbateur (`POST /correspondances/approbateur`) ; `/sante-globale` verte.
- [ ] **Step 4 : Preuve Telegram** sur Calendrier Familial (instance de test, **aucune donnée réelle**) : demander à l'assistant de redémarrer → bouton Telegram → exécution → état `done` ; déployer → idem ; rollback → idem, avec **vérification de l'image** (`docker service inspect` : `:latest` → `:vN`) et de la santé de l'app. Vérifier aussi : refus (bouton « Refuser ») ⇒ rien n'est exécuté ; autre utilisateur ⇒ « introuvable ».
- [ ] **Step 5 :** consigner la preuve dans `docs/s246/preuve-calendrier-familial.md` (versions, durées, RAM VM 100) ; mettre à jour la mémoire `sprint-s245-…`, l'épopée et S246 (statut « livré ») ; **Commit** `docs(s246): preuve LIVE + activation des approbations`.

## Self-review (spec ↔ plan)

- Lecture (`apps/etat/logs`) → T9 ; actions (`redémarrer/déployer/rollback`) → T10 ; approbation Telegram → T10 step 4 + T12 ; clé API / jeton en env, jamais en clair → contraintes + T6/T12 ; logs filtrés → T9 ; faux serveur → T7-T8 ; filet S210 + smoke → T11 ; SLIVE groupé → T12 ; activation des clés seulement à la fin → T12 step 3.
- **Prérequis Forge** (JWT absent à la reprise) : sans objet pour `livraison` (clés de service, aucune identité Forge) ; reste à traiter avant toute capacité Forge sensible.
- Hors périmètre : sauvegarde/reset (S247), collecte d'erreurs (S249), miroir de tous les dépôts (idée notée en S247).
