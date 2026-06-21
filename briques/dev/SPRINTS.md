# Brique `dev` — feuille de route en sprints

Lignée principale Workplace (suite de S85 = resto v0.11.0). Chaque sprint est autonome,
prouvable hors-ligne, et empile sur le **filet git** posé en S86.

> Ordre choisi par **dépendance + valeur + risque** : on ferme d'abord la boucle (S87, seul
> sprint qui touche `main`) pour que l'atelier serve à quelque chose, puis on monte en qualité
> (BMAD), en pédagogie (trace), en économie (porte/caching), en extensibilité (skills/MCP), et
> enfin en confort (IDE + pilotage à la voix). Réordonnable — ce n'est pas figé.

---

## S86 — Socle git ✅ LIVRÉ + PROUVÉ LIVE (2026-06-21)

**Objectif.** Le filet : un chantier = un worktree jetable sur une branche dédiée, jamais
`main` ; produire un **diff sans déployer**.

**Livré.** `domaine.py` (DDD, machine à états `cree→en_cours→revue→fusionne/jete`),
`git_atelier.py` (worktree/diff/jeter, refuse les branches protégées), `agents.py`
(`LanceurAgent` abstrait + Claude Code / OpenCode / mock factice honnête + `choisir()` auto),
`main.py` (FastAPI : `/sante`, `POST /chantiers`, `/lancer`, `GET /diff`, `DELETE`).
**16 tests** + preuve LIVE contre le vrai dépôt (`main` intact, worktree jeté sans trace).

**Reste.** Pas committé, pas câblé au Registre/dashboard.

---

## S87 — Fusion contrôlée + rebuild ciblé ✅ LIVRÉ (2026-06-21)

**Livré.** `git_atelier.fusionner` (`git merge --no-ff`, conflit → `merge --abort` + erreur,
jamais forcé) + `git_atelier.briques_touchees` ; `domaine.fusion_autorisee` (refus des briques
sensibles `paiements`/`connexion`/`auth` sauf déblocage) ; `rebuild.py` (rebuild ciblé
`docker compose … up -d --build <brique>`, **simulé honnête** par défaut, réel si `DEV_REBUILD=1`) ;
`POST /chantiers/{id}/fusionner` (gate `confirme=true` → `428` sinon, `403` brique sensible,
`409` état≠revue/conflit → merge dans `main` + rebuild ciblé → jette le worktree). L'agent factice
dépose désormais sa note **dans** `briques/<cible>/` (rebuild ciblé démontrable). **+10 tests
(26 au total)**, tous verts.

**Objectif (rappel).** Le gate humain qui rend l'atelier *utile* : relire le diff → **valider** →
fusionner la branche dans `main` + **rebuild de la SEULE brique ciblée** ; sinon, jeter.
C'est le **seul** sprint qui touche `main` → le plus sensible, à border.

**Périmètre.**
- `git_atelier.fusionner(branche, base)` : `git merge --no-ff` (ou cherry-pick) dans `main`,
  **uniquement après** statut `revue` ; refuse si conflit (remonte le conflit, ne force jamais).
- `POST /chantiers/{id}/fusionner` (gate, `confirme=true` requis — motif des actions à effet
  de bord) → transition `revue→fusionne`, puis jette le worktree.
- Rebuild ciblé : repérer la brique modifiée depuis le diff (chemin `briques/<nom>/`) et lancer
  son rebuild (`docker compose ... up -d --build <service>`) **derrière un drapeau** ; par
  défaut **rebuild simulé honnête** (log de la commande), réel seulement si `DEV_REBUILD=1`.
- Garde-fou : liste blanche de briques fusionnables (`paiements`/`connexion`/auth EXCLUES par
  défaut, débloquées au cas par cas).

**Preuve.** Test : chantier factice → fusionner → la note est sur `main` (dépôt jetable) →
worktree jeté ; conflit → refus propre ; brique hors liste blanche → 403. LIVE : un diff réel
appliqué puis `git revert` pour rollback.

**Dépend de.** S86.

---

## S88 — Flux BMAD léger (plan d'abord + règle DDD) ✅ LIVRÉ + PROUVÉ LIVE (2026-06-21)

