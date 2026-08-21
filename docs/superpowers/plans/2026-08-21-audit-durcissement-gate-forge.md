# Audit & durcissement du gate d'action Forge (S234) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auditer méthodiquement le pipeline du gate d'action Forge (`core/assistant.py:328-421`, `core/accord_action.py`, `core/guardrails_outils.py`) avec la grille waterfall/serial (veille deepseek-harness/Cordis), corriger les trouvailles réelles en TDD, et documenter le résultat — sans construire de registre d'événements généralisé.

**Architecture:** Aucun nouveau module. Un document d'audit versionné (`docs/audits/`) sert de trace du passage adversarial. Les deux trouvailles confirmées se corrigent in situ : un garde-fou dans `accord_action.Registre.tour_utilisateur()`, et un docstring corrigé dans `core/mcp.py` (avec un test de caractérisation qui fige le comportement MCP existant plutôt que de le changer).

**Tech Stack:** Python 3, pytest (style autonome `assert` + `asyncio.run`, cf. conventions déjà en place dans `core/test_*.py`).

## Global Constraints

- Les 26 tests existants du gate (`core/test_accord_action.py`, `core/test_gate_action_bout_en_bout.py`, `core/test_entretien_routage_hook.py`) plus les tests de `core/test_mcp.py` restent verts après **chaque** tâche.
- Commentaires en français, uniquement pour expliquer le *pourquoi* non-évident (convention déjà en place dans `accord_action.py`/`guardrails_outils.py`) — jamais pour décrire ce que le code dit déjà.
- Pas de registre d'événements généralisé dans ce sprint (non-objectif explicite de la spec `docs/superpowers/specs/2026-08-21-audit-durcissement-gate-forge-design.md`).
- Ne pas remettre en cause les bypasses déjà documentés et acceptés par `docs/decisions/2026-08-09-gate-action-structurel.md` (co-agent, Gateway MCP) — les vérifier et les documenter plus précisément, ne pas les combler.
- Toute exécution se fait depuis `core/` (`cd core && python3 -m pytest <fichier> -v`), comme le reste des tests du module.

---

### Task 1: Écrire le rapport d'audit

**Files:**
- Create: `docs/audits/2026-08-21-gate-forge-audit.md`

**Interfaces:**
- Produces: le document d'audit référencé par les Tasks 2 et 3 (trouvailles #1 et #2 ci-dessous), et par la Task 4 (verdict final).

Ce rapport consigne un passage déjà mené (lecture complète de `core/assistant.py:320-424`,
`core/accord_action.py`, `core/guardrails_outils.py`, `core/mcp.py`, `core/coagent.py`,
`core/routers/assistant.py:195-230`) avec la grille à 3 questions de la spec (court-circuit /
ordre / effet réel vs apparent), maillon par maillon.

- [ ] **Step 1: Créer le dossier et le fichier d'audit avec le contenu complet**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add docs/audits/2026-08-21-gate-forge-audit.md
git commit -m "$(cat <<'EOF'
docs(gate-forge): audit S234 du pipeline du gate d'action

Passage adversarial waterfall/serial sur assistant.py/accord_action.py/
guardrails_outils.py/mcp.py. 2 trouvailles Important (accord sur message
vide, docstring mcp.py trompeur) ; bypasses co-agent/MCP déjà documentés
par l'ADR S222 confirmés inchangés.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016wGw728KrpVYw16vEiz5kx
EOF
)"
```

---

### Task 2: Durcir `tour_utilisateur()` contre un tour de parole vide

**Files:**
- Modify: `core/accord_action.py:148-165`
- Test: `core/test_accord_action.py`

**Interfaces:**
- Consumes: `accord_action.Registre` (déjà défini, `core/accord_action.py:96-193`) — la
  fixture `reg` (`core/test_accord_action.py:15-17`) et la constante `ARGS`
  (`core/test_accord_action.py:20`) existent déjà.
- Produces: `Registre.tour_utilisateur(fil: str, message: str) -> None` garde sa signature ;
  seul son comportement sur un `message` vide/blanc change (ne fait plus rien, au lieu
  d'accorder).

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à la fin de `core/test_accord_action.py` :

```python
def test_tour_utilisateur_message_vide_n_accorde_rien(reg):
    """Un message vide n'est PAS un tour de parole humain : une demande en attente doit
    rester en attente, pas devenir un accord gratuit. Sans ce garde-fou, un appelant qui
    (par bug ou par surface future) atteint `tour_utilisateur` avec un dernier message
    utilisateur vide rouvre exactement le trou que S222 a fermé."""
    reg.demander("fil-1", "mail_envoyer", ARGS)
    reg.tour_utilisateur("fil-1", "")
    ok, msg = reg.consommer("fil-1", "mail_envoyer", {**ARGS, "confirme": True})
    assert ok is False
    assert "n'a pas encore répondu" in msg
