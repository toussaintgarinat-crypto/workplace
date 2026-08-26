# World Engine — Rapport de mesure de charge LIVE (préalable Sprint E)

> **Correctifs Sprint E (2026-08-26)** : la dérive de +14,0% mesurée
> ci-dessous (Résultat 1) a pour cause `_boucle_scheduler` en série —
> corrigée en parallélisant l'exécution des mondes dus par passage
> (`asyncio.gather`, commit `2676b4a`, voir
> `docs/superpowers/specs/2026-08-25-world-engine-sprint-e-scheduler-parallele-design.md`).
> La re-mesure LIVE a alors révélé un nouveau goulot — la contention de
> verrou destination (Résultat 2 ci-dessous), rare sous le scheduler
> sériel, devenue systématique sous le scheduler parallèle puisque les 5
> mondes du scénario partagent le même intervalle. Quatre cycles
> correctif→mesure LIVE (voir
> `docs/superpowers/specs/2026-08-26-world-engine-sprint-e-correctif-contention-verrou-design.md`
> pour le détail de chaque décision) :
>
> | Étape | Écart moyen | Dérive | Avertissements/12min | Commit |
> |---|---|---|---|---|
> | Scheduler sériel (ce rapport) | 5,698s | +14,0% | — | (avant `2676b4a`) |
> | Scheduler parallélisé seul | 9,73s | +94,6% | 328 | `2676b4a` |
> | + timeout verrou 5.0s→1.0s | 7,02s | +40,4% | 608 | `8449cb7`+`0d4cb38` |
> | + jitter à chaque démarrage | 7,02s | +40,7% | 522 | `b84acf0` |
> | + verrou destination non-bloquant | **6,22s** | **+24,4%** | 1700 | `12079d6`+`a59e395` |
>
> Décision utilisateur (2026-08-26) : s'arrêter à +24,4% — amélioration
> réelle et substantielle (dérive divisée par ~4 par rapport au pire point
> mesuré), zéro erreur de tick sur toutes les fenêtres. Le nombre
> d'avertissements monte à chaque étape car chaque échec de verrou coûte
> de moins en moins cher (jusqu'à 1s d'attente à l'origine, quasi 0 avec le
> verrou non-bloquant) — plus d'échecs enregistrés, mais moins de temps
> total perdu. Piste identifiée mais **non vérifiée** pour la dérive
> résiduelle (+24,4%) : un tick isolé sans concurrence prend ~0,38s
> (mesuré le 26/08, population ~1482) contre ~1,2s de coût observé par
> passage — l'écart pourrait venir d'une contention sur le service
> `personnages` partagé sous 5 appels HTTP concurrents (mécanisme différent
> du verrou destination, pas encore investigué).

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
  Rejouée une seconde fois après un correctif de mesure (voir Résultat 2) ;
  les chiffres de ce rapport sont ceux de la seconde rafale, propre.
- `docker stats` échantillonné pendant la fenêtre scheduler **seule** (11,9
  min) — voir Résultat 4, la rafale manuelle n'a pas été échantillonnée.

**Croissance organique observée** (mesurée juste après la fenêtre scheduler de
126 ticks, via `GET /genome/enfants` par tenant et `GET /federation/{id}/etat`) :
partis de 200 fondateurs, le peuplement a atteint **3 473 enfants créés au
total** (fondateurs + naissances automatiques des ticks, tous tenants
confondus) dont **1 582 vivants** à ce point de la mesure (mortalité liée à
l'âge + reproduction ont largement dépassé le peuplement initial en 126
ticks). Le scénario a donc sollicité `genome_moteur.executer_croisement`
(et ses ~4 appels internes vers `personnages`) plusieurs milliers de fois, pas
seulement les 200 fondateurs — plus de charge réelle que le plan ne l'anticipait.

## Résultat 1 — Latence et dérive de tick (fenêtre scheduler, intervalle configuré 5s)

