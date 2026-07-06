# Brique geo — GeoHub cartographique

Cartographie modulaire multi-tenant (port **6110**) : affiche, filtre et surveille
n'importe quel objet géolocalisé. Premier cas d'usage : la veille de créations
d'entreprises (prospection). Architecture agnostique au type — immobilier, événements,
objets de jeu s'ajoutent sans migration (modèle générique `geo_objects` + `metadata` JSON).

## Modèle

- `geo_objects` : socle commun (id, tenant, type, latitude, longitude, `date_reference`
  métier, source, ref_externe, metadata JSON). Index spatial **SQLite R*Tree** synchronisé
  par triggers (pas de PostGIS en v1 — voir l'ADR `docs/decisions/2026-07-06-geo-sqlite-rtree.md`).
- Pastilles de **fraîcheur** calculées côté serveur, par type (entreprise : 🔴 <30 j,
  🟠 <90 j, 🔵 sinon) — règles dans `domaine.py::REGLES_FRAICHEUR`.

## API

- `GET /sante`, `GET /config` (mode honnête : mock ou réel)
- `GET /objets?bbox=lat_min,lon_min,lat_max,lon_max&type=&fraicheur=&naf=&q=&limite=`
- `POST /objets` (épingle manuelle)

Auth multi-tenant : header `X-API-Key` (ou Bearer) → tenant = empreinte sha256. Fail-closed
si `API_KEYS` est défini au `.env` racine ; sinon espace « public » (dev).

## Veille (zones + ingestion)

- `GET/POST /zones`, `DELETE /zones/{id}` : zones surveillées (bbox ou centre+rayon).
- `POST /ingestion/executer` : passe de veille (fournisseur → upsert par SIREN) ; déclenchée
  chaque nuit par l'horloge du Cœur (tâche `ingestion-quotidienne` du manifest, Bearer `GEO_KEY`).
- `GET /nouveautes?jours=` : les découvertes récentes ; push 🗺️ Telegram best-effort
  (brique connexion) quand la veille trouve du neuf.
- Fournisseurs : **Mock honnête** par défaut (déterministe, étiqueté `simule`) ;
  `GEO_FOURNISSEUR=reel` → recherche-entreprises.api.gouv.fr (Sirene public, sans clé).

## Front

`GET /` : carte Leaflet **vendorée** (zéro CDN) — fonds OSM + Plan IGN + ortho
(Géoplateforme WMTS sans clé), rafraîchissement par bbox au déplacement, pastilles
calculées serveur, filtres, recherche de commune (BAN). Embarquée dans l'onglet
« Carte » du dashboard du Cœur (mesh : port 16110 via Caddy).

## Capacités assistant

6 outils auto-découverts via le manifest : `geo_chercher`, `geo_nouveautes` (niveau 0),
`geo_zones_lister`, `geo_zone_ajouter`, `geo_objet_ajouter`, `geo_ingestion_lancer`
(niveau 1, actions gardées par confirmation).

## Tests

```bash
cd briques/geo && python3 -m pytest -q
```

Hors-ligne : DB temporaire, fournisseur mock, aucun appel réseau.