```

- [ ] **Step 2: Vérifier que le test échoue**

Run: `cd core && python3 -m pytest test_accord_action.py::test_tour_utilisateur_message_vide_n_accorde_rien -v`
Expected: FAIL — `assert ok is False` échoue car `ok` vaut `True` (le message vide accorde
la demande dans le code actuel).

- [ ] **Step 3: Corriger `tour_utilisateur`**

Remplacer dans `core/accord_action.py` (lignes 148-165) :

```python
    def tour_utilisateur(self, fil: str, message: str) -> None:
        """Un message utilisateur est arrivé : les demandes en attente deviennent des
        accords — sauf s'il s'agit d'un refus explicite, auquel cas elles disparaissent.

        C'est ICI que se joue toute la garantie : sans passage par cette méthode, aucune
        demande ne devient jamais un accord, et donc aucun `confirme=true` ne passe."""
        self._purger(fil)
        self._lectures.pop(fil, None)  # nouveau tour : les compteurs de lecture repartent
        en_cours = self._demandes.get(fil) or []
        if not en_cours:
            return
        if est_refus(message or ""):
            self._demandes[fil] = []
            return
        maintenant = time.time()
        for d in en_cours:
            d.accordee = True
            d.emise_a = maintenant  # le TTL court à partir de l'accord, pas de la demande
```

par :

```python
    def tour_utilisateur(self, fil: str, message: str) -> None:
        """Un message utilisateur est arrivé : les demandes en attente deviennent des
        accords — sauf s'il s'agit d'un refus explicite, auquel cas elles disparaissent.

        C'est ICI que se joue toute la garantie : sans passage par cette méthode, aucune
        demande ne devient jamais un accord, et donc aucun `confirme=true` ne passe.

        Un message vide N'EST PAS un tour de parole (S234, audit gate-forge) : sans ce
        garde-fou, un appel qui atteint cette méthode sans avoir extrait de VRAI message
        utilisateur accordait quand même toutes les demandes en attente."""
        if not (message or "").strip():
            return
        self._purger(fil)
        self._lectures.pop(fil, None)  # nouveau tour : les compteurs de lecture repartent
        en_cours = self._demandes.get(fil) or []
        if not en_cours:
            return
        if est_refus(message or ""):
            self._demandes[fil] = []
            return
        maintenant = time.time()
        for d in en_cours:
            d.accordee = True
            d.emise_a = maintenant  # le TTL court à partir de l'accord, pas de la demande
```

- [ ] **Step 4: Vérifier que le nouveau test passe**

Run: `cd core && python3 -m pytest test_accord_action.py::test_tour_utilisateur_message_vide_n_accorde_rien -v`
Expected: PASS

- [ ] **Step 5: Vérifier qu'aucun test existant n'a régressé**

Run: `cd core && python3 -m pytest test_accord_action.py test_gate_action_bout_en_bout.py test_entretien_routage_hook.py -v`
Expected: tous PASS (aucun test existant n'appelle `tour_utilisateur` avec une chaîne vide —
vérifié par grep avant cette tâche).

- [ ] **Step 6: Commit**

```bash
git add core/accord_action.py core/test_accord_action.py
git commit -m "$(cat <<'EOF'
fix(gate-forge): tour_utilisateur() n'accorde plus sur un message vide

