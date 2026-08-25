# World Engine — Sprint E, scheduler parallélisé

**Date** : 2026-08-25
**Statut** : design approuvé, plan d'implémentation à venir

## Contexte

Suite de [world-engine-mesure-charge-design](2026-08-25-world-engine-mesure-charge-design.md)
et de son rapport chiffré committé
(`docs/superpowers/reports/2026-08-25-world-engine-mesure-charge-rapport.md`).
La mesure de charge LIVE a identifié une cause structurelle, lisible dans le
code sans extrapolation : `main.py:_boucle_scheduler` (`main.py:371-387`) est
une seule boucle `asyncio` qui `await` chaque monde dû **en série**
(`for due in dues: await horloge_moteur.executer_tick(...)`). Avec
`SCHEDULER_INTERVALLE_S = 5` et 5 mondes actifs, l'écart moyen réel mesuré est
de 5,698s (+14,0% de dérive systématique, identique à ~10⁻⁴ près sur les 5
mondes). Conséquence directe du même mécanisme : deux mondes ne peuvent
JAMAIS tiquer concurremment sous le scheduler actuel, ce qui rend la
contention de verrou destination du Sprint D (`horloge_moteur.
_acquerir_verrou_destination`) inatteignable en usage normal — mesurée
séparément en rafale manuelle (104 avertissements/100 ticks concurrents,
médiane 1,22s, p95 6,39s).

Ce document conçoit le premier sujet retenu pour Sprint E parmi ceux ouverts
par le rapport (dérive du scheduler, angle mort d'observabilité, arbitrage
Redis/RabbitMQ) : corriger la dérive en parallélisant l'exécution des ticks
dus dans chaque passage du scheduler. Décision utilisateur explicite
(brainstorming) : les deux autres sujets ouverts par le rapport sont traités
ci-dessous en Hors périmètre, pas ignorés — juste différés.

## Objectif

1. Éliminer la dérive de tick en remplaçant la boucle séquentielle par une
   exécution concurrente des mondes dus dans un même passage du scheduler.
2. Combler l'angle mort d'observabilité que ce changement rend
   opérationnellement pertinent : le scheduler jette aujourd'hui
   silencieusement `avertissements` (verrou destination) et les exceptions de
   tick (`except Exception: continue`) — une fois deux mondes capables de
   tiquer concurremment en production, ces deux catégories doivent être
   visibles (`docker logs`), pas seulement en rafale manuelle de mesure.

## Hors périmètre

- Arbitrage Redis vs RabbitMQ pour une future mise à l'échelle — pas
  nécessaire au volume mesuré (CPU médian 1,2%, SQLite sans contention visible
  sur ~20 min de charge cumulée). Reste à trancher dans un futur
  brainstorming si le volume réel croît.
- Comportement au-delà de 5 mondes actifs simultanément — non mesuré, la
  parallélisation du scheduler résout la cause structurelle par construction
  (la durée d'un passage devient `max(durées)` au lieu de `Σ(durées)`, donc ne
  dépend plus linéairement du nombre de mondes dus), mais ce n'est vérifié
  empiriquement qu'à l'échelle déjà mesurée (5 mondes) — voir Validation LIVE.
- Toute évolution du mécanisme de verrou destination du Sprint D lui-même
  (`horloge_moteur._acquerir_verrou_destination`, `VERROU_DESTINATION_TIMEOUT_S`) :
  son comportement (retry au tick suivant, aucune corruption) reste inchangé,
  seule sa visibilité change.
