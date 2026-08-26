# World Engine — Sprint E, correctif contention de verrou

**Date** : 2026-08-26
**Statut** : design approuvé, plan d'implémentation à venir

## Mise à jour post-validation LIVE (v2 du correctif)

Le correctif initial (timeout 1.0s + jitter au TOUT PREMIER démarrage
uniquement, `derniere_execution IS NULL`) a été codé, revu (2 Important
trouvés et corrigés en revue — test manquant + race TOCTOU, voir
`.superpowers/sdd/task-1-report.md`) et validé en LIVE sur le HP. Résultat :
dérive descendue de +94,6% à **+40,4%** (écart moyen 7,02s), avertissements
de verrou montés de 328 à **608** sur la fenêtre de 12 min. Le timeout
réduit a bien aidé, mais **le jitter n'a jamais été exercé par ce test** :
les 5 mondes existants avaient déjà tické ~300 fois ensemble AVANT que ce
correctif n'existe, donc `derniere_execution` n'était déjà plus `NULL` —
la condition qui déclenche le jitter ne s'est jamais activée. Les mondes
restent synchronisés indéfiniment une fois qu'ils l'ont été, le
comportement « garde sa phase existante » de la v1 les maintenait dans cet
état pour toujours.

Décision utilisateur (brainstorming) : **étendre le jitter à CHAQUE appel à
`demarrer()`**, pas seulement au tout premier — un monde déjà en lockstep
avec ses voisins ne se désynchronise jamais tout seul, donc seul un
redémarrage qui rejitte systématiquement peut casser une synchronisation
déjà installée. Ce choix contredit la décision v1 (« un monde déjà tické
avant garde sa phase existante ») ; cette décision reposait sur une
hypothèse (les mondes se désynchroniseraient naturellement, ou n'avaient
besoin d'être désynchronisés qu'une fois) invalidée par la mesure LIVE.
Effet secondaire positif : cela **simplifie** le code de `demarrer` plutôt
que de l'alourdir — plus besoin de lire `derniere_execution` avant
d'écrire, donc plus besoin de la transaction `BEGIN IMMEDIATE` ajoutée en
revue pour fermer la race TOCTOU de la v1 (elle disparaît avec la
condition qui la rendait nécessaire). Compromis assumé : un redémarrage
après une pause perd la continuité exacte de son ancien rythme (nouvelle
phase aléatoire à chaque fois) — acceptable, `tick_actuel` (la progression
réelle) n'est jamais affecté par `demarrer`, seul l'horodatage de
planification change.

## Mise à jour n°2 — le jitter systématique ne suffit pas (v3 du correctif)

Le jitter étendu à chaque démarrage a été codé, revu (0 Critical/Important)
et validé en LIVE : **aucune amélioration mesurable**. Écart moyen
identique à celui du timeout seul (~7,02s, +40,4% puis +40,7%),
avertissements de verrou similaires (608 puis 522 sur 12 min). Vérifié
empiriquement que le jitter fonctionne bien (les 5 mondes démarrent
désormais à des instants clairement étalés, pas simultanés) — mais ça ne
change presque rien au résultat.