⚠️ **Correctif post-revue finale** (commit `1284fdc`) : la première version de
ce rapport présentait un tableau min/p50/p95/max et concluait à « +23% de dérive ». Ces
écarts sont en réalité **quantifiés par la période de polling de `observer`
(~2,05s)** — chaque écart individuel est un multiple entier de ce pas, pas une
mesure continue de l'intervalle réel entre deux ticks. Le percentile p50 tombe
sur UN bucket de polling, pas sur la tendance réelle. Seule la **moyenne**
(portée totale / nombre d'incréments), indépendante du pas de polling, est un
estimateur non biaisé :

| Monde | Ticks observés | écart moyen (non biaisé) |
|---|---|---|
| febbac99d4c3… | 126 | 5,699s |
| f8393296602e… | 126 | 5,698s |
| 7df2e55ef98e… | 126 | 5,698s |
| 5f4299e416d3… | 126 | 5,698s |
| 13346d1c3eb1… | 126 | 5,698s |

**Lecture** : le scheduler ne tient pas l'intervalle configuré de 5s — l'écart
moyen réel est **5,698s, soit +14,0% de dérive systématique** (identiques à
~10⁻⁴ près sur les 5 mondes — pas du bruit, un effet structurel). La cause
est lisible directement dans le code, pas à deviner : `main.py:370-387`
(`_boucle_scheduler`) est **une seule boucle `asyncio` qui `await` chaque
monde dû, EN SÉRIE**, pas en parallèle (`for due in dues: await
horloge_moteur.executer_tick(...)`). L'intervalle réel par monde est donc
`sleep(5s) + Σ(durée du tick de CHAQUE monde dû dans cette passe, le sien
inclus)` — avec 5 mondes dus à chaque passage, les ~0,698s supplémentaires
mesurés sont la somme des 5 durées de tick de cette passe (≈0,14s de coût
moyen par tick), pas une part du temps « des 4 autres » divisée entre eux.
**Signal pour Sprint E, à formuler comme une hypothèse à vérifier, pas un
fait établi par cette seule mesure** : ce mécanisme implique que la dérive
devrait croître AU MOINS linéairement avec le nombre de mondes actifs
(chaque monde supplémentaire allonge la même boucle série) — mais le coût
par tick lui-même peut aussi croître avec la population/la contention, donc
la vraie courbe pourrait être plus qu'une droite. Une seule mesure à 5 mondes
ne permet pas de trancher — voir la question ouverte en conclusion. Autre
conséquence du même mécanisme, celle-ci directement lisible dans le code
sans extrapolation : deux mondes ne peuvent JAMAIS tiquer concurremment sous
le scheduler automatique actuel — la contention de verrou du Résultat 2
décrit un régime que le déploiement d'aujourd'hui n'atteint jamais tout seul
(ticks manuels concurrents ou un futur multi-worker, pas le scheduler tel
quel).

## Résultat 2 — Avertissements de verrou (rafale manuelle, 20 rounds × 5 mondes = 100 ticks)

⚠️ **Correctif post-revue finale** (commit `1284fdc`) : le `duree_s` de la
première version de ce rapport (p50=5,78s) était un artefact de mesure — le code mesurait le temps
écoulé au moment de la CONSOMMATION de chaque `Future` dans l'ordre de
soumission (`for fut, m in futurs.items(): fut.result()`, bloquant), donc un
**maximum croissant** dans cet ordre, pas la durée de l'appel lui-même. Corrigé
(`_tick_manuel_chronometre`, chronométrage DANS le thread qui exécute l'appel)
et la rafale rejouée proprement avec le script corrigé :

**104 avertissements sur 100 ticks manuels concurrents, 0 erreur/timeout de
transport.** Chaque avertissement, sans exception, est de la forme :

> `Émigration de <id> vers <pays> non appliquée : verrou du pays destination
> indisponible (retentera au tick suivant).`

Ce sont exactement les avertissements de `horloge_moteur._acquerir_verrou_destination`
(Sprint D) — le verrou de tick du pays destination, tenu par le tick concurrent
de CE pays, expire après `VERROU_DESTINATION_TIMEOUT_S = 5.0s`. La durée
CORRECTEMENT mesurée des ticks manuels de la rafale : `duree_s` min=0,26s
**p50=1,22s** p95=6,39s max=10,79s — la **médiane** d'un tick concurrent est
rapide (~1,2s, la majorité des ticks n'attendent AUCUN verrou), mais la queue
haute (p95/max) montre bien des ticks qui attendent près des 5s du timeout de
verrou (voire deux verrous en série, ~10,8s dans les cas les plus chargés).

**Lecture corrigée** : avec 5 pays qui tiquent EXACTEMENT en même temps
(rafale manuelle) et une population significative en migration transfrontière,
la contention de verrou destination touche une **minorité mais non négligeable**
des ticks (avertissements dans 12 des 20 rounds sur cette rafale) — pas « la
majorité attend le timeout » comme la version précédente le concluait à tort.
C'est le comportement DOCUMENTÉ et ASSUMÉ du Sprint D (l'émigration échouée
retentera au tick suivant, aucune corruption), et — voir Résultat 1 — un
régime que le scheduler automatique actuel n'atteint jamais tout seul (ses
ticks sont sériels, jamais concurrents entre mondes).

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
conteneur, vérifié à deux reprises (`docker logs --since 20m`, une première
fois après le scheduler + la 1ère rafale manuelle, une seconde fois après la
rafale manuelle rejouée pour le correctif `duree_s` ci-dessus). Malgré la
charge réelle (126 ticks × 5 mondes via scheduler + 2 rafales de 100 ticks
manuels concurrents + 3473 créations d'enfants au total), SQLite n'a montré
aucun signe de contention visible dans les logs applicatifs à cette échelle.

## Résultat 4 — CPU / mémoire (25 échantillons, `docker stats`)

⚠️ **Correctif post-revue finale** : les échantillons couvrent la **fenêtre
scheduler (11,9 min, 19:17:19→19:29:15 UTC)**, PAS ~20 minutes comme la
version précédente l'affirmait — l'échantillonnage s'est arrêté avant le
début des rafales manuelles, qui ne sont donc **pas couvertes** par ces
chiffres alors qu'elles sont la charge concurrente la plus lourde du
scénario. Le fichier brut contient aussi une ligne corrompue (`7GiB`,
fragment d'écriture entrelacée entre deux lancements de la boucle
d'échantillonnage — l'un s'était arrêté prématurément et a dû être relancé
en cours de mesure), exclue du calcul ci-dessous.

- **CPU** (fenêtre scheduler seule) : min 0,08% — médiane 1,19% — **max
  36,39%** (pic isolé, probablement une salve de naissances concurrentes
  déclenchant plusieurs appels HTTP vers `personnages` en parallèle).
- **Mémoire** (fenêtre scheduler seule) : très stable, 97,16 MiB → 101,0 MiB
  (pas de tendance à la hausse observable sur cette durée — aucun signal de
  fuite, mais ~12 minutes ne prouvent rien sur des heures/jours, et la
  charge la plus lourde du scénario — les rafales manuelles — n'a jamais été
  échantillonnée).

## Trois correctifs hors-plan découverts en déployant/mesurant réellement

Aucun n'était anticipé par la spec — trouvés uniquement parce que le
déploiement et la mesure étaient réels, pas simulés :

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

## Disposition des données de test

Les 5 mondes/pays, la fédération, et les ~3 500+ enfants créés par ce
scénario **restent en place** sur le déploiement permanent du HP — non
supprimés après la mesure. Les deux clés `API_KEYS`/`WORLD_ENGINE_KEY`
générées pour ce test (à usage unique prévu) sont donc toujours valides et
authentifient toujours ces données ; leur rotation, ainsi que la suppression
ou la conservation de ce peuplement de test, sont une décision opérationnelle
à prendre séparément, pas incluse dans ce rapport.

## Ce que ce rapport ne dit pas

Ce rapport constate des chiffres, il ne tranche pas Redis vs RabbitMQ ni
aucune autre décision d'architecture — c'est la matière du prochain
brainstorming Sprint E, pas de ce document. Il nomme un mécanisme (le
scheduler sériel, Résultat 1) parce que c'est un fait lisible dans le code,
pas une recommandation ; les décisions de conception restent pour le
brainstorming à venir, en particulier : la dérive croît-elle vraiment
linéairement avec le nombre de mondes (à vérifier avec plus de 5 mondes avant
de la tenir pour acquise à plus grande échelle) ; la contention de verrou
mesurée en rafale manuelle a-t-elle une pertinence opérationnelle tant que le
scheduler reste sériel (elle n'apparaît dans AUCUN mode d'usage normal
aujourd'hui) ; et l'angle mort d'observabilité du scheduler (Résultat 2)
mérite-t-il d'être corrigé en amont de Sprint E ou à l'intérieur.
