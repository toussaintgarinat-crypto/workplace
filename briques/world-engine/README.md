# world-engine — Génome Cosmique + Maillage Spatial + Horloge de simulation

Prototype : croise 2 profils cosmiques (via la brique `personnages`) pour produire
un enfant dont le thème astral est calculé à une vraie date, avec un récit
d'hérédité en post-traitement (comparaison des 10 corps aux 2 parents).

Voir les specs :
- `docs/superpowers/specs/2026-08-22-world-engine-genome-cosmique-design.md`
- `docs/superpowers/specs/2026-08-23-world-engine-persistance-lignees-design.md`
- `docs/superpowers/specs/2026-08-23-world-engine-maillage-spatial-design.md`
- `docs/superpowers/specs/2026-08-23-world-engine-horloge-simulation-design.md`

Persiste automatiquement chaque enfant produit (SQLite, cloisonné par `cle_api`)
— voir `stockage.py`. Dépend de la brique `personnages` (port 5900) en HTTP pour
tout calcul astral — pas de duplication du moteur astro.

Génère et persiste aussi des mondes spatiaux (maillage Voronoï, biomes/ressources
par bruit cohérent, forkables pour représenter des lignées temporelles divergentes)
— voir `spatial.py` (génération pure) et `stockage_spatial.py` (persistance). Un
enfant peut être placé sur un monde à sa naissance via `monde_id` sur
`POST /genome/croiser`.

Fait vivre un monde au fil de ticks (`/horloge`, 1 tick = 1 an narratif) :
vieillissement/mortalité (réduite par la technologie locale), migration poussée
par la rareté des ressources, couples formés/dissous par hasard, reproduction
(couples établis + rencontres occasionnelles) — voir `horloge.py` (mécanique
pure) et `horloge_moteur.py` (orchestrateur). Déclenchement manuel
(`POST /horloge/{id}/tick`) ou automatique opt-in par monde
(`POST /horloge/{id}/demarrer`, scheduler in-process — pas de queue externe,
volume visé modéré ce sprint). Mondes fédérés (pays→monde) et mise à l'échelle
(traitement vectorisé, queue Redis/RabbitMQ) restent hors périmètre.

Port : 6220.
