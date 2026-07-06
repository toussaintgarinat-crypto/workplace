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

## Tests

```bash
cd briques/geo && python3 -m pytest -q
```

Hors-ligne : DB temporaire, fournisseur mock, aucun appel réseau.
