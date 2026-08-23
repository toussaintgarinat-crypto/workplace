# world-engine — Génome Cosmique + Maillage Spatial

Prototype : croise 2 profils cosmiques (via la brique `personnages`) pour produire
un enfant dont le thème astral est calculé à une vraie date, avec un récit
d'hérédité en post-traitement (comparaison des 10 corps aux 2 parents).

Voir les specs :
- `docs/superpowers/specs/2026-08-22-world-engine-genome-cosmique-design.md`
- `docs/superpowers/specs/2026-08-23-world-engine-persistance-lignees-design.md`
- `docs/superpowers/specs/2026-08-23-world-engine-maillage-spatial-design.md`

Persiste automatiquement chaque enfant produit (SQLite, cloisonné par `cle_api`)
— voir `stockage.py`. Dépend de la brique `personnages` (port 5900) en HTTP pour
tout calcul astral — pas de duplication du moteur astro.

Génère et persiste aussi des mondes spatiaux (maillage Voronoï, biomes/ressources
par bruit cohérent, forkables pour représenter des lignées temporelles divergentes)
— voir `spatial.py` (génération pure) et `stockage_spatial.py` (persistance). Un
enfant peut être placé sur un monde à sa naissance via `monde_id` sur
`POST /genome/croiser`.

Port : 6220.