**Livré.** Brique v0.3.0. État `planifie` ajouté à la machine (transitions `cree→planifie→en_cours`,
replanification `planifie→planifie`) + champs `plan_requis`/`plan`/`plan_valide` et propriétés
`peut_planifier`/`code_verrouille_par_plan` (domaine pur). `plan.py` = l'« Architect » conçoit un
plan en **3 sections imposées** (`## Mini-PRD` / `## Stories` / `## Domaine (DDD)`) via la Gateway
LLM, **repli honnête local** si pas de LLM (parsing markdown → `{prd, stories[], domaine, texte,
genere_par}`). `POST /chantiers/{id}/planifier` (Architect, async) + `POST …/plan/valider`
(`confirme=true` → 428 sinon, 1er gate du **double gate**) ; `lancer` **verrouillé 409** tant que
plan requis non validé ; le plan validé est **injecté à l'agent codeur** (`GABARIT_PLAN` en tête de
l'invite). `GABARIT_INVITE` enrichi : DOMAINE PUR (sans I/O) AVANT toute technique. Opt-in
(`plan_requis`) → rétrocompat S86 totale. **+10 tests (36 au total)**. Preuve LIVE (uvicorn, vraie
Gateway) : `lancer` 409 avant plan → `planifier` rend un **plan IA en FR** structuré → 409 encore →
`valider` 428 sans confirme → valide → `lancer` OK, « Plan validé suivi » présent dans le diff.

**Objectif (rappel).** Reprendre 3 idées de BMAD (agents spécialisés par phase, **plan AVANT
code**, story qui porte le contexte) sans installer BMAD. Le gate devient double : *valide le plan*
puis *valide le diff* — bien plus pédagogique.

**Périmètre.**
- `plan.py` : à l'ouverture d'un chantier, l'agent (rôle « Architect ») produit un **mini-PRD**
  + un **découpage en stories** + une **note de domaine DDD** (entités/agrégats/langage métier),
  AVANT d'écrire du code. Repli honnête si pas de LLM.
- Transition ajoutée : `cree → planifie → en_cours` ; `POST /chantiers/{id}/planifier` puis
  gate `POST /chantiers/{id}/plan/valider`.
- `GABARIT_INVITE` (dans `agents.py`) enrichi : impose l'étape domaine pur avant la logique
  technique.

**Preuve.** Test : un chantier produit un plan structuré (mini-PRD + stories + domaine), le code
ne démarre **pas** sans validation du plan (409). LIVE avec un vrai agent : plan lisible en FR.

**Dépend de.** S86 (idéalement après S87 pour boucler plan→code→fusion).

---

## S89 — Task trace activable (pédagogie) ✅ LIVRÉ + PROUVÉ LIVE (2026-06-21)

**Livré.** Brique v0.4.0. `traceur.py` = journal JSONL par chantier (`Traceur` noter/lire/phrases/
effacer) + traduction des outils en phrases FR (`phrase_pour_outil`, `phrase_pour_evenement`).
`trace_hook.py` = hook autonome branché par Claude Code en **PreToolUse** (traduit chaque outil en
direct, silencieux/tolérant). Les agents narrent quand `trace=True` (factice = ses pas ; Claude Code
= start/end + hook ; OpenCode = start/end) → `chantier.journal` archivé. `GET /chantiers/{id}/trace`
= **flux SSE** (`suivre=false` = relire l'archive puis clore). La phase plan (S88) est aussi narrée.
`jeter` efface la trace. **+6 tests (42 au total)**. Preuve LIVE (uvicorn) : flux SSE ouvert AVANT
`lancer` → la narration FR arrive **en temps réel** pendant le travail de l'agent ; trace OFF →
journal vide + flux silencieux.

**Objectif (rappel).** Interrupteur on/off : quand activé, l'agent **narre chaque pas en français**
(« j'ouvre la branche… », « je crée l'entité X parce que… ») → affiché en direct + archivé.
Conçu pour *apprendre le code* en regardant l'agent travailler.

**Périmètre.**
- `trace.py` : capter les étapes de l'agent. Pour Claude Code → **hooks** (`PreToolUse`/
  `PostToolUse`) traduits en phrases FR ; pour OpenCode → parser le flux ; pour factice → journal
  déjà présent.
