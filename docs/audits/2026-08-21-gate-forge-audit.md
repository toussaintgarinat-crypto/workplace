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
  `tour_utilisateur()` (accord_action.py:113-165) sont 100% synchrones, aucun `await` interne.
  Sous asyncio (Cœur mono-processus), aucune fenêtre de course n'existe entre la vérification
  et la mutation de l'état : un seul appel s'exécute jusqu'au bout avant qu'un autre ne
  reprenne la main. Pas de trouvaille.
- **Ordre `entretien_routage.activer` / `graphe_apprentissage.noter_usage` /
  `verifier_idempotence` (assistant.py:385-416)** — tout ce bloc s'exécute APRÈS le `await
  outils.executer(...)` (assistant.py:381), donc strictement après une exécution déjà décidée.
  Aucun chemin ne les atteint sans être passé par le gate en amont. Pas de trouvaille.
- **Isolation multi-utilisateur (`accord_action.cle`, accord_action.py:73-82)** — clé =
  (fil, personne), pas fil seul ; déjà corrigé et testé (ADR S222, `test_accord_action.py`
  cas Alice/Bob). Toujours vrai dans le code actuel. Pas de trouvaille.
- **Bypass co-agent (`core/coagent.py:192`)** — `outils.executer(nom, args, registre)` appelé
  directement, AUCUNE référence à `accord_action` dans tout le fichier. Confirme l'ADR : ce
  chemin n'a pas de tour de parole humain, comportement antérieur assumé, non couvert. Vérifié
  toujours vrai, pas retouché (hors périmètre explicite de ce sprint).

## Trouvailles

### Trouvaille 1 (Important) — `tour_utilisateur()` accorde sur un message vide

**Fichier** : `core/accord_action.py:148-165`

**Scénario** : `tour_utilisateur(fil, message)` est appelé sans condition à
`core/routers/assistant.py:223` sur CHAQUE requête `/assistant/chat`, avec
`dernier_user = ""` si aucun message `role == "user"` n'est trouvé dans la requête
(routers/assistant.py:202-208). Dans `tour_utilisateur`, un message vide ne matche pas
`est_refus("")` (le motif de refus ne matche rien sur une chaîne vide) — la méthode tombe
donc dans la branche qui ACCORDE toutes les demandes en attente (accord_action.py:162-165),
même si aucun humain n'a réellement parlé. Ça recrée, pour ce cas précis, exactement le trou
que S222 a fermé : un accord produit sans qu'un vrai tour de parole humain ne se soit
intercalé. Aucun appelant connu n'envoie aujourd'hui une requête avec un dernier message
utilisateur vide, mais rien dans le code ne l'empêche structurellement — c'est le genre de
garantie qui doit tenir par construction, pas par la discipline des appelants actuels (c'est
exactement la leçon de l'ADR S222 sur le drapeau SSE).

**Verdict** : Corrigée — Task 2.

### Trouvaille 2 (Important, documentation) — `core/mcp.py` sur-affirme la protection

**Fichier** : `core/mcp.py:14-19` (docstring du module)

**Scénario** : le docstring affirme *« La confirmation des actions (`confirme=true`) reste
EXIGÉE par `outils.executer` — on ne contourne aucun garde-fou »*. C'est trompeur :
`outils.executer`/`_executer` (`core/outils.py:506-538`) n'a AUCUNE référence à
`accord_action` — la seule vérification de `confirme` est **textuelle**, dans
`outils_communs._confirmation()` (déclenchée à `outils_communs.py:174-176`), qui refuse
seulement si `confirme` est absent. Un client MCP qui connaît la convention et passe
`confirme=true` dès le PREMIER appel (`core/mcp.py:95`, `tools/call` → `outils.executer`
direct) exécute immédiatement, sans jamais passer par `accord_action.REGISTRE` — exactement
le chemin que `docs/decisions/2026-08-09-gate-action-structurel.md` documente déjà comme
non couvert (« co-agent autonome et Gateway MCP … ne sont pas couverts »). Le code se comporte
comme l'ADR l'annonce ; c'est le commentaire LOCAL de `mcp.py` qui donne une fausse assurance
à qui le lit sans l'ADR sous les yeux.

**Verdict** : Corrigée (docstring) — Task 3. Aucun changement de comportement : ce chemin
reste un choix assumé, pas un trou à combler dans ce sprint.

## Verdict final

2 trouvailles Important trouvées et corrigées (Tasks 2 et 3). Aucune Critical. Les bypasses
co-agent/Gateway MCP déjà documentés par l'ADR S222 sont confirmés toujours vrais dans le
code actuel — non retouchés, hors périmètre explicite de ce sprint. Registre d'événements
généralisé (waterfall/serial) : non entamé, reste une piste pour un sprint séparé.

Statut : clôturé après Task 4 (suite complète verte) et Task 5 (revue indépendante).