⚠️ **Correctif post-revue finale de branche** : l'explication ci-dessous
(« cause statistique », écart de phase minimal ≈0,17s) était **fausse** —
gardée biffée pour l'honnêteté du journal de décision, corrigée en
« Mise à jour n°4 ». <s>Cause statistique, pas un bug : avec 5 mondes
répartis aléatoirement sur un cycle de 5s, l'écart minimal attendu entre
les deux mondes les plus proches en phase est de l'ordre de 5/(5×6) ≈
0,17s — bien en dessous du temps qu'un tick contesté peut prendre (jusqu'à
1,0s, le timeout de verrou). À ce ratio (nombre de mondes / longueur de
cycle / coût maximal d'une collision), une paire de mondes reste presque
toujours assez proche en phase pour se percuter, quel que soit le tirage
aléatoire.</s> Le jitter ne peut pas résoudre un problème de RATIO,
seulement de synchronisation permanente (ce qu'il a effectivement résolu :
+94,6% → +40,4%, un plafond atteint dès le seul timeout réduit) — cette
dernière phrase reste juste, seule la cause invoquée était fausse.

Décision utilisateur : passer à une refonte du mécanisme de verrouillage
lui-même plutôt que de continuer à chercher un meilleur timing.

### Diagnostic de fond (lu dans le code, pas une hypothèse)

`_acquerir_verrou_destination` acquiert `_verrou_tick(monde_id)` — c'est
**le même verrou** qui sérialise l'exécution complète du tick du pays
destination (`executer_tick` : `async with _verrou_tick(monde_id): ...`).
Ce n'est pas un verrou étroit dédié à l'écriture d'une migration : c'est
le verrou d'exécution ENTIER du pays destination, emprunté tel quel. Un
migrant vers le pays B doit donc attendre que TOUT le tick de B se
termine, pas seulement une écriture — d'où un coût de collision proche de
la durée d'un tick complet (~0,2-1s selon la charge), pas de quelques
millisecondes.

Le mécanisme d'échec est déjà sûr et accepté depuis le Sprint D : verrou
indisponible → l'émigration échoue proprement, capturée dans
`avertissements`, retentera au tick suivant, zéro corruption. L'attente
actuelle (`asyncio.wait_for(..., timeout=1.0)`) ne fait que retarder ce
verdict déjà connu — elle espère que le tick concurrent libère le verrou
à temps, mais les trois mesures LIVE (avec et sans jitter) montrent que ce
pari ne paie quasiment jamais : le coût de l'attente est payé presque à
chaque collision, sans réduire le nombre d'échecs qui finissent par se
produire de toute façon.

### Décision de conception

**Rendre la tentative d'acquisition non-bloquante, pas remplacer le
verrou.** Deux options explorées :

- **Verrou séparé, plus étroit, dédié à l'écriture seule** (l'idée
  d'origine d'« Option 3 ») — libérerait le tick du pays destination de
  toute dépendance envers les migrations entrantes. Écartée : elle change
  la portée de la synchronisation entre les mondes, ce qui retoucherait
  aux invariants de correction établis avec soin au Sprint D (ordre
  dissolution de couple / verrou destination, atomicité de la passe 2b —
  voir les commentaires de revue dans `horloge_moteur.py` autour de la
  résolution des verrous). Risque de régression plus élevé qu'un gain
  incertain ne le justifie.
- **Vérification non-bloquante sur le MÊME verrou** (retenue) :
  `_acquerir_verrou_destination` vérifie `verrou.locked()` — si déjà tenu,
  échoue INSTANTANÉMENT (même verdict qu'avant, juste sans l'attente) ; si
  libre, `await verrou.acquire()` réussit immédiatement (dans le modèle
  coopératif d'asyncio, aucune tâche ne peut s'intercaler entre le test
  `.locked()` et l'`acquire()` puisqu'aucun `await` ne les sépare — pas de
  fenêtre de course). Ne change ni la portée du verrou, ni son
  identité, ni aucun invariant Sprint D — seulement la présence d'une
  attente avant l'échec. `VERROU_DESTINATION_TIMEOUT_S` devient inutile et
  est retiré (plus de valeur à monkeypatcher pour les tests qui simulaient
  un timeout court).

## Hors périmètre (mise à jour v3)

- Le verrou séparé pour l'écriture seule (ci-dessus) reste noté comme
  option de repli si la mesure LIVE de ce correctif s'avère encore
  insuffisante — pas codé dans ce sprint.
- Le comportement de re-tentative au tick suivant reste inchangé — c'est
  précisément ce qui permet de rendre l'acquisition non-bloquante sans
  perdre en fiabilité : l'échec instantané mène exactement au même filet
  de sécurité qu'un échec après attente.

## Contexte

Suite de [world-engine-sprint-e-scheduler-parallele-design](2026-08-25-world-engine-sprint-e-scheduler-parallele-design.md).
Ce correctif (`asyncio.gather()` par passage) a été codé, revu (0 Critical/
Important) et poussé (`2676b4a`). Sa validation LIVE sur le HP — rejouer le
scénario de mesure du 2026-08-25 (5 mondes fédérés, scheduler automatique,
fenêtre de 12 min) — a produit un résultat inattendu :

