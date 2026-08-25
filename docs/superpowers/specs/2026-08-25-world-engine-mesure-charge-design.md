# World Engine — Mesure de charge LIVE (préalable Sprint E)

**Date** : 2026-08-25
**Statut** : design approuvé, plan d'implémentation à venir

## Contexte

Suite de [world-engine-mondes-federes-design](2026-08-24-world-engine-mondes-federes-design.md).
Sprints A→D sont codés, revus et poussés sur `main`. La roadmap (voir mémoire
`backlog-world-engine-genome-cosmique-phases-suivantes`) prévoyait que
**Sprint E** (mise à l'échelle, arbitrage Redis vs RabbitMQ) se décide « une
fois le volume réel connu avec C+D en conditions réelles » — mais rien n'a
encore tourné en LIVE : le régime de preuve du projet sépare développement
(ici, tests natifs) et preuves Docker (groupées sur le HP, voir mémoire
`regime-preuve-docker-differe`), et ce regroupement n'a pas encore eu lieu
pour `world-engine`.

Ce document ne conçoit **pas** Sprint E. Il conçoit l'étape qui doit le
précéder : déployer `world-engine` en LIVE sur le HP et y faire tourner une
charge réaliste pour obtenir de vrais chiffres (latence par tick, contention
SQLite, comportement du scheduler sous plusieurs mondes concurrents). Sprint E
sera brainstormé séparément, à partir de ces chiffres.

État actuel du code, pour mémoire (lu dans `horloge_moteur.py`/`stockage.py`) :
un seul process, une seule base SQLite (`sqlite3.connect`, une connexion par
module de stockage), des verrous `asyncio.Lock` par monde tenus **en mémoire
de ce process** (non partagés entre workers/conteneurs), un scheduler
in-process qui avance chaque monde opt-in dans la même boucle asyncio. Aucune
queue de messages nulle part.

## Objectif

Obtenir des mesures réelles, pas estimées, sur :
1. La latence d'un tick (et sa variance) sous une fédération multi-tenant
   active.
2. La présence ou non de contention SQLite (`database is locked`) quand
   plusieurs mondes tickent en même temps.
3. Le comportement du scheduler in-process sur plusieurs mondes concurrents
   pendant une fenêtre soutenue (dérive de rythme, ticks manqués).
4. CPU/mémoire du conteneur sous cette charge.

Ces quatre points sont exactement ce qui doit trancher — ou non — le besoin
d'une queue de messages pour Sprint E.

## Hors périmètre

- Concevoir ou coder Sprint E lui-même (queue, multi-worker, sharding...).
- Corriger un goulot trouvé pendant la mesure — la mesure produit un rapport,
  pas un correctif. Un problème découvert nourrit le brainstorming Sprint E.
- Charge « ambitieuse » (dizaines de pays, milliers d'habitants) — hors
  périmètre par décision utilisateur, un scénario modeste suffit à ce stade.
- Automatiser ce scénario de charge en test pytest permanent ou en CI — c'est
  un script de mesure ponctuel, pas un filet de non-régression.

## Décisions de conception

- **Déploiement permanent dans la flotte HP**, pas une mesure jetable :
  `world-engine` est stable (Sprints A→D testés+revus), il a vocation à
  rester en LIVE durablement, pas seulement le temps du test de charge.
  Décision utilisateur explicite (brainstorming).
- **Script de mesure = appels HTTP purs contre l'API publique**, aucun code
  ajouté dans la brique elle-même. Le script vit hors de `briques/world-engine`
  (ex. `scripts/` à la racine ou un répertoire de mesure dédié — précisé dans
  le plan d'implémentation), pour bien marquer qu'il n'est pas partie du
  produit.
- **Scénario modeste, décision utilisateur** : 5 mondes fédérés, **au moins 2
  `cle_api` distinctes** parmi eux (pour exercer le chemin transfrontière
  multi-tenant du Sprint D — la fuite de clé et le transfert de propriété
  corrigés en revue finale de D sont justement ce qui doit être sollicité en
  vrai), adjacences déclarées entre eux, quelques centaines d'habitants au
  total répartis sur les 5 mondes, scheduler automatique activé (tick toutes
  les 5-10s par monde), fenêtre d'observation ~10-15 minutes (~100 ticks par
  monde).
- **Peuplement initial via l'API existante** (croisements `personnages`),
  pas d'insertion directe en base — le scénario doit passer par les mêmes
  chemins qu'un usage réel, sinon la mesure ne vaut rien.
- **Mesures collectées** :
  - latence par tick : temps de réponse si tick déclenché manuellement, ou
    écart entre `tick_actuel` observés successivement si on laisse le
    scheduler automatique piloter (le scénario retenu utilise le scheduler
    automatique — voir ci-dessus — donc mesure par observation, pas par appel
    bloquant) ;
  - contenu du champ `avertissements` de chaque réponse de tick (verrous
    destination en timeout, écritures échouées) ;
  - logs du conteneur `workplace_world_engine` pendant la fenêtre (grep
    `locked`, exceptions) ;
  - `docker stats` échantillonné pendant la fenêtre (CPU/mémoire).
- **Sortie** : un rapport court, en Markdown, avec les chiffres bruts et une
  lecture (y a-t-il eu contention, dérive, timeouts — pas d'interprétation
  Redis/RabbitMQ, cette décision revient à Sprint E). Le rapport est aussi
  résumé dans une mémoire projet, avec un lien vers le fichier complet.

## Risques / limites connues

- Un seul run de ~15 minutes ne prouve rien sur la tenue dans la durée
  (heures/jours) — explicitement accepté, cohérent avec l'échelle « modeste »
  choisie. Si les chiffres sont ambigus, un second run plus long reste une
  option à rouvrir avec l'utilisateur, pas une extension silencieuse de ce
  sprint.
- Le HP a hébergé par le passé des soucis d'espace disque au build (voir
  mémoire `regime-preuve-docker-differe`) — build sur le HP directement (pas
  ici), une seule brique à la fois.
- La dépendance `personnages` doit déjà tourner sur le HP pour que le
  peuplement fonctionne — à vérifier avant de lancer le scénario, pas supposé.

## Critères de succès

- `world-engine` `healthy` sur le HP, healthcheck vert, dans le dashboard
  comme les autres briques.
- Le scénario de charge s'exécute de bout en bout sans intervention manuelle
  une fois lancé.
- Le rapport contient des chiffres concrets (pas « ça a eu l'air fluide ») sur
  les 4 axes de l'objectif, suffisants pour que le prochain brainstorming
  Sprint E parte de faits plutôt que d'hypothèses.
