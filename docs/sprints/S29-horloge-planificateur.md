# S29 — Brique `horloge` (planificateur)

> **Objectif** : un planificateur fidèle au modèle **noyau + briques** qui exécute
> les **tâches périodiques déclarées par les briques** (contrat manifest : *quoi*,
> *quand*, *idempotence*). Premiers branchements : **relances J+7/15/30** (S22) et
> **sync Google Agenda** (S27, pull périodique). **Prérequis de S30** (briefing).

**Statut : ✅ LIVRÉ + PROUVÉ LIVE (dev) le 2026-06-10.**

## Le choix d'architecture

Le backlog offrait deux voies (« une petite brique *ou* un module du Cœur étendant
`proactif.py` »). Voie retenue : **un module du Cœur** (`core/horloge.py`), frère de
`proactif.py`. Raison : `proactif.py` fournit déjà le motif (boucle asyncio + journal
SQLite side-car, sans Redis ni broker), et le Cœur a déjà l'accès au registre et la
résolution d'URL des briques (`orchestrateur._brique_base`). Faire une brique Docker
séparée aurait dupliqué cette infra pour zéro gain — l'innovation n'est pas le process,
c'est **le contrat dans le manifest**, préservé dans les deux cas.

Répartition des responsabilités :
- l'**idempotence métier** reste à la brique (relances anti-doublon facture×niveau S22,
  pull Google idempotent S27) ;
- l'**horloge** garantit seulement qu'une tâche n'est pas redéclenchée avant que sa
  `cadence_heures` soit écoulée — et journalise chaque exécution (statut + résultat).

## Le contrat (champ `taches` du `manifest.json`)

Le Cœur ne code en dur **aucune** tâche. Chaque brique déclare les siennes :

```json
"taches": [
  {
    "nom": "relances-impayes",
    "description": "…",
    "methode": "POST",                 // verbe HTTP (défaut POST)
    "chemin": "/relances/executer",     // relatif à la base de la brique
    "cadence_heures": 24,               // période minimale entre deux exécutions
    "idempotent": true,                 // documentaire : la brique dédoublonne
    "entetes": {"X-User-Id": "perso"},  // en-têtes statiques (optionnel, non secret)
    "entete_token_env": "CALENDAR_SERVICE_TOKEN",  // nom d'env → Authorization: Bearer
    "tolere_echec": true                // un 4xx/5xx attendu n'est pas une alarme
  }
]
```

Le secret du Bearer **n'est jamais dans le manifest** : seul le *nom* de la variable
d'environnement y figure (`entete_token_env`), la valeur reste dans l'env du Cœur.

## Livré

| Élément | Détail |
|---|---|
| `core/horloge.py` | Découverte (`collecter_taches`), cadence pure (`tache_due`), exécution tolérante (`run_due`), état (`lister_etat`), boucle de fond (`boucle`). Journal SQLite `horloge_journal` (par `brique×tache` : dernière exécution, statut, résultat tronqué, nb d'exécutions). |
| `core/main.py` | `horloge.boucle` démarrée dans le `lifespan` (tick toutes les 15 min) ; `GET /horloge/taches`, `POST /horloge/executer` (`?forcer=`, `?brique=`, `?tache=`). |
| `briques/forge/manifest.json` | Tâche `relances-impayes` → `POST /relances/executer`, cadence 24 h. |
| `briques/agenda/manifest.json` | Tâche `sync-google` → `POST /google/sync`, cadence 6 h, `X-User-Id: perso` + `CALENDAR_SERVICE_TOKEN`, `tolere_echec`. |
| `core/test_horloge.py` | **7 tests verts** (httpx simulé, journal isolé) : cadence pure, collecte/normalisation des manifests, ignore les déclarations incomplètes, Bearer depuis l'env, exécution puis respect de la cadence, `forcer`, `tolere_echec` avance l'horloge, calcul de `prochaine_echeance`. |

## Preuve LIVE (dev) — 2026-06-10

Cœur rebuildé (`docker compose up -d --build`), 10 briques chargées.

1. **Découverte par manifest** — `GET /horloge/taches` renvoie les **2 tâches**
   (`agenda/sync-google` 6 h, `forge/relances-impayes` 24 h) : aucune n'est codée
   dans le Cœur, toutes lues dans les manifests montés.
2. **Déclenchement** — `POST /horloge/executer` :
   - `forge/relances-impayes` → **HTTP 200** : le vrai moteur de relances a tourné
     (`{"nb_envoyees":0,"message":"0 relance(s) … 0 € d'impayés"}` — rien d'échu, donc
     **pas de spam**, comportement attendu). Auth M2M `forge-service` côté adaptateur.
   - `agenda/sync-google` → **HTTP 400** `« Aucun compte Google connecté pour cet
     utilisateur »` → statut **`ignore`** (toléré) : le câblage périodique fonctionne ;
     le pull s'exécutera dès que `perso` sera le compte Google connecté.
3. **Anti-matraquage** — 2ᵉ `POST /horloge/executer` immédiat : **0 exécutée**, les
   deux **sautées** (cadence pas écoulée). `prochaine_echeance` = +24 h / +6 h.

## Limites assumées (héritées, pas des bugs de S29)

- **Identité** : les relances tournent sous le `sub` du token de service `forge-service`
  (dette identité Forge S20, déjà tracée) — à propager au vrai `user_id` avant un 2ᵉ
  utilisateur réel.
- **Agenda mono-utilisateur** : la tâche cible `X-User-Id: perso`. Le compte Google
  connecté en S27 l'avait été sous une autre identité → 400 toléré ici. Un « sync all
  connected users » côté brique agenda serait l'évolution naturelle.

## Débloque S30

`lister_etat()` et le déclencheur `horloge` sont la base du **briefing quotidien** :
S30 ajoutera des coroutines dans `proactif.CHECKS` (RDV, impayés J-proches, pipeline,
coût LLM) et une synthèse, déclenchées chaque matin par une tâche `horloge`.