- Persistance des avertissements en base (table dédiée, endpoint
  d'historique) — décision utilisateur explicite : logging standard
  (`docker logs`) suffit à ce stade, pas de besoin exprimé de requêtabilité
  au-delà de la rétention des logs Docker.

## Décisions de conception

- **`asyncio.gather()` sur chaque passage**, pas une tâche `asyncio`
  indépendante par monde ni un pool de workers borné (deux options écartées en
  brainstorming). Un seul réveil toutes les `SCHEDULER_INTERVALLE_S`, mais
  tous les mondes dus dans ce passage tiquent en parallèle au lieu de
  s'additionner. Changement minimal, cohérent avec l'architecture actuelle
  (in-process, pas de queue externe — déjà le choix assumé du docstring de
  `_boucle_scheduler`). Un pool borné (sémaphore) serait de la
  sur-ingénierie au volume mesuré (5 mondes) ; des tâches indépendantes par
  monde demanderaient un cycle de vie explicite (créer/annuler à la
  création/suppression/pause d'une horloge) non justifié par le besoin actuel.
- **Isolation d'erreur préservée** : chaque tick est enveloppé
  individuellement (`_executer_et_consigner`), qui attrape toute exception
  avant qu'elle ne remonte à `gather` — aucune exception n'atteint donc
  jamais `asyncio.gather` lui-même, ce qui évite d'avoir à s'appuyer sur
  `return_exceptions=True` (dont le comportement par défaut, sans lui,
  propagerait la première exception à l'appelant sans annuler les autres
  tâches déjà lancées — un mode dégradé qu'on évite en amont plutôt qu'en
  s'y fiant). Une erreur sur un monde n'interrompt jamais la boucle ni les
  autres mondes, comme aujourd'hui.
- **Logging standard Python**, aligné sur le motif déjà utilisé dans
  `calcul/main.py:34` et `restaurant/main.py`
  (`logging.getLogger("world-engine")`). Avertissements de verrou en
  `WARNING` (un par entrée de `resultat["avertissements"]`, avec `monde_id`),
  exceptions de tick en `ERROR` via `_log.exception` (traceback inclus).
  Aucune nouvelle dépendance.

Esquisse du changement (`main.py`) :

```python
_log = logging.getLogger("world-engine")

async def _executer_et_consigner(monde_id: str, cle_api: str) -> None:
    try:
        resultat = await horloge_moteur.executer_tick(monde_id, cle_api)
        for avert in resultat.get("avertissements", []):
            _log.warning("monde=%s %s", monde_id, avert)
    except Exception:
        _log.exception("tick en échec monde=%s", monde_id)

async def _boucle_scheduler():
    while True:
        await asyncio.sleep(SCHEDULER_INTERVALLE_S)
        maintenant = datetime.now(timezone.utc).isoformat()
        try:
            dues = stockage_horloge.horloges_actives_a_declencher(maintenant)
        except Exception:
            continue
        await asyncio.gather(*(_executer_et_consigner(d["monde_id"], d["cle_api"]) for d in dues))
```

## Tests

Nouveau test unitaire (mock `horloge_moteur.executer_tick`) vérifiant :
- N mondes dus dans le même passage s'exécutent concurremment (durée totale
  ≈ `max(durées mockées)`, pas `Σ(durées)`) ;
- un avertissement retourné par un tick est bien loggé en `WARNING` avec le
  `monde_id` concerné ;
- une exception levée par un tick est loggée en `ERROR` sans empêcher les
  autres mondes du même passage de s'exécuter ni d'interrompre la boucle.

## Validation LIVE

Une fois codé/testé/revu et poussé : redéploiement sur le HP
(`192.168.1.89:6230`, déjà configuré depuis la mesure de charge) et rejeu du
même scénario que le rapport du 2026-08-25 avec
`scripts/mesure_charge_world_engine.py` (5 mondes fédérés, scheduler
automatique, fenêtre d'observation comparable). Critère de succès : l'écart
moyen non biaisé entre ticks redescend proche de `SCHEDULER_INTERVALLE_S`
(dérive proche de 0%, contre +14,0% avant correctif) sur les 5 mondes
actuels, et les logs du conteneur contiennent des avertissements de verrou
lisibles si la fenêtre en produit (au lieu d'être invisibles comme avant).

## Risques / limites connues

- La parallélisation rend la contention de verrou destination (Sprint D)
  atteignable en usage normal pour la première fois — comportement déjà
  documenté et assumé (retry au tick suivant, aucune corruption), mais c'est
  un changement de régime réel, pas seulement de visibilité. À surveiller
  dans les logs après déploiement LIVE.
- La mesure de validation reste à l'échelle déjà connue (5 mondes) — elle
  prouve que la cause structurelle identifiée est corrigée, pas le
  comportement à une échelle non encore mesurée (dizaines de mondes).
