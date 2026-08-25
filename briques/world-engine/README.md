# world-engine — Génome Cosmique + Maillage Spatial + Horloge de simulation + Mondes fédérés

Prototype : croise 2 profils cosmiques (via la brique `personnages`) pour produire
un enfant dont le thème astral est calculé à une vraie date, avec un récit
d'hérédité en post-traitement (comparaison des 10 corps aux 2 parents).

Voir les specs :
- `docs/superpowers/specs/2026-08-22-world-engine-genome-cosmique-design.md`
- `docs/superpowers/specs/2026-08-23-world-engine-persistance-lignees-design.md`
- `docs/superpowers/specs/2026-08-23-world-engine-maillage-spatial-design.md`
- `docs/superpowers/specs/2026-08-23-world-engine-horloge-simulation-design.md`
- `docs/superpowers/specs/2026-08-24-world-engine-mondes-federes-design.md`

Persiste automatiquement chaque enfant produit (SQLite, cloisonné par `cle_api`)
— voir `stockage.py`. Dépend de la brique `personnages` (port 5900) en HTTP pour
tout calcul astral — pas de duplication du moteur astro. Exception à ce
cloisonnement (Sprint D) : un habitant qui migre vers un pays fédéré d'une autre
`cle_api` voit sa ligne `enfants` transférée au tenant du pays destination — voir
plus bas.

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
volume visé modéré ce sprint).

Fédère enfin plusieurs mondes (`/federation`, Sprint D) : chaque monde rattaché
devient un « pays », des adjacences sont déclarées explicitement entre pays d'une
même fédération, et les habitants d'une cellule saturée peuvent franchir une
frontière vers un pays adjacent (migration transfrontière, âge préservé, ligne
d'origine conservée et marquée « émigré ») — voir `stockage_federation.py`. Une
fédération peut mélanger plusieurs `cle_api`, chaque acte ayant sa règle de
consentement (voir `docs/superpowers/specs/2026-08-24-world-engine-mondes-federes-design.md`).
Chaque pays garde son horloge autonome : aucune synchronisation de ticks.

La mise à l'échelle (traitement vectorisé, queue Redis/RabbitMQ) reste hors
périmètre, tout comme la reproduction transfrontière, la diplomatie entre pays et
le rendu d'une carte fédérée.

Port : 6220.