- `ch.trace_active` (déjà au domaine) pilote l'émission ; canal **SSE** `GET /chantiers/{id}/trace`
  pour le direct ; archivage dans le journal unifié S78 ([[sprint-s78-journal-conversations-unifie]]).
- Off → l'agent bosse en silence, on ne montre que le diff final.

**Preuve.** Test : trace on → journal pas-à-pas non vide et en FR ; trace off → journal vide.
LIVE : narration en direct pendant un vrai chantier.

**Dépend de.** S86 (S88 utile pour narrer aussi la phase plan).

---

## S90 — La porte à divulgation progressive + prompt caching ✅ LIVRÉ + PROUVÉ LIVE (2026-06-21)

**Livré (côté Cœur — sprint « hors-brique »).**
- **Porte (taille).** `catalogue.py` lit un champ `niveau` par capacité (défaut 0, borné ≥ 0,
  tolérant). `outils.outils_pour(registre, *, chargees, porte)` : avec `porte=True`, les capacités
  de **niveau ≥ 1** sont retirées du contexte et remplacées par un méta-outil **`competence_charger`**
  (pendant de `ToolSearch`) qui les LISTE (nom — description) ; le LLM l'appelle avec un `nom` → son
  schéma complet devient appelable au tour suivant (`executer` rend le schéma ; la boucle de
  `assistant.py` suit `competences_chargees` et recompose les outils). Gardé par
  `PORTE_PROGRESSIVE` (off par défaut) → tant qu'aucune capacité ne déclare `niveau:1`, comportement
  S64 strictement inchangé. La Gateway MCP garde `porte=False` (clients externes voient tout).
- **S90a (préfixe stable).** `outils_pour` **trie les outils par nom** (préfixe d'outils stable d'une
  requête à l'autre) ; dans `assistant.py`, le seul message système VOLATIL (date/heure) passe **en
  dernier**, après le prompt fondateur + digests gelés → le gros préfixe ne « bouge » plus.
- **S90b (`cache_control` conditionnel).** Nouveau `core/cache.py` : `fournisseur(modele)` +
  `appliquer(messages, modele)` pose un `cache_control: ephemeral` sur le dernier message système
  **si Anthropic**, **no-op** pour OpenAI (auto-cache) / local (jamais muté). Branché par modèle dans
  `llm_pipeline.completer` ET `completer_flux` (aliasé `cache_prefixe` car `cache` est déjà un param).
- **Drive-by honnête.** Bug pré-existant corrigé dans `shadow.py` + `proprioception.py` :
  `float(conf.get("…_taux") or DEFAUT)` faisait retomber un **taux 0 explicite** sur le défaut (~10 %)
  → régler le taux à 0 ne désactivait pas l'échantillonnage (fuite de souveraineté/coût + tests
  flaky). Corrigé (`DEFAUT if brut is None else brut`).

**+18 tests** (`test_cache` 6, `test_porte` 6, `test_catalogue` +1, + non-régression `test_s138`/
`test_proprioception` désormais stables) → **32 tests core verts, 0 flaky** (5 rounds).
**Preuve LIVE** (contre la vraie Gateway, modèle `anthropic/claude-sonnet-4-6`, préfixe stable
7702 tokens) : appel 1 → `cache_write_tokens=7702`, coût **$0.0290** ; appel 2 (préfixe identique) →
`cached_tokens=7702`, coût **$0.0024** = **~12× moins cher**. (Chemin `openai/gpt-4o-mini` : la
Gateway ne remonte pas `cached_tokens` ici — noté honnêtement, mécanisme prouvé côté Anthropic.)