| | Avant (25/08, scheduler sériel) | Après le correctif scheduler (26/08) |
|---|---|---|
| Écart moyen non biaisé | 5,698s | **9,73s** |
| Dérive vs 5s configuré | +14,0% | **+94,6%** |
| Ticks observés en 12 min | 126/monde | 73-74/monde |

Diagnostic établi par mesure directe, pas par hypothèse : un tick isolé
(sans concurrence, via `POST /horloge/{id}/tick` pendant que le scheduler
était arrêté) prend **~0,2s** à la population actuelle (population vivante
totale 1437, comparable à celle de fin de mesure originale — pas un effet
de croissance de charge). Les logs du conteneur pendant la fenêtre de 12 min
contiennent **328 avertissements** `verrou du pays destination indisponible`
sur ~366 ticks au total (5 mondes × ~73) — c'est le mécanisme de contention
du Sprint D (`horloge_moteur._acquerir_verrou_destination`,
`VERROU_DESTINATION_TIMEOUT_S = 5.0`), mesuré à l'origine seulement en
rafale manuelle, devenu ici le régime **permanent** : les 5 mondes du
scénario partagent le même intervalle (5s) et ont été démarrés ensemble,
donc ils restent en permanence dus au même instant. Dans une topologie en
anneau (chaque pays adjacent à 2 voisins), 5 ticks démarrés simultanément
qui essaient chacun de migrer vers leur voisin forment une attente
circulaire qui ne se résout qu'au bout du timeout complet — d'où une durée
de tick moyenne proche de 5s (mesurée ~4,7s) au lieu des ~0,2s mesurés sans
concurrence, ce qui domine largement la durée du passage
(`max(durées)` du correctif du 25/08 fonctionne comme prévu, mais le
`max` lui-même est maintenant proche du timeout de verrou, pas du coût de
calcul réel).

Le mécanisme parallélisé du 25/08 n'est donc pas remis en cause — il
élimine bien la sommation sérielle qu'il ciblait — mais il expose une
contention que le scheduler sériel ne pouvait structurellement jamais
atteindre. Décision utilisateur (brainstorming) : corriger cette
contention plutôt que de la documenter comme limite acceptée.

## Objectif

1. Réduire l'attente maximale sur un verrou de pays destination contendu,
   pour qu'un tick ne puisse plus approcher les 5s d'attente alors qu'un
   tick non contendu prend ~0,2s à l'échelle actuelle.
2. Réduire la fréquence à laquelle plusieurs mondes partageant le même
   intervalle deviennent dus exactement au même instant, pour que la
   contention mesurée ci-dessus cesse d'être le régime permanent d'un
   déploiement où plusieurs pays sont démarrés ensemble avec le même
   intervalle — un scénario réaliste (pas un artefact du script de mesure
   seul), puisque `POST /horloge/{id}/demarrer` est l'API produit que tout
   client utiliserait de la même façon.

## Hors périmètre

- Revoir la granularité du verrou lui-même (ne verrouiller que l'écriture
  de la migration plutôt que tout le tick) — chantier plus large touchant
  le cœur du mécanisme Sprint D, à envisager seulement si ce correctif
  s'avère insuffisant en re-mesure LIVE.
- Exposer le plafond du jitter comme paramètre de configuration — décision
  utilisateur explicite : le plafond est l'intervalle configuré lui-même,
  pas une valeur séparée à régler.
- Revoir le comportement de re-tentative existant (« retentera au tick
  suivant ») — inchangé, toujours correct et suffisant.

## Décisions de conception

- **`VERROU_DESTINATION_TIMEOUT_S` : `5.0` → `1.0`** (`horloge_moteur.py`).
  Justifié par la mesure directe (tick isolé ~0,2s à la population
  actuelle) — une marge ×5 laisse la place à une salve de naissances
  occasionnelle (qui ajoute des appels `personnages` dans le tick) sans
  revenir à une attente proche de l'ancien timeout. Le comportement en cas
  d'échec ne change pas (« retentera au tick suivant », capturé dans
  `avertissements`) — seule la latence maximale change.
