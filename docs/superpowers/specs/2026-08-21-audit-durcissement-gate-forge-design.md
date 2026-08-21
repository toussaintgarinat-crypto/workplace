# Audit & durcissement du gate d'action Forge (S234)

## Contexte

Veille sur `deepseek-ai/deepseek-harness` (framework Cordis) : le pipeline d'exécution
d'outils y est un registre d'événements explicite — `tools/pre-execute` → `tools/execute` →
`tools/post-execute`, en **waterfall** (chaque listener doit appeler `next()` pour déléguer),
avec un événement **serial** distinct (`agent/turn-stopping`, sans `next()`) pour un arrêt dur.
Mémoire : `veille-deepseek-harness-cordis-plugin.md`.

Le gate d'action du Cœur (`docs/decisions/2026-08-09-gate-action-structurel.md`, S222) ferme
déjà un vrai trou de sécurité en production, et documente lui-même ce qu'il garantit et ne
garantit pas. Mais sa mise en œuvre reste une **séquence codée en dur** dans la boucle
d'inférence (`core/assistant.py:328-421`) : `guardrail.before_call` → gate (`demander`/
`consommer`) → `outils.executer()` → `guardrail.after_call` → routage entretien → note du
graphe d'apprentissage → `verifier_idempotence`. Chaque étape est un appel de fonction nommé,
pas un callback enregistré dans une liste — il n'existe aucun point où une nouvelle étape de
contrôle s'insère sans modifier cette fonction.

Ce sprint utilise le vocabulaire waterfall/serial comme **grille d'audit** sur ce pipeline
existant : pas pour le juger insuffisant a priori, mais pour vérifier méthodiquement, maillon
par maillon, qu'aucune étape ne peut être court-circuitée, appelée dans le mauvais ordre, ou
déclenchée sans que l'étape précédente ait réellement produit son effet bloquant.

## Non-objectifs

- **Pas de registre d'événements généralisé dans ce sprint.** Remplacer la séquence codée en
  dur par un vrai dispatch pluggable (waterfall + serial) est une piste notée, pas un
  livrable : si l'audit et les correctifs de sécurité occupent tout le cycle, la
  généralisation devient un sprint séparé. Décision explicite de l'utilisateur (2026-08-21) :
  l'audit prime.
- **Pas de remise en cause des limites déjà assumées et documentées par l'ADR S222** —
  notamment : le co-agent autonome et la Gateway MCP contournent le gate car ils n'ont pas de
  tour de parole humain (comportement antérieur, assumé) ; le Cœur ne fait aucune analyse
  sémantique du « oui » de l'utilisateur ; le registre est en mémoire vive, perdu au redémarrage.
  Ces points sont des limites connues, pas des trous à combler ici — l'audit part de ce que
  l'ADR affirme et vérifie que c'est toujours vrai dans le code actuel, il ne rouvre pas ces
  décisions.
- **Pas de changement de comportement observable côté utilisateur** si aucune faille n'est
  trouvée. Ce sprint peut légitimement se conclure par « rien à corriger, voici la preuve » —
  un audit qui ne trouve rien n'est pas un échec s'il est mené sérieusement.

## Méthode d'audit

Passage adversarial, maillon par maillon, sur toute la chaîne appelée depuis
`core/assistant.py:328-421` :

`guardrail.before_call` → `outils.est_action` → `accord_action.REGISTRE.demander` /
`.consommer` → `outils.executer` → `guardrail.after_call` → `entretien_routage.activer` →
`graphe_apprentissage.noter_usage` → `guardrail.verifier_idempotence`

Pour chaque maillon, trois questions fixes :

1. **Court-circuit** — existe-t-il un chemin d'appel (co-agent, Gateway MCP, un futur appelant,
   une route existante) qui atteint `outils.executer()` sans être passé par ce maillon ?
2. **Ordre** — le code garantit-il que ce maillon s'exécute strictement après celui dont il
   dépend (ex : `consommer()` avant `executer()`, jamais l'inverse), y compris sous
   concurrence (plusieurs tours/fils en parallèle sur le même processus) ?
3. **Effet réel vs effet apparent** — un refus/blocage de ce maillon empêche-t-il vraiment
   l'exécution, ou seulement l'affichage (le piège originel de S222 : un simple drapeau SSE
   sans effet structurel) ?

Chaque trouvaille est consignée avec fichier:ligne, scénario d'exploitation concret, et
classée Critical / Important / mineure — même format que les revues finales précédentes
(S222, S227, S228).

## Méthode de correction

TDD strict par trouvaille retenue : un test qui la reproduit (rouge) avant le correctif
(vert). Les 26 tests existants (`core/test_accord_action.py`,
`core/test_gate_action_bout_en_bout.py`, `core/test_entretien_routage_hook.py`) restent verts
en continu — ce sont eux qui, neutralisés, avaient initialement prouvé la valeur du gate
(ADR S222 : 5 tests de sécurité échouent, 3 de non-régression continuent de passer).

## Revue finale

Une fois les correctifs posés, passage de revue indépendant (skill `code-review` ou
`security-review`) sur le diff complet avant push — pour rattraper ce qu'un audit en solo
pourrait manquer, comme sur les sprints précédents où la revue finale a trouvé des Critical
que l'implémentation avait ratés.

## Definition of done

- Audit documenté : chaque maillon examiné, verdict explicite pour chaque trouvaille
  (corrigée / non exploitable / différée avec raison).
- Tests nouveaux (un par trouvaille corrigée) + tous les tests existants verts.
- Revue finale indépendante faite, ses trouvailles traitées.
- Poussé sur `main`. Statut LIVE HP hors scope (régime de preuve différé, cf.
  `regime-preuve-docker-differe.md`).
- Si du temps reste après tout ce qui précède : esquisse (design, pas implémentation) du
  registre d'événements généralisé, à valider avant tout code.