**Reste.** Aucune capacité ne déclare encore `niveau:1` (la porte est armée mais inerte tant qu'une
brique n'opte pas dedans — branchement naturel en S91/S92). Mesure du cache OpenAI à confirmer si la
config Gateway expose un jour `cached_tokens`.

**Objectif (rappel).** Dégraisser le contexte (le `core/outils.py` de 95 Ko) ET rendre le préfixe stable
bon marché. Deux faces : taille (porte) et coût (caching).

**Périmètre (porte, côté Cœur).**
- Étendre `core/catalogue.py` (découverte S63) + `core/mcp.py` (Gateway S74) en **niveau-0**
  (nom+description toujours en contexte) / **niveau-1** (corps chargé à la demande).
- Méta-outil `competence_charger(nom)` (pendant de `Skill`/`ToolSearch`) : injecte le corps de la
  compétence + les schémas MCP associés seulement quand utile.
- **S90a — préfixe stable** : prompt système GELÉ (zéro `datetime.now()`), **outils triés par
  nom**, volatil en dernier ; vérifier `cache_read_input_tokens > 0`.
- **S90b — `cache_control` conditionnel** : helper dans `core/llm_pipeline` qui détecte le
  fournisseur effectif → pose les points de cache si Anthropic, laisse l'auto-caching OpenAI
  sinon (rappel : `GATEWAY_MODEL=openai/gpt-4o-mini` par défaut), no-op sur local.

**Preuve.** Test : `outils_pour` ne renvoie plus que niveau-0 par défaut ; `competence_charger`
ajoute le corps. Mesure : sur 2 requêtes au préfixe identique, `cache_read_input_tokens > 0`.

**Dépend de.** S86 ; touche le Cœur (catalogue/mcp/llm_pipeline) — sprint le plus « hors-brique ».

---

## S91 — Création de skills + accroche MCP par la brique

**Objectif.** La brique `dev` **fabrique des skills façon Claude Code** (dossier + descripteur
type SKILL.md) et y **accroche des MCP**, puis les enregistre dans la porte (S90) → découvrables
+ chargeables à la demande, sans code en dur.

**Périmètre.**
- `skills_atelier.py` : créer/valider un dossier skill (`SKILL.md` avec frontmatter
  `nom`/`description`/`outils_autorisés`, scripts éventuels, `mcp` accrochés).
- `POST /skills` (gate) : l'agent rédige une skill dans un chantier → revue → enregistrée dans la
  porte au merge (S87).
- Une skill = un workflow réutilisable ou une **persona BMAD** (Analyst/Architect…) fabriquée
  une fois et servie à la demande.

**Preuve.** Test : création d'une skill valide → apparaît en niveau-0 de la porte, chargeable via
`competence_charger`, MCP accroché listé. LIVE : une skill fabriquée par l'agent puis appelée.

**Dépend de.** S90 (la porte).

---

## S92 — IDE `code-server` + pilotage Cœur `dev_demander`

**Objectif.** Le confort : un vrai IDE web + piloter l'atelier **à la voix / en chat** depuis
l'assistant, avec gate dans la conversation.

**Périmètre.**
- Conteneur `code-server` monté sur le dépôt → **onglet iframe « Atelier dev »** au dashboard
  (motif S19 [[sprint-S19-forge-frontend-integre]]), volet **task trace** (S89) à côté.
- Capacités au `manifest.json` → outil Cœur **`dev_demander(brique, intention, agent, trace)`**
  auto-découvert (motif organisme vivant S63) → l'utilisateur parle, l'agent planifie/code/narre,
  gate dans le chat via les boutons S76 ([[sprint-s76-actions-suggerees-boutons]]).
- Vue dashboard `dev` + carte au Registre des briques (port affiché).

**Preuve.** LIVE : « ajoute un champ X à la brique mail » au chat → chantier ouvert, plan proposé,
gate, diff, fusion sur validation, le tout visible dans l'onglet + l'IDE.

**Dépend de.** S86–S91 (le sprint d'intégration finale).

---

### Récap des numéros

| Sprint | Titre | État |
|---|---|---|
| **S86** | Socle git | ✅ livré + prouvé LIVE |
| **S87** | Fusion contrôlée + rebuild ciblé | ✅ livré (26 tests) |
| **S88** | Flux BMAD léger (plan d'abord + DDD) | ✅ livré + prouvé LIVE (36 tests) |
| **S89** | Task trace activable | ✅ livré + prouvé LIVE (42 tests) |
| **S90** | Porte progressive (niveau-0/1) + prompt caching | ✅ livré + prouvé LIVE (cache 12×, 32 tests) |
| **S91** | Création de skills + accroche MCP | à faire |
| **S92** | IDE code-server + pilotage Cœur `dev_demander` | à faire |
