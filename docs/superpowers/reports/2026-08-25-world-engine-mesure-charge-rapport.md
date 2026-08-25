# World Engine — Rapport de mesure de charge LIVE (préalable Sprint E)

**Date** : 2026-08-25
**Contexte** : voir [spec](../specs/2026-08-25-world-engine-mesure-charge-design.md) et
[plan](../plans/2026-08-25-world-engine-mesure-charge.md). Sprint E (mise à l'échelle)
devait trancher Redis vs RabbitMQ « une fois le volume réel connu » — ce rapport
fournit ce volume réel, mesuré en LIVE sur le HP, pas estimé.

## Scénario exécuté

- `world-engine` déployé en LIVE **permanent** sur le HP (`192.168.1.89:6230` —
  voir note de port ci-dessous), sain (`docker healthcheck`), dépendant de
  `personnages` (déjà en service).
- 5 mondes fédérés en anneau (adjacence circulaire), répartis sur **2 tenants
  distincts** (`API_KEYS` local à la brique = 3 pays, `WORLD_ENGINE_KEY` = 2 pays)
  — vérifié empiriquement : les 2 clés sont bien acceptées indépendamment, une
  requête sans clé est rejetée 401 (aucun mode public résiduel).
- Peuplement initial : 40 fondateurs/monde (200 au total) via `/genome/croiser`,
  sexes équilibrés, monde_id assigné à la naissance.
- Scheduler automatique activé sur les 5 mondes (intervalle configuré 5s),
  laissé tourner **~12 minutes** (fenêtre `observer`, échantillonnage toutes les
  2s) : les mondes ont avancé de **126 ticks** chacun pendant cette fenêtre.
- Puis scheduler arrêté, **rafale de 20 rounds de ticks manuels concurrents**
  sur les 5 mondes (100 appels au total) pour capturer `avertissements` — le
  scheduler automatique les jette silencieusement (voir constat plus bas).
- `docker stats` échantillonné en parallèle sur toute la fenêtre.

**Croissance organique observée** : partis de 200 fondateurs, le peuplement a
atteint **3 473 enfants créés au total** (fondateurs + naissances automatiques
des ticks, tous tenants confondus) dont **1 582 vivants** à la fin de la mesure
(mortalité liée à l'âge + reproduction ont largement dépassé le peuplement
initial en 146 ticks). Le scénario a donc sollicité `genome_moteur.executer_croisement`
(et ses ~4 appels internes vers `personnages`) plusieurs milliers de fois, pas
seulement les 200 fondateurs — plus de charge réelle que le plan ne l'anticipait.

## Résultat 1 — Latence et dérive de tick (fenêtre scheduler, intervalle configuré 5s)

| Monde | Ticks observés | écart min | écart p50 | écart p95 | écart max |
|---|---|---|---|---|---|
| febbac99d4c3… | 126 | 4,09s | 6,16s | 6,27s | 6,30s |
| f8393296602e… | 126 | 4,09s | 6,15s | 6,27s | 6,30s |
| 7df2e55ef98e… | 126 | 4,09s | 6,16s | 6,27s | 6,29s |
| 5f4299e416d3… | 126 | 4,09s | 6,16s | 6,27s | **8,35s** |
| 13346d1c3eb1… | 126 | 4,09s | 6,16s | 6,28s | **8,36s** |

**Lecture** : le scheduler ne tient pas l'intervalle configuré de 5s — l'écart
médian réel est ~6,15-6,16s, soit environ **+23% de dérive systématique** sur
les 5 mondes, constante et reproductible (pas un bruit isolé). 2 des 5 mondes
montrent un pic isolé à ~8,3-8,4s (écart max), les 3 autres restent bornés à
~6,3s. Le plancher à 4,09s (jamais en dessous) est cohérent avec le
comportement du scheduler in-process (`asyncio.sleep(SCHEDULER_INTERVALLE_S)`
puis vérification, jamais un déclenchement anticipé).

## Résultat 2 — Avertissements de verrou (rafale manuelle, 20 rounds × 5 mondes = 100 ticks)

**143 avertissements sur 100 ticks manuels concurrents, 0 erreur/timeout de
transport.** Chaque avertissement, sans exception, est de la forme :

> `Émigration de <id> vers <pays> non appliquée : verrou du pays destination
> indisponible (retentera au tick suivant).`

Ce sont exactement les avertissements de `horloge_moteur._acquerir_verrou_destination`
(Sprint D) — le verrou de tick du pays destination, tenu par le tick concurrent
de CE pays, expire après `VERROU_DESTINATION_TIMEOUT_S = 5.0s`. La durée des
ticks manuels de la rafale confirme ce mécanisme : `duree_s` min=0,22s
p50=5,78s p95=6,58s **max=10,77s** — la majorité des ticks concurrents attend
bien près des 5s du timeout de verrou avant de continuer (voire deux verrous en
série dans les cas les plus chargés, ~10,8s).

**Lecture** : avec 5 pays qui tiquent EXACTEMENT en même temps (rafale
manuelle) et une population significative en migration transfrontière, la
contention de verrou destination n'est pas un cas rare — elle survient dans
la majorité des rounds (avertissements présents dans 17 des 20 rounds). C'est
le comportement DOCUMENTÉ et ASSUMÉ du Sprint D (l'émigration échouée
retentera au tick suivant, aucune corruption), mais c'est un signal réel de
contention sous charge concurrente.

**Constat d'observabilité (limite découverte pendant cette mesure)** : le
scheduler automatique (`main.py:_boucle_scheduler`) appelle
`horloge_moteur.executer_tick` et **jette silencieusement** son résultat,
`avertissements` inclus (`except Exception: continue`, résultat jamais lu).
Un déploiement qui laisserait tourner uniquement le scheduler automatique
(comme en usage normal) **ne verrait jamais** ces avertissements de verrou
nulle part — ni logs, ni métriques, ni valeur de retour. Ce n'est pas un bug
(le scheduler n'a jamais eu vocation à consigner ces données), mais un angle
mort d'observabilité réel si la contention de verrou devient un sujet
opérationnel un jour.

## Résultat 3 — Contention SQLite

**Aucune** ligne contenant `locked`, `traceback` ou `error` dans les logs du
conteneur sur toute la fenêtre (~20 minutes, `docker logs --since 20m`).
Malgré la charge réelle (146 ticks × 5 mondes concurrents + rafale manuelle +
3473 créations d'enfants), SQLite n'a montré aucun signe de contention
visible dans les logs applicatifs à cette échelle.

## Résultat 4 — CPU / mémoire (25 échantillons valides sur ~20 minutes, `docker stats`)

- **CPU** : min 0,08% — médiane 1,19% — **max 36,39%** (pic isolé, probablement
  une salve de naissances concurrentes déclenchant plusieurs appels HTTP vers
  `personnages` en parallèle).
- **Mémoire** : très stable, 97,16 MiB → 101,0 MiB sur toute la fenêtre (pas de
  tendance à la hausse observable sur cette durée — aucun signal de fuite,
  mais 20 minutes ne prouvent rien sur des heures/jours).

## Deux correctifs hors-plan découverts en déployant réellement

Aucun n'était anticipé par la spec — trouvés uniquement parce que le
déploiement était réel, pas simulé :

1. **Collision de port réelle** : `world-engine` et `jeu-factions-public`
   réclamaient tous deux le port `6220` en dur dans leur `docker-compose.yml`/
   `manifest.json` — invisible jusqu'ici car `world-engine` n'avait jamais été
   déployé sur le HP. `jeu-factions-public` était déjà en service ; `world-engine`
   a été réassigné sur **6230** (commit `6c9f87b`).
2. **Second tenant sans toucher l'auth partagée** : le `.env` racine du HP
   n'avait qu'une seule clé configurée (`WORLD_ENGINE_KEY`) — pas de `API_KEYS`
   générique. Ajouter `API_KEYS` dans le `.env` racine aurait activé l'auth
   fail-closed pour les ~22 autres briques qui le lisent (effet de bord
   fleet-wide hors périmètre). Solution : un second `env_file` **local à la
   brique** (`briques/world-engine/.env`, non versionné), chargé après le
   `.env` racine (commit `55aa5e7`).

Un troisième correctif, découvert pendant l'exécution de la rafale manuelle :
`commande_rafale_manuelle` ne capturait pas les dépassements de timeout HTTP
(`TimeoutError`, sous-classe d'`OSError`) — un tick manuel peut légitimement
dépasser les 15s du script (une naissance chaîne un appel HTTP à `personnages`
avec son propre timeout de 30s). Corrigé pour capturer ce cas comme les autres
échecs isolés plutôt que de faire planter toute la rafale (commit `b71f4a8`).

## Ce que ce rapport ne dit pas

Ce rapport constate des chiffres, il ne tranche pas Redis vs RabbitMQ ni
aucune autre décision d'architecture — c'est la matière du prochain
brainstorming Sprint E, pas de ce document. Deux pistes de lecture pour ce
futur brainstorming, sans les trancher ici : la dérive de +23% sur l'intervalle
de tick a une cause à investiguer (charge CPU ? latence `personnages` ?) avant
de conclure qu'elle nécessite une queue ; la contention de verrou destination
n'est significative que sous ticks VRAIMENT concurrents (rafale manuelle) — le
scheduler automatique, lui, espace naturellement les ticks des différents
mondes et n'a montré aucun avertissement observable (faute d'observabilité,
voir Résultat 2 — pas la même chose que « aucune contention »).
