# PyAirbyte vit dans un venv isolé, joint en sous-processus

- **Date** : 2026-07-28
- **Statut** : accepté
- **Sprint** : S214 (brique `connecteurs`)
- **Prolonge** : `docs/sprints/S210-S215-etl-connecteurs-app-builder.md` § S214

## Contexte

S214 avait déjà tranché le gros morceau : **on ne déploie pas la plateforme Airbyte**
(cluster k8s via `abctl`, Temporal, ~8 Go de RAM, pile Java, et surtout la double licence
MIT/**ELv2** qui interdit l'offre en service managé — incompatible avec l'épopée « bundles
solutions par client »). On prend **PyAirbyte**, la bibliothèque MIT, décrite dans le
backlog comme « une simple librairie Python, sans plateforme ».

**Cette prémisse est fausse**, et c'est ce qui a motivé cet ADR. Vérification faite avant
d'écrire la moindre ligne de la brique :

```
$ pip install --dry-run 'airbyte==0.53.2' 'fastapi==0.115.6' 'starlette==0.41.3' 'pydantic==2.9.2'
ERROR: Cannot install airbyte, airbyte==0.53.2, fastapi==0.115.6 and pydantic==2.9.2
       because these package versions have conflicting dependencies.
ERROR: ResolutionImpossible
```

`airbyte` tire `fastmcp>=3` → `fastmcp-slim[client,server]` → **`starlette>=1.0.1`** et
**`pydantic>=2.11.7`**. `constraints-workplace.txt` (S117/S205) fige `fastapi==0.115.6`
(donc `starlette>=0.40,<0.42`) et `pydantic==2.9.2`. Ce n'est pas un plafond qu'on peut
relever au passage : ce sont les versions que portent 16 et 2 composants du parc.

Toutes les versions de PyAirbyte ≥ 0.30 traînent `fastmcp`. La 0.20.0 y échappe, mais au
prix d'un `airbyte-cdk` 5.x — figer une librairie deux ans en arrière pour éviter un
conflit de packaging n'est pas un choix, c'est une dette déguisée.

Poids constaté, à titre d'information : `pip install airbyte` seul rend **703 Mo** de
`site-packages` (pyarrow 50 Mo, duckdb 21 Mo, numpy 17 Mo, pandas 11 Mo, plus
snowflake-connector, google-cloud-bigquery, psycopg2 — PyAirbyte embarque *tous* ses
backends de cache). C'est une lib grasse, pas une lib mince.

## Options

1. **Rétrograder PyAirbyte à 0.20.0** — supprime le conflit, gèle le CDK deux ans en
   arrière. Rejetée.
2. **Relever `constraints-workplace.txt` vers `starlette>=1.0.1` / `pydantic>=2.11.7`** —
   ferait migrer FastAPI sur 38 briques pour le confort d'une seule. Le fichier de
   contraintes existe précisément pour empêcher ça. Rejetée.
3. **Abandonner PyAirbyte et parler le protocole Airbyte en direct** (`spec` / `check` /
   `discover` / `read --state` sur les connecteurs, qui sont des exécutables PyPI) —
   image ~150 Mo, zéro conflit, mais ~300 lignes à écrire et à maintenir contre une spec
   tierce, dont la gestion d'état, qui est la partie subtile. Écartée pour ce sprint, mais
   c'est le repli si la cloison devient coûteuse.
4. **Isoler PyAirbyte dans son propre venv, le joindre en sous-processus.** Retenue.

## Décision

Une image, **deux environnements Python** :

- `/opt/pyairbyte` — `airbyte==0.53.2` et ses ~700 Mo. Créé par `python -m venv` **sans**
  `--system-site-packages` : la cloison doit être étanche, sinon la brique importerait le
  `pydantic` de PyAirbyte et l'API tomberait au démarrage.
- le venv système — l'API FastAPI, installée `-c constraints-workplace.txt` comme le reste
  du parc.

Ils ne se parlent que par un contrat pauvre (`briques/connecteurs/pont.py` ↔
`briques/connecteurs/pont/executer.py`) : un objet JSON sur stdin, **une** ligne JSON sur
stdout, tout le reste sur stderr.

**Image `python:3.11-slim`, pas 3.12** : `airbyte` exige `<3.13`, mais surtout plusieurs
connecteurs publiés sur PyPI exigent `<3.12` (`airbyte-source-stripe`,
`airbyte-source-declarative-manifest` au 2026-07-28). Une image 3.12 leur fermerait la
porte sans le dire.

## Conséquences

**La cloison rend deux services qu'on aurait dû construire de toute façon.**

- *La boucle d'événements ne bloque jamais.* Une sync de plusieurs minutes tourne dans un
  processus séparé, attendue en asyncio ; `/sante` répond pendant ce temps. C'est
  exactement le défaut que S212 a corrigé sur `etl`, où l'OCR faisait tomber le healthcheck
  — ici il ne peut pas se produire par construction.
- *Un connecteur tiers qui plante n'emporte pas la brique.* Les connecteurs Airbyte sont du
  code tiers ; un segfault ou une fuite mémoire reste de l'autre côté.

**Le prix.**

- **1,32 Go d'image** (mesuré, `docker images workplace/connecteurs:0.1.0`) — les 703 Mo de
  `site-packages` plus la base et les métadonnées de venv. C'est de loin la plus grosse
  image du parc. Sur un HP 800 G4 qui héberge déjà ~54 conteneurs, c'est du **disque**, pas
  de la RAM : la couche n'est chargée que dans le sous-processus, et seulement pendant une
  sync — `/sante` mesuré à 2-3 ms *pendant* un transfert.
- Tout passe par du JSON. Peu coûteux, mais réel : pas d'objet PyAirbyte côté API.
- **Piège dicté par la cloison** : PyAirbyte écrit ses barres de progression `rich` sur
  *stdout*. Un protocole JSON sur stdout serait corrompu par la librairie elle-même, de
  façon **intermittente** (selon tty, selon la durée). `pont/executer.py` duplique donc le
  vrai stdout **avant** d'importer `airbyte`, puis branche le descripteur 1 sur stderr.
  Tenu par `test_pont.py::test_le_bruit_de_pyairbyte_ne_corrompt_pas_le_protocole`.

**Condition d'un retour en arrière** : si la cloison devient coûteuse à maintenir (contrat
qui s'épaissit, API PyAirbyte qu'on n'atteint plus), l'option 3 — le protocole Airbyte en
direct — redevient la bonne, et fait tomber l'image à ~150 Mo.

## Ce qui reste ouvert

Le critère de sortie du sprint (« deux syncs de suite ne retransfèrent que le delta ») n'est
**pas** déclaré atteint. La brique capte le curseur, le recopie dans SQLite et PyAirbyte le
repasse bien au connecteur (fichier `--state` non vide, vérifié) — mais la *réduction* du
volume est une propriété du **connecteur**. Deux connecteurs sans identifiants ont été
mesurés le 2026-07-28 et ne la présentent pas : `source-faker` écrit son curseur et
l'ignore en entrée ; un manifeste déclaratif écrit à la main repart de `start_datetime`.
La preuve du delta demande un connecteur qui l'implémente (`source-github` avec un jeton),
à faire LIVE. Voir le doc de sprint.

## Références

- `briques/connecteurs/pont.py` — côté API de la cloison
- `briques/connecteurs/pont/executer.py` — côté PyAirbyte
- `briques/connecteurs/requirements.txt` — pourquoi `airbyte` n'y est pas
- `constraints-workplace.txt` — les versions du parc
- `docs/decisions/2026-07-28-contrat-manifeste-route.md` (S210) — le filet que respectent
  les 6 capacités de cette brique