- **Jitter au premier démarrage d'une horloge, plafonné à l'intervalle
  configuré** (`stockage_horloge.demarrer`). Quand une horloge n'a
  **jamais** été exécutée (`derniere_execution IS NULL`), `demarrer`
  l'initialise désormais à `now - random.uniform(0, intervalle_secondes)`
  au lieu de la laisser `NULL`. Une horloge déjà tickée avant (redémarrée
  après un arrêt) garde sa phase existante, `demarrer` ne touche pas
  `derniere_execution` dans ce cas — comportement inchangé pour ce cas,
  seul le tout premier démarrage change. Décision utilisateur explicite sur
  le plafond : proportionnel à l'intervalle configuré (pas une petite
  valeur fixe) — un monde isolé à intervalle long peut donc attendre
  jusqu'à cet intervalle avant son tout premier tick, ce compromis est
  assumé en échange d'une désynchronisation complète entre mondes
  partageant le même intervalle.
- **Changement de comportement assumé, à documenter dans le test qui
  l'encode** : `test_stockage_horloge.py:45`
  (`test_horloges_actives_a_declencher_jamais_executee_est_due`) vérifie
  aujourd'hui qu'une horloge jamais exécutée est due **immédiatement**,
  quelle que soit la date de vérification. Après ce correctif, une horloge
  jamais exécutée est due à un instant aléatoire dans son premier
  intervalle, plus nécessairement immédiatement. Le test est renommé et
  son assertion ajustée pour vérifier que l'horloge devient due au plus
  tard `intervalle_secondes` après son démarrage (borne haute garantie),
  pas qu'elle est due sur la toute première vérification.

## Tests

- `stockage_horloge.py` : nouveau test vérifiant qu'après `demarrer()` sur
  une horloge jamais exécutée, `derniere_execution` n'est plus `None` et
  est compris entre `now - intervalle_secondes` et `now` (bornes du
  jitter) ; test existant `test_horloges_actives_a_declencher_jamais_executee_est_due`
  renommé et réécrit pour vérifier la borne haute (due au plus tard après
  `intervalle_secondes`), pas l'immédiateté.
- `horloge_moteur.py` : les tests existants monkeypatchent déjà
  `VERROU_DESTINATION_TIMEOUT_S` à une valeur courte pour leurs propres
  besoins (`test_horloge_moteur.py:629`) — aucun changement structurel
  nécessaire ; vérifier simplement que la valeur par défaut du module est
  bien `1.0` après le changement (assertion directe sur la constante).

## Validation LIVE

Une fois codé/testé/revu et poussé : redéploiement sur le HP et rejeu du
même scénario que la mesure du 26/08 (5 mondes, mêmes clés, scheduler
automatique 5s, fenêtre de 12 min). Critères de succès :
- Écart moyen non biaisé nettement inférieur aux 9,73s mesurés avant ce
  correctif — idéalement proche des ~5,7s d'avant la parallélisation
  (Sprint E scheduler) ou mieux.
- Nombre d'avertissements de verrou dans les logs de la fenêtre nettement
  inférieur aux 328 mesurés avant ce correctif.
- Aucune régression : toujours 0 erreur de tick, toujours des migrations
  transfrontières appliquées avec succès sur la fenêtre (pas de blocage
  total du mécanisme de migration).

## Mise à jour n°4 — revue finale de branche (2026-08-26)

