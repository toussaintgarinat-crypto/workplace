# S179 — Capacités asynchrones (Synopsis vidéo) — design

**Sprint** : S179. **Briques** : `synopsis` (port 6090, version 1.1.0 → 1.2.0)
+ `core` (Cœur, conteneur `core-core-1`).
**Famille** : `media`. **Déclencheur** : bug rapporté — l'assistant Workplace
échoue (500/timeout) quand on colle une URL YouTube ; racine : `AsyncClient(timeout=30)`
dans `core/outils.py:447` tue le pipeline synopsis qui dure ≥ 50 s.

## Problème

`core/outils.py:447` ouvre `httpx.AsyncClient(timeout=30)` partagé par tous les
`dispatch` (`outils_domaines`) et par `_appel_dynamique` (`core/outils_communs.py:75`).
Quand le LLM appelle la capacité `video_resumer` (découverte via le manifest
`synopsis/manifest.json`), le Cœur envoie `POST /resumer` sur ce client 30 s. Or le
pipeline synopsis (transcript YouTube → chunking → LLM par chunk → fusion LLM)
tourne facilement 50 s, parfois plusieurs minutes sur une vidéo longue.
`httpx.ReadTimeout` est attrapé par `except httpx.HTTPError`
(`core/outils.py:463`) → l'assistant renvoie « Brique injoignable » à l'utilisateur.

Le test direct sur le HP le confirme : `POST /resumer` d'une vidéo YouTube
courte revient en 200 OK en ~53 s (`08:26:14 → 08:27:07`). Synopsis marche ;
seul le câblage Cœur le tue.

`orchestrateur.py` (pipeline usine: ETL → Audit → Génération) résout déjà ce
problème pour l'usine : `POLL_TIMEOUT=900`, `_attendre_termine` poll un
endpoint `{base}/{id}` jusqu'à `statut:"termine"|"erreur"`. `audit/main.py:142`
et `generateur/main.py:242` exposent ce contrat (`202 + {id, statut:"en_cours"}`
puis `GET {base}/{id}`). **S179 généralise ce contrat à TOUTE capacité
déclarée `async:true` dans un manifest** — Synopsis est la première
bénéficiaire, transcription/vidéo/oria pourront l'adopter ensuite sans toucher
au Cœur.

## Décisions validées avec l'utilisateur (2026-07-17)

1. **Motif générique au Cœur** (vs. patch dédié Synopsis) : `async:true` dans
   le manifest suffit — le Cœur détecte et pole automatiquement via
   `_attendre_termine`. Réutilisable aux futures briques longues (transcription
   Whisper, teaser vidéo, etc.).
2. **Persistance SQLite dans le volume existant** `synopsis_clips` (chemin
   `/clips/jobs.db`). Survit au redémarrage du conteneur, permet de relancer un
   job en cours.
3. **Les 3 endpoints Synopsis** (`/resumer`, `/reel`, `/resumer-fichier`)
   deviennent asynchrones. Cohérent — `/reel` peut durer le plus longtemps
   (montage ffmpeg après le résumé).
4. **Approche A — auto-poll Cœur** (vs. B : LLM explicite avec méta-outil
   `job_etat`). Transparent pour l'utilisateur et le LLM qui reçoit
   directement le résumé final comme s'il venait d'un outil synchrone.

## Architecture

```
Utilisateur ─"url YouTube"─► Assistant LLM
                              │ tool_call video_resumer(url, langue)
                              ▼
                          Cœur : _appel_dynamique(cap, args)
                          │ cap.async=true → mode async
                          ▼
POST synopsis:6090/resumer {url, langue}
── 202 {"job_id":"abc","statut":"en_cours","poll_url":"/jobs/abc"}
                          │
                          │ Cœur : ouvre httpx.AsyncClient(timeout=None)
                          │ boucle GET /jobs/abc jusqu'à statut terminal
                          │ deadline = OUTILS_ASYNC_TIMEOUT (défaut 600 s)
                          │
                          ▼                       Synopsis BackgroundTask
                          │                       │ sqlite INSERT jobs(id, statut='en_cours')
                          │                       ▼
                          │                       transcript → chunks → LLM (loop)
                          │                       ▼
                          │                       fusion LLM → UPDATE jobs SET statut='termine', resultat_json=...
                          │                       (ou statut='erreur' sur exception attrapée)
                          ▼
                          Cœur : data.statut='termine' → rend JSON(data.resultat) au LLM
                          ▼
                          Assistant LLM → réponse à l'utilisateur (résumé structuré)
```

