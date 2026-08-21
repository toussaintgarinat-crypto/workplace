# Audit du gate d'action Forge — S234 (2026-08-21)

## Méthode

Passage adversarial sur la chaîne appelée depuis `core/assistant.py:328-421` :

`guardrail.before_call` → `outils.est_action` → `accord_action.REGISTRE.demander`/`.consommer`
→ `outils.executer` → `guardrail.after_call` → `entretien_routage.activer` →
`graphe_apprentissage.noter_usage` → `guardrail.verifier_idempotence`

Pour chaque maillon : (1) court-circuit possible ? (2) ordre garanti ? (3) effet réel ou
seulement apparent (drapeau d'affichage sans conséquence structurelle) ?

## Maillons vérifiés sans trouvaille

- **`guardrail.before_call` (guardrails_outils.py:71-98)** — bloque AVANT tout appel réel
  (`assistant.py:364-370` court-circuite `outils.executer` sur `block`/`halt`). Effet réel,
  pas apparent. RAS. Note mineure hors périmètre : la branche `halt` n'est jamais produite par
  `before_call` (seul `block`/`warn`/`allow` sont retournés) — code mort défensif, pas un
  risque, pas de correctif dans ce sprint (YAGNI).
- **Concurrence sur `accord_action.REGISTRE`** — `demander()`, `consommer()`,
  `tour_utilisateur()` (accord_action.py:113-173) sont 100% synchrones, aucun `await` interne :
  chacune s'exécute jusqu'au bout avant qu'un autre appel ne reprenne la main. La boucle
  englobante SUSPEND bien entre `consommer()` (assistant.py:347) et `outils.executer()`
  (assistant.py:381) — au `yield` de assistant.py:360 — mais `consommer()` retire l'accord de
  `self._demandes[fil]` de façon atomique AVANT cette suspension (accord_action.py:133-135) :
  un accord consommé ne peut donc pas être dépensé une seconde fois par un appel concurrent qui
  reprendrait la main pendant la suspension. Pas de trouvaille.
- **Ordre `entretien_routage.activer` / `graphe_apprentissage.noter_usage` /
  `verifier_idempotence` (assistant.py:385-416)** — tout ce bloc s'exécute APRÈS le `await
  outils.executer(...)` (assistant.py:381), donc strictement après une exécution déjà décidée.
  Aucun chemin ne les atteint sans être passé par le gate en amont. Pas de trouvaille.
- **Isolation multi-utilisateur (`accord_action.cle`, accord_action.py:73-82)** — clé =
  (fil, personne), pas fil seul ; déjà corrigé et testé (ADR S222, `test_accord_action.py`
  cas Alice/Bob). Toujours vrai dans le code actuel. Pas de trouvaille.

## Trouvailles

### Trouvaille 1 (Important) — `tour_utilisateur()` accorde sur un message vide

**Fichier** : `core/accord_action.py:148-173`

**Scénario** : `tour_utilisateur(fil, message)` est appelé sans condition à
`core/routers/assistant.py:223` sur CHAQUE requête `/assistant/chat`, avec
`dernier_user = ""` si aucun message `role == "user"` n'est trouvé dans la requête
(routers/assistant.py:202-208). Dans `tour_utilisateur`, un message vide ne matche pas
`est_refus("")` (le motif de refus ne matche rien sur une chaîne vide) — la méthode tombe
donc dans la branche qui ACCORDE toutes les demandes en attente (accord_action.py:170-173),
même si aucun humain n'a réellement parlé. Ça recrée, pour ce cas précis, exactement le trou
que S222 a fermé : un accord produit sans qu'un vrai tour de parole humain ne se soit
intercalé. Aucun appelant connu n'envoie aujourd'hui une requête avec un dernier message
utilisateur vide, mais rien dans le code ne l'empêche structurellement — c'est le genre de
garantie qui doit tenir par construction, pas par la discipline des appelants actuels (c'est
exactement la leçon de l'ADR S222 sur le drapeau SSE).

**Verdict** : Corrigée — Task 2.

### Trouvaille 2 (Important, documentation) — `core/mcp.py` sur-affirme la protection

**Fichier** : `core/mcp.py:19-28` (docstring du module)

**Scénario** : le docstring affirme *« La confirmation des actions (`confirme=true`) reste
EXIGÉE par `outils.executer` — on ne contourne aucun garde-fou »*. C'est trompeur :
`outils.executer`/`_executer` (`core/outils.py:506-538`) n'a AUCUNE référence à
`accord_action` — la seule vérification de `confirme` est **textuelle**, dans
`outils_communs._confirmation()` (déclenchée à `outils_communs.py:175-176`), qui refuse
seulement si `confirme` est absent. Un client MCP qui connaît la convention et passe
`confirme=true` dès le PREMIER appel (`core/mcp.py:104`, `tools/call` → `outils.executer`
direct) exécute immédiatement, sans jamais passer par `accord_action.REGISTRE` — exactement
le chemin que `docs/decisions/2026-08-09-gate-action-structurel.md` documente déjà comme
non couvert (« co-agent autonome et Gateway MCP … ne sont pas couverts »). Le code se comporte
comme l'ADR l'annonce ; c'est le commentaire LOCAL de `mcp.py` qui donne une fausse assurance
à qui le lit sans l'ADR sous les yeux.

**Verdict** : Corrigée (docstring) — Task 3. Aucun changement de comportement : ce chemin
reste un choix assumé, pas un trou à combler dans ce sprint.

### Trouvaille 3 (Important, différée) — le filtre du co-agent n'est appliqué qu'à l'offre, pas à l'exécution

**Fichier** : `core/coagent.py:60-72` (offre) et `core/coagent.py:192` (exécution)

**Scénario** : `_outils_lecture()` (coagent.py:60-72) retire bien toute capacité `action: true`
de la trousse OFFERTE au LLM du co-agent — c'est le vrai garde-fou souverain documenté dans le
docstring du module ("le co-agent est LECTURE SEULE"). Mais `coagent.py:192` exécute
`outils.executer(nom, args, registre)` avec le `nom` renvoyé par le LLM, SANS revérifier que ce
nom fait partie de la trousse offerte. `outils.executer`/`_executer` (core/outils.py) ne fait
lui-même aucun contrôle d'allowlist par nom — contrairement à `core/mcp.py:101`
(`tools/call`), qui valide explicitement `nom` contre `lister_outils(registre)` avant tout
dispatch. Un LLM qui émettrait un nom d'outil hors de sa trousse (action incluse) verrait donc
cet appel s'exécuter — sous réserve, comme pour le contournement MCP de la Trouvaille 2, qu'il
pense aussi à passer `confirme=true` : la garde textuelle de `_confirmation()`/des dispatchers
de domaine s'applique ici aussi, elle n'est simplement pas doublée d'un contrôle d'allowlist.

**Verdict** : Différée — hors périmètre de ce sprint. L'ADR S222
(`docs/decisions/2026-08-09-gate-action-structurel.md:99-103`) note déjà que "le co-agent
mériterait de ne pas pouvoir exécuter d'action confirmée du tout" et que c'est "un sprint à
part". Ce correctif, quand il sera fait, est court : valider `nom` contre la trousse offerte
avant `outils.executer` à `coagent.py:192`, même motif que `mcp.py:101`.

## Verdict final

3 trouvailles Important trouvées (2 corrigées Tasks 2 et 3, 1 différée). Aucune Critical. Les
bypasses co-agent/Gateway MCP déjà documentés par l'ADR S222 sont confirmés toujours vrais dans
le code actuel. Le bypass Gateway MCP reste non retouché, hors périmètre explicite de ce
sprint. Le bypass co-agent, lui, s'avère plus précis qu'annoncé : le filtre agit à l'offre
(coagent.py:60-72) mais pas à l'exécution (coagent.py:192) — voir Trouvaille 3 ci-dessus,
différée avec renvoi à l'ADR S222 (`docs/decisions/2026-08-09-gate-action-structurel.md:99-103`).
Registre d'événements généralisé (waterfall/serial) : non entamé, reste une piste pour un
sprint séparé.

Statut : clôturé. Task 4 (suite complète verte, 60/60) confirmée sans écart. Task 5 (revue
finale indépendante) a trouvé ce rapport lui-même incomplet (trouvaille co-agent différée
ci-dessus, ajoutée après coup) et ses références de ligne obsolètes (corrigées ci-dessus) — le
code des Tasks 2/3 n'a pas été remis en cause.