Le correctif v3 (verrou non-bloquant + filet 0,05s) a été validé en LIVE :
6,22s/+24,4% (contre 7,02s/+40,7%), avertissements montés à 1700 (attendu :
chaque échec coûte ~0 au lieu de jusqu'à 1s). Décision utilisateur initiale :
s'arrêter là. La revue finale de branche (opus, tout le Sprint E) a trouvé
des inexactitudes de documentation à corriger et une cause racine plus
profonde, non encore traitée — voir tableau complet dans
`docs/superpowers/reports/2026-08-25-world-engine-mesure-charge-rapport.md`.

**Trouvaille infirmée par mesure directe** : la revue affirmait la
migration transfrontière « effectivement morte » sous le scheduler
parallèle. Vérifié en LIVE (5 rounds de ticks concurrents réels, même
mécanisme que le scheduler) : **77 migrations réussies contre 68 échecs**
(~53% de réussite), pas 0%. La fonctionnalité est dégradée par rapport au
régime sériel d'origine (contention rare devenue fréquente), pas inerte —
correction du récit, pas du code.

**Trouvaille confirmée, cause racine véritable de la dérive résiduelle** :
`_boucle_scheduler` fait `sleep(HORLOGE_SCHEDULER_INTERVALLE_S)` PUIS le
travail, sans compenser le temps déjà écoulé — l'écart moyen mesuré est
donc **structurellement** `HORLOGE_SCHEDULER_INTERVALLE_S + durée du
passage`, vérifié exact sur les 4 mesures (5+0,698=5,698 ;
5+2,02=7,02 ; 5+1,22=6,22). Conséquence : l'objectif « dérive proche de
0% » du design du 25/08 était mathématiquement inatteignable avec cette
forme de boucle, quelle que soit la rapidité du verrou — chaque correctif
de ce document a bien réduit la dérive (en réduisant la durée du passage),
mais ne pouvait jamais l'annuler.

**Cause réelle de l'inertie du jitter** (remplace l'explication statistique
biffée ci-dessus) : `HORLOGE_SCHEDULER_INTERVALLE_S` (cadence de sondage du
scheduler) et `intervalle_secondes` (cadence propre à chaque monde) sont
déjà deux réglages indépendants dans le code — mais le scénario de mesure
les règle tous les deux à 5s. Le sondage se fait donc à la MÊME granularité
que l'intervalle des mondes : dès que la durée du passage dépasse 0, TOUS
les mondes redeviennent dus au passage suivant, pour toujours (démontré
par simulation par le reviewer : `mondes dus par passage : [5, 5, 5, 5, …]`
avec jitter actif). Le jitter ne peut décaler QUE le tout premier passage
après démarrage — il n'a aucun effet sur le régime permanent, parce que le
sondage n'est jamais assez fin pour que deux mondes jittés atterrissent
dans des passages différents.

**Décision utilisateur** : corriger les inexactitudes de documentation
trouvées par la revue (Task 7 du plan), et tenter le correctif peu coûteux
qu'elles révèlent — découpler la cadence de sondage du scheduler de
l'intervalle des mondes (Task 8), en réduisant
`HORLOGE_SCHEDULER_INTERVALLE_S` par défaut de la valeur configurée pour
le déploiement (via `docker-compose.yml`, pas de changement de code Python
nécessaire — la variable d'environnement existe déjà). Sonder plus
finement que l'intervalle le plus court des mondes actifs permet
simultanément : (1) de réduire la dérive résiduelle (moins de temps perdu
entre l'échéance réelle et le sondage qui la détecte), (2) de rendre le
jitter enfin effectif (des mondes jittés à des instants différents dans
leur fenêtre de 5s peuvent désormais tomber dans des passages de sondage
différents), et (3) probablement d'améliorer le taux de réussite des
migrations (moins de mondes simultanément dus par passage = moins de
verrous destination tenus en même temps).

## Résultat final (2026-08-26)

`HORLOGE_SCHEDULER_INTERVALLE_S=1` déployé (commit `4ce4141`, aucun
changement Python). Re-mesure LIVE : **5,55s d'écart moyen, +11,0% de
dérive** (contre +14,0% pour le régime sériel de départ — meilleur, pas
seulement comparable) et **59 avertissements de verrou sur 12 min**
(contre 1700 avant ce correctif, ÷29). Zéro erreur de tick. Confirme
l'hypothèse de la revue finale : le sondage à cadence fine était bien la
cause dominante, pas un facteur secondaire — les 3 correctifs précédents
sur le verrou lui-même (timeout, jitter, non-bloquant) n'avaient pu
qu'atténuer un symptôme dont ce correctif traite la cause. Sprint E
(scheduler + contention de verrou) clos ici.