Un message vide ne matchait aucun motif de refus et tombait donc dans la
branche d'accord — un appel sans vrai message utilisateur accordait
quand même toutes les demandes en attente. Trouvaille #1, audit S234.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016wGw728KrpVYw16vEiz5kx
EOF
)"
```

---

### Task 3: Corriger le docstring trompeur de `core/mcp.py`

**Files:**
- Modify: `core/mcp.py:1-20`
- Test: `core/test_mcp.py`

**Interfaces:**
- Consumes: `mcp.traiter(corps: dict, registre) -> dict | None` (déjà défini,
  `core/mcp.py:68-102`) ; le faux registre `_registre()` et le runner `_t()`
  (`core/test_mcp.py:20-38`) existent déjà.
- Produces: aucun changement de comportement — ce test FIGE (characterization test) le
  comportement actuel plutôt que d'en introduire un nouveau.

- [ ] **Step 1: Écrire le test de caractérisation (déjà vert, pas un cycle rouge)**

Ce n'est pas un bugfix comportemental : le docstring ment, le code lui reste correct vis-à-vis
de l'ADR. Le test suivant DOIT déjà passer avant toute modification — il documente et
verrouille ce que Task 1 a vérifié, pour qu'un futur changement de ce comportement soit
délibéré plutôt qu'accidentel. Ajouter à la fin de `core/test_mcp.py` :

```python
def test_tools_call_action_confirmee_bypasse_le_registre_accord():
    """MCP ne passe JAMAIS par accord_action.REGISTRE (S222) : `tools/call` appelle
    `outils.executer` directement. C'est un choix assumé (ADR
    docs/decisions/2026-08-09-gate-action-structurel.md), pas un oubli — ce test fige ce
    comportement pour qu'un futur changement soit délibéré, pas accidentel."""
    capte = {}

    async def faux_executer(nom, args, registre):
        capte["nom"], capte["args"] = nom, args
        return json.dumps({"ok": True})

    orig = outils.executer
    outils.executer = faux_executer
    try:
        rep = _t({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                  "params": {"name": "calcul_etat_muscle",
                             "arguments": {"reveiller": True, "confirme": True}}})
    finally:
        outils.executer = orig
    # Exécuté immédiatement malgré `action: True` et SANS accord préalable dans le
    # registre : c'est le chemin documenté comme non couvert par le gate.
    assert capte["nom"] == "calcul_etat_muscle"
    assert capte["args"] == {"reveiller": True, "confirme": True}
    assert rep["result"]["isError"] is False
```

- [ ] **Step 2: Vérifier que le test passe déjà (avant tout changement)**

Run: `cd core && python3 -m pytest test_mcp.py::test_tools_call_action_confirmee_bypasse_le_registre_accord -v`
Expected: PASS — confirme que le comportement décrit est bien celui du code actuel.

- [ ] **Step 3: Corriger le docstring du module**

Remplacer dans `core/mcp.py` (lignes 14-19) :

```python
Transport : Streamable HTTP — un POST JSON-RPC sur `/mcp`. Méthodes : `initialize`,
`tools/list`, `tools/call`, `ping`. Le co-agent planificateur exécutif est exposé comme un
outil ordinaire (`coagent_lancer`) : un client MCP peut donc déléguer une tâche multi-briques
autonome. Sécurité : clé `MCP_KEY` (header) si définie, kill-switch `MCP_ACTIF`. La
confirmation des actions (`confirme=true`) reste EXIGÉE par `outils.executer` — on ne
contourne aucun garde-fou : un agent autonome doit la passer explicitement.
"""
```

par :

```python
Transport : Streamable HTTP — un POST JSON-RPC sur `/mcp`. Méthodes : `initialize`,
`tools/list`, `tools/call`, `ping`. Le co-agent planificateur exécutif est exposé comme un
outil ordinaire (`coagent_lancer`) : un client MCP peut donc déléguer une tâche multi-briques
autonome. Sécurité : clé `MCP_KEY` (header) si définie, kill-switch `MCP_ACTIF`.

⚠ Le gate d'action structurel (S222, `accord_action.REGISTRE`) NE COUVRE PAS ce chemin :
`tools/call` appelle `outils.executer` directement, sans jamais passer par `converser` ni
par le registre d'accords (audit S234). Un client qui passe `confirme=true` dès le premier
appel l'exécute immédiatement — seule la garde TEXTUELLE de `_confirmation()`
(`outils_communs.py`) s'applique, et elle ne protège qu'un LLM qui ignore encore qu'il doit
passer `confirme=true`, pas un appelant qui le sait déjà. Choix assumé, documenté dans
`docs/decisions/2026-08-09-gate-action-structurel.md` : un client MCP est par nature un
appelant autonome sans tour de parole humain à intercaler. Ne pas lire cette absence comme
un oubli.
"""
```

- [ ] **Step 4: Vérifier que le test passe toujours et qu'aucun test MCP n'a régressé**

Run: `cd core && python3 -m pytest test_mcp.py -v`
Expected: tous PASS (le docstring n'affecte aucun comportement testé).

- [ ] **Step 5: Commit**

```bash
git add core/mcp.py core/test_mcp.py
git commit -m "$(cat <<'EOF'
docs(gate-forge): corrige le docstring trompeur de mcp.py sur le gate

