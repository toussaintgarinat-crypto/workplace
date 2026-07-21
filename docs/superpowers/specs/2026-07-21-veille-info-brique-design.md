# Design — Brique `veille-info` (2e sous-brique de la famille « veille »)

**Date** : 2026-07-21
**Statut** : validé, prêt pour plan d'implémentation

## Contexte

Suite de la décision d'architecture « veille parente + sous-briques togglables »
(mémoire `veille-brique-parente-sous-briques`). Premier palier déjà livré (commits
`35b6ebc`+`97227d4`, poussés `origin/main`) : famille de manifest `veille` (🔭) créée dans
`core/familles.py`, `briques/geo` rattachée à cette famille sans aucun changement de son
code fonctionnel.

Ce spec couvre la **2e sous-brique** : la veille informationnelle (RSS multi-sources →
agrégation → résumé quotidien). Aujourd'hui, ce besoin n'existe que sous forme basique dans
`briques/forge/forge/core/app/routers/veille.py` : CRUD sources/articles + fetch RSS manuel
(parser regex), sans planification automatique ni résumé ni audio.

Clarifications actées avec l'utilisateur :
- **Le code Forge reste inchangé** — pas de suppression, pas de migration, pas de partage de
  code entre les deux. La nouvelle brique est un service complètement indépendant avec sa
  propre implémentation RSS (les deux coexistent, c'est assumé).
- **Déclenchement automatique quotidien** via le mécanisme générique déjà existant du Cœur
  (`core/horloge.py`, S29 : chaque brique déclare ses tâches périodiques dans son
  `manifest.json`, champ `taches` ; l'horloge du Cœur les découvre et les appelle sur leur
  `cadence_heures`). C'est exactement le motif déjà utilisé par `geo` pour sa veille nocturne
  (`ingestion-quotidienne`, cadence 24h) — aucune nouvelle mécanique de planification à
  inventer.
- **Périmètre de ce spec : fetch + résumé texte seulement.** Pas de génération audio — ce
  sera un spec séparé, une fois le texte du digest quotidien validé. La brique `voix` (5985)
  expose déjà `POST /rendre` (segments texte→MP3 concaténé, persisté, retourne
  `{url, duree, episode_id}`) : le futur spec audio n'aura qu'à lui passer le texte du
  digest, sans dupliquer de code TTS.
- **Nom retenu : `veille-info`** (dossier `briques/veille-info/`, port `6120` — premier port
  libre après `geo` à `6110`) — distingue explicitement le nom de LA brique du nom de LA
  FAMILLE dashboard (`veille`), qui elle regroupe plusieurs briques (`geo` + `veille-info`).

## État constaté du code (vérifié, pas supposé)

- `core/horloge.py` (S29) est déjà générique : ne code AUCUNE tâche métier en dur, découvre
  les tâches via `registre` (manifests scannés) et les déclenche par HTTP quand dues. Contrat
  exact d'une entrée `taches` (déjà utilisé par `briques/geo/manifest.json`) :
  ```json
  {
    "nom": "digest-quotidien",
    "description": "Fetch RSS + résumé consolidé du jour pour chaque personne ayant des sources actives.",
    "methode": "POST",
    "chemin": "/digest/executer",
    "cadence_heures": 24,
    "idempotent": true,
    "entete_token_env": "VEILLE_INFO_KEY",
    "tolere_echec": true
  }
  ```
- `briques/synopsis/lib/llm_client.py` est le motif standard d'appel LLM d'une brique
  autonome : priorité `GATEWAY_URL`/`GATEWAY_KEY` (LiteLLM du Cœur, `/v1/chat/completions`
  compatible OpenAI), repli `OPENROUTER_API_KEY` puis `OPENCODE_GO_API_KEY`, modèle par
  défaut `deepseek/deepseek-v4-flash` (env `LLM_MODEL`). `veille-info` réplique ce fichier
  (chaque brique duplique sa propre petite lib client — convention du monorepo, pas de
  package partagé entre conteneurs de briques, seul `core/` importe `shared/`).
- `briques/voix/main.py:205` (`POST /rendre`) confirmé comme le point d'entrée pour un futur
  spec audio — hors périmètre ici, juste noté pour ne pas le redécouvrir plus tard.
- Isolation par personne : motif `X-User-Id` (header, défaut `"perso"`) déjà en place dans
  `briques/mail/main.py:46-67` et généralisé aux briques S182-S187 (mail/mémoire/écoute/
  studio) — `veille-info` suit ce motif dès sa création (pas de dette d'isolation à rattraper
  plus tard comme ce fut le cas pour les briques plus anciennes, cf. `docs/rapport-s183-audit-isolation.md`).
- Port `6120` confirmé libre (tous les manifests scannés, le plus haut port métier actuel est
  `6110` pour `geo`).

## Architecture

Service FastAPI autonome, comme toutes les briques du monorepo : son propre
`Dockerfile`/`docker-compose.yml`/`manifest.json`/`requirements.txt`, aucune dépendance de
code vers Forge ou vers une autre brique (seuls les appels HTTP vers la Gateway et,
plus tard, vers `voix`, existent). Stockage SQLite local (fichier
`/data/veille-info/veille_info.db` en conteneur, cf. convention `mail`/`geo`), pas de
Postgres — volume trop faible pour le justifier.

## Modèle de données (SQLite)

```sql
CREATE TABLE sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    nom TEXT NOT NULL,
    url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    titre TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, url)
);

CREATE TABLE digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,           -- "YYYY-MM-DD", clé d'idempotence avec user_id
    texte_resume TEXT NOT NULL,
    nb_articles INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, date)
);
```

`UNIQUE(user_id, date)` sur `digests` porte l'idempotence : la tâche horloge peut être
rappelée plusieurs fois le même jour (retry, redémarrage) sans produire de doublon — un
digest déjà présent pour `(user_id, date du jour)` fait sauter cet utilisateur, silencieusement
(pas une erreur).

## Pipeline quotidien (`POST /digest/executer`)

Appelé par l'horloge du Cœur (voir `taches` ci-dessus), ou manuellement pour tester. Ne prend
aucun paramètre (contrairement aux endpoints normaux de la brique, il traite TOUS les
utilisateurs connus — même motif que `geo`'s `ingestion-quotidienne`, qui elle aussi ne
segmente pas par appelant) :

1. `SELECT DISTINCT user_id FROM sources WHERE enabled = 1`
2. Pour chaque `user_id` :
   a. Si un digest existe déjà pour `(user_id, aujourd'hui)` → passer au suivant (idempotence).
   b. Pour chaque source active de cet utilisateur : fetch RSS (timeout 10s, `httpx`,
      `User-Agent: VeilleInfo/1.0`), parser les `<item>` (regex, même logique que celle
      déjà éprouvée dans `briques/forge/forge/core/app/routers/veille.py` — réécrite dans
      cette brique, PAS importée), insérer les nouveaux articles (`INSERT OR IGNORE`, la
      contrainte `UNIQUE(user_id, url)` dédoublonne). Une source dont le fetch échoue
      (timeout, 404, XML invalide) est journalisée et ignorée — ne bloque pas les autres
      sources de l'utilisateur.
   c. S'il n'y a AUCUN nouvel article pour cet utilisateur aujourd'hui → ne pas créer de
      digest, passer au suivant (pas de résumé vide).
   d. Sinon : construire un prompt listant titre+URL+source de chaque nouvel article, un
      seul appel LLM via `lib/llm_client.py` (température basse, ~0.3, motif synopsis) pour
      produire un résumé consolidé en français. Si l'appel LLM échoue (Gateway indisponible) :
      journaliser l'échec, NE PAS créer de digest partiel — l'utilisateur sera re-tenté au
      prochain passage de l'horloge (24h) ou peut relancer `/digest/executer` à la main.
   e. Insérer le digest `(user_id, date=aujourd'hui, texte_resume, nb_articles)`.
3. Répond `{"utilisateurs_traites": N, "digests_crees": M}` (compte agrégé, pas de détail par
   utilisateur — cohérent avec le fait que l'appelant est l'horloge, pas un humain).

## API + capacités assistant

Toutes protégées par `X-User-Id` (isolation) sauf `/digest/executer` (appelé par l'horloge
via `entete_token_env: VEILLE_INFO_KEY`, traite tous les utilisateurs — cf. pipeline
ci-dessus) et `/sante` (santé, sans auth, comme toutes les briques).

| Capacité | Méthode | Chemin | Action | Niveau |
|---|---|---|---|---|
| `veille_info_sources_lister` | GET | `/sources` | non | 0 |
| `veille_info_source_ajouter` | POST | `/sources` | oui | 1 |
| `veille_info_source_supprimer` | DELETE | `/sources/{id}` | oui | 1 |
| `veille_info_digests_lister` | GET | `/digests` | non | 0 |
| `veille_info_digest_lire` | GET | `/digests/{id}` | non | 0 |

(`action`/`niveau` calqués sur `geo_zone_ajouter`/`geo_zone_supprimer` — créer/supprimer une
source de veille est de la même famille de geste que créer/supprimer une zone surveillée.)

`POST /digest/executer` n'est PAS une capacité assistant (pas dans `capacites` du manifest) —
c'est une route interne appelée par l'horloge, comme `geo`'s `/ingestion/executer` qui n'est
pas non plus exposée à l'assistant.

`manifest.json` : `"famille": "veille"`, `"port": 6120`, entrée `taches` (contrat ci-dessus),
`depends_on: []` (aucune dépendance dure — la Gateway est appelée en best-effort, comme
`summarisation.py` du Cœur : tout échec dégrade proprement, jamais de crash).

## Erreurs / dégradation

- Gateway indisponible → pas de digest ce jour pour l'utilisateur concerné, retry au
  prochain passage horloge (24h) ou manuel. Jamais de digest à moitié rempli.
- Source RSS injoignable/malformée → ignorée pour ce passage, les autres sources de
  l'utilisateur continuent d'être traitées normalement.
- Aucun nouvel article → pas de digest créé (comportement normal, pas une erreur).

## Tests

`briques/veille-info/conftest.py` (isolation entre tests, même motif que les autres briques)
+ `test_veille_info.py` :
- CRUD sources (créer/lister/supprimer, isolation par `user_id` — un utilisateur ne voit pas
  les sources d'un autre).
- Parsing RSS : items valides/invalides, dédup par URL.
- Pipeline `/digest/executer` : mock `httpx` (RSS fetch) + mock de l'appel Gateway (aucun
  réseau réel, comme les briques existantes qui testent contre des fournisseurs externes) —
  vérifie idempotence (2 appels le même jour → 1 seul digest), dégradation propre (Gateway en
  échec → pas de digest créé), aucun nouvel article → pas de digest créé.

## Hors périmètre (explicitement)

- Génération audio du digest (appel à `POST /rendre` de la brique `voix`) — spec séparé.
- Toute modification du code RSS existant dans Forge — laissé tel quel.
- Résumé par article individuel (seul le résumé consolidé quotidien existe).
- Import de sources depuis Forge (pas de migration de données).