## Côté brique Synopsis

### 1. `lib/jobs.py` (nouveauté, ~80 lignes)

DB path `/clips/jobs.db` (volume `synopsis_clips` existant — zéro nouveau
volume). SQLite standard.

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id            TEXT PRIMARY KEY,
  date_creation TEXT NOT NULL,
  type          TEXT NOT NULL,        -- 'resumer' | 'reel' | 'resumer_fichier'
  url           TEXT,                  -- NULL pour resumer_fichier
  langue        TEXT,
  statut        TEXT NOT NULL,         -- 'en_cours' | 'termine' | 'erreur'
  progress_pct  INTEGER DEFAULT 0,    -- 0..100 (approximatif, indicatif)
  resultat_json TEXT,                  -- payload final si statut='termine'
  erreur        TEXT                   -- message si statut='erreur'
);
"""

def init_db() -> None: ...
def creer_job(type, **ctx) -> str: ...      # génère uuid4, INSERT statut='en_cours'
def maj_statut(id, statut, *, resultat=None, erreur=None, progress_pct=None) -> None
def lire_job(id) -> dict | None: ...       # renvoie dict plat
```

Init au démarrage de l'app (avant `uvicorn.run`).

### 2. Endpoints (`main.py`)

Les 3 endpoints POST changent de contrat :

- `POST /resumer` → **202** `{job_id, statut:"en_cours", poll_url:f"/jobs/{job_id}"}`.
  Crée le job, lance `BackgroundTasks.add_task(_pipeline_resumer, job_id, url, langue, modele)`.
- `POST /reel` → **202** `{job_id, statut:"en_cours", poll_url}`.
  Background `_pipeline_reel` : résume d'abord (via `_summarize`), puis lance
  `_highlight_reel` — identique à aujourd'hui mais en arrière-plan.
- `POST /resumer-fichier` → **202** `{job_id, statut:"en_cours", poll_url}`.
  Écrit le contenu uploadé dans `/clips/uploads/{job_id}` (temporaire, supprimé
  par le worker après extraction audio) pour ne pas porter les `bytes` en
  mémoire pendant plusieurs minutes. Le worker lit le fichier, appelle
  `audio.extraire_audio` + `transcribe_client.transcrire_fichier` comme
  aujourd'hui, puis `_run_pipeline`.
- `GET /jobs/{id}` → `{statut, progress_pct?, erreur?, resultat?}`. Transparent
  sur l'erreur : `statut="erreur"` + `erreur` (jamais de 500 pour un job
  échoué). Vue par les clients basta : 200 + `statut` porteur de sens.

**Workers** (en haut de `main.py` ou dans `lib/pipeline.py`) :

```python
def _pipeline_resumer(job_id, url, langue, modele):
    try:
        maj_statut(job_id, "en_cours", progress_pct=10)
        data = _summarize(url, langue, modele)
        maj_statut(job_id, "termine", progress_pct=100,
                   resultat_json=json.dumps(data, ensure_ascii=False))
    except Exception as e:
        logger.exception("pipeline_resumer job=%s", job_id)
        maj_statut(job_id, "erreur", erreur=str(e))
```

Toute exception est **attrapée** et persistée — jamais de crash silencieux du
background. Une vidéo longue (60 min → ~10 chunks × ~50 s LLM → ~10 min)
dépasse le `OUTILS_ASYNC_TIMEOUT` du Cœur : le job continue côté brique, le
Cœur renvoie une erreur honnête « délai dépassé ; job_id=XXX — interroge
`GET /jobs/{id}` plus tard » (l'utilisateur peut relancer avec `?attendre=true`
depuis le front, ou interroger le job plus tard).

### 3. Front (`briques/synopsis/front.html`)

La fonction `lancer(req, msg)` actuelle attend une payload complète en un coup.
On la remplace par :

- `POST` reçoit `{job_id, statut, poll_url}` (202).
- Boucle `GET poll_url` toutes les 2 s côté navigateur.
- Met à jour le spinner avec `progress_pct` quand dispo.
- Affiche `resultat` via `afficher(...)` quand `statut='termine'`.
- Affiche `erreur` (rouge) quand `statut='erreur'`.

~30 lignes de JS, design system inchangé.

### 4. Tests (`test_synopsis.py`)

Mocks de `get_youtube_transcript` et `llm_complete` retournent vite (déjà
existants). S'ajoutent :

- `test_resumer_renvoie_202_avec_job_id` — POST `/resumer` → 202 + `{job_id, poll_url}`.
- `test_job_termine_renvoie_resultat` — après background (mock synchrone via
  patching direct de `BackgroundTasks.add_task` qui exécute immédiatement),
  `GET /jobs/{id}` → `{statut:'termine', resultat:{titre, resume, ...}}`.
- `test_resumer_async_erreur` — mock `get_youtube_transcript` lève
  `ValueError("Vidéo inaccessible")` → `GET /jobs/{id}` → `{statut:'erreur', erreur:"Vidéo inaccessible"}`,
  jamais de crash du background.

Test backward-compat : `/resumer-fichier` avec mock audio nul → 202 + job_id.

## Côté Cœur

### 1. Manifeste — propagation `async`/`poll_chemin`

`core/catalogue.py:80-93` — dans `collecter_capacites`, on propage deux nouveaux
champs lus sur chaque déclaration de capacité :

```python
"async": bool(decl.get("async", False)),
"poll_chemin": decl.get("poll_chemin"),
```

Backward-compatible : toute cap sans `async` reste `async=False` (comportement
S64 inchangé).

### 2. `core/outils_communs._appel_dynamique` — branche async

```python
async def _appel_dynamique(client, cap, args):
    # gate action + POST comme aujourd'hui…
    res = await client.request(...)  # synchrone ou 202
    if not cap.get("async") or res.status_code != 202:
        # chemin S64 inchangé (parse 200, traite 4xx, retourne JSON)
        return ...
    # ── branche async (S179) ──
    body = res.json()
    job_id = body.get("job_id") or body.get("id")
    if not job_id:
        return json.dumps({"ok": False, "message": "202 sans job_id"}, ensure_ascii=False)
    poll_chemin = (cap.get("poll_chemin") or "/jobs/{id}").replace("{id}", job_id)
    poll_url = urljoin(cap["url"], poll_chemin)   # sur la même brique
    deadline = float(os.getenv("OUTILS_ASYNC_TIMEOUT", "600"))
    poll = float(os.getenv("OUTILS_ASYNC_POLL", "5"))
    return await asyncio.wait_for(
        _poll_jusqua_terminaison(poll_url, poll, client_http_headers),
        timeout=deadline,
    )
```

`_poll_jusqua_terminaison` — ouvre son propre `httpx.AsyncClient(timeout=None)`
(reuse les headers `X-Compte-Id` / `X-API-Key` via `_entetes_brique`) :
- Boucle GET tant que `statut='en_cours'`, sleep croissant (2 s, 2, 5, 5, 10, 15… plafonné à 15 s).
- `statut='termine'` → rend `json.dumps(data.get("resultat") or data, ensure_ascii=False)`.
- `statut='erreur'` → rend `json.dumps({"ok": False, "message": data.get("erreur")}, ...)`.
- `asyncio.TimeoutError` (levé par `wait_for`) → message honnête :
  `{"ok": False, "message": "Délai dépassé ({deadline}s). Job toujours en cours ; interroge GET {poll_url} plus tard.", "job_id": job_id}`.

**Pourquoi un second client** : `outils.executer` (`core/outils.py:447`) ouvre
le client partagé à `timeout=30`, conçu pour les outils sync. Le poll async a
besoin d'attentes longues sans timeout par requête — ouvrir un client dédié
évite de perturber le pooling et garde le diff minimal.

### 3. Réglages (env, défauts conservateurs)

- `OUTILS_ASYNC_TIMEOUT=600` (10 min, couvre 95 % des usages synopsis — vidéos
  YouTube jusqu'à ~30 min).
- `OUTILS_ASYNC_POLL=5` (intervalle de base ; amortit jusqu'à 15 s).
- Pas de kill-switch dédié : `CAPACITES_DYNAMIQUES=0` (existant, `outils.py:304`)
  éteint déjà tout — suffisant en cas de régression.

## Tests côté Cœur

`core/test_outils_dynamiques.py` enrichi avec `respx` (déjà présent dans les
dépendances tests `conftest.py`) :

- `test_appel_dynamique_async_termine` — cap `async:true` + `poll_chemin`, mock
  POST → 202 + `job_id`, mock GET `poll_url` → `{statut:'termine', resultat:{...}}`.
  On vérifie le rendu JSON attendu par le LLM.
- `test_appel_dynamique_async_erreur` — mock GET → `{statut:'erreur', erreur:'X'}`
  → rend JSON `ok:false`.
- `test_appel_dynamique_async_timeout` — mock GET perpétuel `en_cours` +
  `OUTILS_ASYNC_TIMEOUT=0.1` → rend message `"délai... job_id=abc"` + le job_id.
- `test_appel_dynamique_async_sans_job_id` — 202 sans `job_id` → message honnête.
- `test_appel_dynamique_sync_inchange` — cap **sans** `async:true` → comportement
  S64 inchangé (test déjà existant, à garder vert pour anti-régression).

## Effets de bord & migration

- **Cœur** : 0 changement comportement temps que aucune cap ne déclare
  `async:true`. Activé au premier `briques/reload` après rebuild synopsis.
- **Autres briques potentiellement impactées plus tard** : transcription
  (Whisper longues notes), vidéo (teaser/enlèvement de portrait), oria
  (indexation). Pourront adopter `async:true` sans toucher au Cœur une seconde
  fois — c'est la valeur du motif générique.
- **HP déploiement** :
  1. Rebuild `workplace/synopsis:1.2.0` (MakefileSynopsis).
  2. Rebuild `core-core-1` (noyau).
  3. `curl -X POST :5000/briques/reload` pour lever le nouveau manifeste.
  4. Volume `synopsis_clips` accueille `jobs.db` — zéro migration.
- **Annulation des jobs en cours** : non gérée en S179 (scop volontairement
  minimal). Un job bloqué reste `en_cours` jusqu'à timeout applicatif côté
  brique (TODO futur : `POST /jobs/{id}/annuler`).

## Out of scope (YAGNI)

- Annulation de job `/cancel` (futur).
- Webhook Cœur → brique (pattern inverse, inutile tant que le Cœur peut poller).
- Persistance du `job_id` dans le fil d'activité (`core/fil_activite.py`) — S179
  garde l'async transparent pour le LLM, on n'expose pas le job_id en surface.
- SSE streaming — incompatible avec function-calling synchrone.

## Critères d'acceptation

1. Une vidéo YouTube courte collée sur l'assistant renvoie un résumé structuré
   complet en moins de 90 s, sans erreur "Brique injoignable".
2. Une vidéo très longue (> 10 min de pipeline) ne tue pas synopsis — l'assistant
   indique honnêtement "délai dépassé, job_id=XXX en cours" au lieu d'une
   erreur 500 muette.
3. `test_synopsis.py` et `test_outils_dynamiques.py` passent à 100 %.
4. Une cap **synchrone** déjà déployée continue à fonctionner sans rien changer
   (anti-régression).