Le docstring affirmait que confirme=true restait EXIGÉ par
outils.executer — faux, la vérification est purement textuelle et MCP
ne passe jamais par accord_action.REGISTRE. Comportement inchangé (choix
assumé par l'ADR S222), seul le commentaire était trompeur. Ajoute un
test de caractérisation qui fige ce comportement. Trouvaille #2, audit
S234.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016wGw728KrpVYw16vEiz5kx
EOF
)"
```

---

### Task 4: Suite complète verte + clôture de l'audit

**Files:**
- Modify: `docs/audits/2026-08-21-gate-forge-audit.md` (aucun changement de contenu attendu,
  juste confirmation que le statut « clôturé » tient — cf. Step 2)

**Interfaces:**
- Consumes: tous les fichiers de test touchés par les Tasks 2 et 3.

- [ ] **Step 1: Lancer toute la suite du gate + MCP**

Run: `cd core && python3 -m pytest test_accord_action.py test_gate_action_bout_en_bout.py test_entretien_routage_hook.py test_mcp.py -v`
Expected: tous PASS, y compris le nouveau test de Task 2
(`test_tour_utilisateur_message_vide_n_accorde_rien`) et celui de Task 3
(`test_tools_call_action_confirmee_bypasse_le_registre_accord`).

- [ ] **Step 2: Confirmer que le verdict final du rapport d'audit reste exact**

Relire `docs/audits/2026-08-21-gate-forge-audit.md`, section « Verdict final » : les deux
trouvailles sont bien marquées corrigées, aucune modification de contenu nécessaire (déjà
écrit correctement en Task 1). Si un écart apparaît entre le rapport et l'état réel du code
à ce stade, corriger le rapport avant de continuer — jamais l'inverse.

- [ ] **Step 3: Commit (si le rapport a été retouché à l'étape précédente ; sinon, passer à la Task 5 sans commit)**

```bash
git add docs/audits/2026-08-21-gate-forge-audit.md
git commit -m "$(cat <<'EOF'
docs(gate-forge): ajuste le verdict final de l'audit S234 après vérif

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016wGw728KrpVYw16vEiz5kx
EOF
)"
```

---

### Task 5: Revue indépendante avant push

**Files:** aucun fichier propre à cette tâche — porte sur le diff cumulé des Tasks 1 à 4.

- [ ] **Step 1: Lancer la revue**

Invoquer le skill `code-review` (ou `security-review`) sur le diff complet du sprint
(`git diff main...HEAD` une fois toutes les tâches précédentes commitées sur une branche, ou
directement sur `main` si le travail a été fait dessus).

- [ ] **Step 2: Traiter chaque trouvaille de la revue**

Pour toute trouvaille Critical ou Important remontée : cycle TDD (test rouge → correctif →
test vert), suivant le même patron que Task 2. Pour toute trouvaille jugée non pertinente :
consigner pourquoi dans `docs/audits/2026-08-21-gate-forge-audit.md` (section à ajouter
« Revue finale ») plutôt que de l'ignorer silencieusement.

- [ ] **Step 3: Suite complète verte après correctifs de revue**

Run: `cd core && python3 -m pytest test_accord_action.py test_gate_action_bout_en_bout.py test_entretien_routage_hook.py test_mcp.py -v`
Expected: tous PASS.

- [ ] **Step 4: Commit des correctifs de revue (s'il y en a)**

```bash
git add -A
git commit -m "$(cat <<'EOF'
fix(gate-forge): correctifs de la revue finale S234

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016wGw728KrpVYw16vEiz5kx
EOF
)"
```

---

### Task 6: Push sur `main`

**Files:** aucun.

- [ ] **Step 1: Vérifier l'état de la branche**

Run: `git status && git log --oneline -8`
Expected: working tree propre, les commits des Tasks 1-5 présents en tête.

- [ ] **Step 2: Push**

```bash
git push origin main
```

- [ ] **Step 3: Vérifier**

Run: `git status`
Expected: `Your branch is up to date with 'origin/main'.`

---

## Note pour la suite

Si du temps reste après la Task 6 : esquisser (design, pas implémentation) le registre
d'événements généralisé waterfall/serial pour le pipeline du gate — non-objectif de ce
sprint, à valider via le skill `brainstorming` avant tout code, comme un sprint séparé.
