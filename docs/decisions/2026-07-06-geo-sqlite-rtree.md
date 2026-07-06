# Décision — Brique geo (GeoHub) : SQLite + R*Tree plutôt que PostGIS

- **Date** : 2026-07-06
- **Statut** : ✅ Adopté (S156→S159)
- **Portée** : brique `geo` (port 6110) — stockage et index spatial des objets géolocalisés
- **Fichiers liés** : `briques/geo/stockage.py`, `briques/geo/domaine.py`, `briques/geo/manifest.json`

> **But de ce document** : consigner *pourquoi* la carte de veille tourne sur SQLite et
> non PostGIS (comme le proposait le cahier des charges GeoHub initial), et surtout
> **quand** ce choix devra être remis en cause.

---

## En bref (l'état actuel)

- Un seul fichier `geo.db` (SQLite, WAL), motif identique aux autres briques (mail, paiements).
- Table générique `geo_objects` (type + `metadata` JSON — polymorphe sans migration) +
  table virtuelle **R*Tree** synchronisée par **triggers** (points = boîtes dégénérées).
- Recherche par bounding box = JOIN sur le R*Tree ; filtres métier via `json_extract` (json1).
- Zéro service supplémentaire, tests offline en millisecondes, mock honnête par défaut.

## Contexte & objectif

Le cahier des charges GeoHub recommandait PostgreSQL + PostGIS d'entrée. Mais la v1
(veille de créations d'entreprises sur quelques zones) manipule des **milliers** de
points, pas des millions, et n'a besoin que de requêtes par rectangle (la carte Leaflet
envoie sa bbox à chaque `moveend`). Le R*Tree de SQLite couvre exactement ce besoin,
en restant fidèle au motif « brique autonome, un fichier, testable hors-ligne ».

## Décision

SQLite + extension R*Tree (compilée par défaut dans le sqlite3 de Python, gardée par le
test `test_module_rtree_disponible`). Fraîcheur recalculée à la lecture (jamais stockée),
règles par type dans `domaine.py::REGLES_FRAICHEUR`.

## Alternatives considérées & quand basculer

| Approche | Coût | Complexité | Bon quand… |
|---|---|---|---|
| SQLite + R*Tree (choisi) | 0 | faible | bbox sur ≤ quelques centaines de milliers de points |
| PostgreSQL + PostGIS | 1 conteneur + volume | moyenne | vraies géométries, gros volumes, concurrence |

**Déclencheurs de bascule vers PostGIS** (l'un suffit) :
1. **> ~500 000 objets par tenant** (ingestion Sirene massive, France entière) ;
2. besoin de **vraies géométries** : polygones (zones non rectangulaires), distance
   métrique exacte, jointures spatiales, isochrones ;
3. **écritures concurrentes multi-processus** soutenues (SQLite sérialise) ;
4. une **2e brique** doit consommer la même base spatiale.

La migration est bornée : `stockage.py` est la seule couche SQL, le modèle
`geo_objects`/`metadata` JSONB se transpose tel quel, l'API ne change pas.

## Runbooks

### A. Vérifier que le R*Tree est disponible (nouvelle machine/image)
```bash
python3 -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE t USING rtree(id,a,b)'); print('rtree OK')"
```

### B. Reconstruire l'index spatial (si suspicion de désynchronisation)
```sql
DELETE FROM geo_rtree;
INSERT INTO geo_rtree SELECT rowid, latitude, latitude, longitude, longitude FROM geo_objects;
```

## Limites connues

- bbox rectangulaire ≠ rayon exact (le « rayon » d'une zone est converti en boîte englobante) ;
- pas de projection : approximation sphérique 111 km/degré (suffisant pour la veille) ;
- comparaisons de dates en chaînes ISO (une date « AAAA-MM-JJ » nue est normalisée UTC).

## Décision liée : enrichissement emails DIFFÉRÉ (RGPD)

Le cahier des charges demandait un module de scraping emails/sites. L'API Sirene ne
fournit pas les emails **exprès** (RGPD) ; les moissonner en masse recréerait le
problème. Choix : v1 SANS enrichissement ; un sprint futur pourra ajouter un
enrichissement **opt-in, à la demande (jamais en masse), sourcé** (site officiel de
l'entreprise) **et journalisé**.

## Références

- `briques/geo/README.md`
- `tests/test_briques_smoke.py` (contrat manifest)
- Cahier des charges GeoHub (conversation du 2026-07-06)
