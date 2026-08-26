# World Engine — Sprint E, correctif contention de verrou

**Date** : 2026-08-26
**Statut** : design approuvé, plan d'implémentation à venir

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
