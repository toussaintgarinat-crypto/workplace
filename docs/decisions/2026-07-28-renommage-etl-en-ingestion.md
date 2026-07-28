# Décision — la brique `etl` devient `ingestion`, et ce qui casse en le faisant

- **Date** : 2026-07-28
- **Statut** : ✅ Adopté (S215)
- **Portée** : `briques/etl/` → `briques/ingestion/`, la brique `audit` (seule consommatrice
  déclarée), le Cœur (`core/orchestrateur.py`, `core/cycle_de_vie.py`, `core/proactif.py`,
  `core/classer.py`, `core/conscience.py`, `core/routers/assistant.py`,
  `core/outils_domaines/documents.py`, `core/dashboard.html`), les lanceurs macOS,
  `.env.example`, et les diagrammes `detail/*.excalidraw` + `workplace-mindmap.html`

> **But de ce document** : consigner *pourquoi* un renommage cosmétique a été fait malgré
> son coût, et surtout *les deux choses qui font perdre des données si on les oublie* —
> parce que ni l'une ni l'autre ne se signale au démarrage.

## Le problème

La brique s'appelait `etl` et ne faisait pas d'ETL. Elle extrait du texte de documents non
structurés (PDF, Word, images, HTML) vers SQLite, pour la brique `audit`. Elle ne réplique
aucune table, ne suit aucun curseur, ne planifie rien. Sa `famille` au manifeste disait
déjà `ingestion` — c'est le `nom` qui mentait, et il mentait depuis l'origine.

Ce n'est pas ça qui a déclenché le sprint. Le backlog S210→S215 avait explicitement rangé
ce renommage en **dernier, et sautable** : du churn pour du confort. Ce qui l'a rendu
rentable, c'est **S214** : la brique `connecteurs` (PyAirbyte) fait, elle, un vrai ETL —
extraction depuis des sources, sync incrémentale, état, planification. À partir du moment
où les deux vivent côte à côte dans `briques/`, une brique nommée `etl` qui n'en fait pas
et une brique qui en fait sans le dire coûtent plus cher, en confusion, que le renommage.

## La décision

Renommage complet, **sans couche de compatibilité**, sur cinq surfaces :

| Surface | Avant | Après |
|---|---|---|
| Dossier, `nom`, `role` | `etl` | `ingestion` |
| Capacités du manifeste | `etl_ingerer_url`, `etl_documents_lister`, `etl_supprimer_document` | `ingestion_*` |
| Docker | service/image/conteneur `etl`, volume `etl_data` | `ingestion`, `ingestion_data` |
| Base SQLite | `/data/etl.db` | `/data/ingestion.db` |
| Variables d'env | `ETL_URL`, `ETL_KEY`, `ETL_API_KEYS`, `ETL_EXTRACTIONS_PARALLELES` | `INGESTION_*` |

Le port (**5200**) et tous les chemins d'API (`/ingerer`, `/documents`, `/dossiers`…) sont
**inchangés** : le renommage ne touche pas le contrat HTTP, seulement les noms autour.

## Les deux pièges, et pourquoi ils sont muets

**1. Le volume Docker change de nom, donc il est vide.** Le nom de projet Compose vient du
nom du dossier : `etl_etl_data` devient `ingestion_ingestion_data`. Un `docker compose up`
sur le nouveau compose ne récupère pas l'ancien volume, il en **crée un neuf**. La brique
démarre parfaitement, le healthcheck passe, `/sante` répond `documents_ingeres: 0`. Rien
n'est en erreur — les documents sont simplement dans un volume que plus personne ne monte.

→ `scripts/migration_etl_vers_ingestion.sh` recopie l'un dans l'autre. **Avant** le premier
`up`, sur toute machine où `etl` tournait déjà (le HP). Il refuse d'écraser une base
`ingestion.db` non vide, et **laisse l'ancien volume en place** : c'est le retour arrière.

**2. Le fichier change de nom dans le volume.** Même une fois le volume recopié, la base
s'appelle encore `etl.db` et le code ouvre `ingestion.db` — donc `sqlite3.connect` crée
sagement une base **vide à côté**, sans une ligne de log. `stockage.reprendre_base_heritee()`,
appelée au démarrage, renomme le fichier si le nouveau nom n'existe pas encore.

Les deux sont nécessaires et aucun ne remplace l'autre : le script fait traverser deux
volumes au fichier, la reprise le renomme dans le volume. Preuve de la seconde :
`briques/ingestion/test_reprise_base_heritee.py` (4 cas, dont un démarrage complet par
`TestClient` et le cas « les deux fichiers coexistent » où la base en service gagne).

## Ce qu'on a refusé : le repli sur les anciennes variables

La tentation était d'écrire `os.getenv("INGESTION_API_KEYS") or os.getenv("ETL_API_KEYS")`
pour qu'un `.env` non mis à jour continue de marcher. **Refusé**, et c'est le point le moins
évident du sprint.

Un repli sur `ETL_API_KEYS` ne « continue pas de marcher » à moitié : il maintient une
brique **fermée** avec une variable dont plus rien dans le dépôt ne parle. Six mois plus
tard, quelqu'un nettoie le `.env` de la ligne `ETL_API_KEYS` qui ne correspond à rien, et
rouvre la brique sans le savoir. Le repli déplace la panne dans le temps au lieu de
l'éviter — il la rend juste plus difficile à relier à sa cause.

Sans repli, le mode de panne est différent : entre le `git pull` et l'édition du `.env`, la
brique est **ouverte** (comportement historique d'un déploiement non configuré) — dommage
borné, réseau Docker seulement, garde SSRF de S211 toujours en place. C'est un risque court
et connu plutôt qu'un piège durable et invisible. **Le `.env` se renomme dans la même
opération que le pull**, c'est écrit dans `.env.example` et dans le journal de `WORKPLACE.md`.

## Ce qu'on a laissé tel quel, assumé

- **Les entrées datées du journal de `WORKPLACE.md`** et les rapports de sprint archivés
  disent toujours « brique ETL ». C'est un compte-rendu de ce qui s'est passé à l'époque :
  le réécrire serait falsifier un historique, pas le mettre à jour. Seule la prose qui
  décrit le fonctionnement **actuel** a été renommée.
- **Le mot « ETL » comme concept** dans `detail/forge.excalidraw` a été reformulé, mais on
  ne s'interdit pas le terme : il redevient juste pour parler de `connecteurs`.

## À quelle condition on serait revenu en arrière

Si la reprise des documents déjà ingérés s'était avérée impossible à prouver, le renommage
n'aurait pas valu son coût — c'est du confort, et aucun confort ne justifie de perdre le
contenu extrait de documents qu'on n'a plus forcément sous la main. La reprise est prouvée
par test avant tout déploiement, donc la question ne se pose plus.
