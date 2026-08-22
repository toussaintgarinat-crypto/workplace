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

## S91 — Création de skills + accroche MCP par la brique ✅ LIVRÉ + PROUVÉ LIVE (2026-06-21)

**Livré.** Brique v0.5.0. `skills_atelier.py` (domaine quasi pur + I/O fichier) : `valider` (slug,
description bornée, `allowed-tools`/`mcp` en listes), `composer_skill_md`/`parser_skill_md`
(frontmatter YAML minimal **clés Claude Code** `name`/`description`/`allowed-tools`/`mcp`, sans
PyYAML — dépendances minces), `creer`/`lire`/`lister`/`supprimer` (refuse invalide → `ErreurSkill`,
refuse doublon, garde-fou anti-évasion des scripts), `persona_bmad(role)` (personas prêtes
**Analyst/Architect/Dev/QA**), et le **pont porte** `capacite_pour(skill)` → capacité de **niveau-1**
(format `core/catalogue.py`) pointant `GET /skills/{nom}/corps`. Endpoints : `POST /skills` (gate
`confirme=true` → 428, 422 invalide, 409 doublon), `POST /skills/persona/{role}`, `GET /skills`
(descripteurs = niveau-0 sans corps), `GET /skills/{nom}`, `GET /skills/{nom}/corps` (instructions +
MCP), `DELETE /skills/{nom}`. **Manifest** : 3 capacités **niveau-0** découvertes par le Cœur
(`dev_skills_lister`, `dev_skill_charger`, `dev_skill_creer` = action) → lister/charger/créer une
skill depuis l'assistant **sans toucher au Cœur**. Dossier `skills/` runtime gitignoré.

**+15 tests** (`test_skills` 6 + `test_skills_porte` 4 + non-régression) → **brique 52 tests pytest
verts**. `test_skills_porte` **importe le VRAI code S90 du Cœur** (`core/outils.py`+`catalogue.py`) :
une skill → `capacite_pour` → niveau-1 → porte ON la **diffère** derrière `competence_charger` (qui
la liste avec sa description) → `competence_charger` rend son schéma → une fois `chargees`, elle
réapparaît appelable. **Preuve LIVE** (uvicorn, port 5951) : `/sante` v0.5.0 ; `POST /skills` sans
confirme → **428** ; avec confirme → skill créée + `capacite.niveau=1` ; persona BMAD fabriquée ;
`GET /skills` liste **sans corps** (niveau-0 bon marché) ; `GET /skills/revue-securite/corps` →
instructions + `mcp=['github']` + `outils=['Read','Grep']`. Le Cœur **découvre** bien les 3 capacités
du manifest (niveau-0, `dev_skill_charger` visible même porte ON, `dev_skill_creer` marquée action).

**Note de cadrage.** Le couplage « rédigée dans un chantier → enregistrée au merge » (S87) est
laissé à S92 (pilotage `dev_demander`) : ici la fabrique de skills est directe + gardée, et la porte
niveau-1 par skill est **prouvée contre le vrai code S90** (la découverte DYNAMIQUE des skills comme
capacités du Cœur — au-delà des 3 capacités statiques du manifest — viendra avec S92). C'est le 1er
sprint qui produit des capacités `niveau:1` réelles → la porte S90 n'est plus seulement « armée ».

**Objectif (rappel).** La brique `dev` **fabrique des skills façon Claude Code** (dossier + descripteur
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

## S92 — IDE `code-server` + pilotage Cœur `dev_demander` ✅ LIVRÉ + PROUVÉ LIVE (2026-06-21)

**Livré.** Brique v0.6.0. `POST /demander` = l'**orchestrateur en un geste** : réutilise tels
quels `ouvrir`/`planifier`/`lancer` (mêmes gardes, mêmes états) → `plan_requis=true` ouvre +
PLANIFIE et **s'arrête au gate du plan** ; sinon ouvre + LANCE l'agent et **s'arrête au gate du
diff** ; JAMAIS de fusion auto ; renvoie le chantier + une `prochaine_etape` lisible (+ `diff_stats`
quand le diff est prêt). Le `manifest.json` expose la **boîte à outils de pilotage** découverte par
le Cœur (organisme vivant S63) : **`dev_demander` (niveau-0)** + `dev_chantiers`/`dev_diff`/
`dev_plan_valider`/`dev_lancer`/`dev_fusionner`/`dev_jeter` (**niveau-1**, chargées à la demande par
la porte S90) → on pilote tout le cycle plan→code→gate→fusion **en parlant** ; comme `dev_demander`
est `action:true`, le builder du Cœur lui injecte automatiquement le param **`confirme`** = gate
dans le chat (boutons S76). Côté confort : `briques/dev/docker-compose.yml` ajoute un conteneur
**`code-server`** (image épinglée `4.96.4`, télémétrie coupée) monté sur le dépôt + la brique `dev`
elle-même (repo monté rw, worktrees gitignorés `.dev-ateliers/`). Cœur : constante `DEV_IDE_URL`,
**onglet « Atelier dev »** (entre Mail et Profil) avec **iframe code-server** chargée paresseusement
+ renvoi vers l'Assistant pour le pilotage ; la **carte au Registre** était déjà câblée via
`vue_dashboard:"dev"` (bouton « Ouvrir dans le dashboard »).

**+3 tests (`test_demander.py`) → brique 55 tests pytest verts.** Catalogue/outils/dashboard du
Cœur vérifiés : les 7 capacités `dev_*` sont découvertes (niveaux 0/1 corrects), `outils_pour` les
transforme en outils LLM (path param `cid` géré, `confirme` auto-injecté sur `dev_demander`), le
dashboard rend l'onglet + substitue `__DEV_IDE_URL__`. **Preuve LIVE** (uvicorn :5953, repli plan
local) : `/sante` v0.6.0 ; `/demander` sans plan → `revue` + `diff_stats` (note dans
`briques/mail/`) + `prochaine_etape` ; `dev_diff` montre la note ; `/demander` plan_requis=true →
`planifie` (plan 3 stories) + codage **verrouillé 409** ; **`main` identique** (SHA inchangé) ;
les 2 chantiers jetés, **aucun worktree ni branche `dev/` résiduels**.

**Reste.** Preuve LIVE de la boucle COMPLÈTE depuis le chat (Cœur + Gateway + brique + vrai agent
de code) et de l'IDE `code-server` en conteneur (stack Docker lancée) — l'offline + le LIVE brique
prouvent le mécanisme ; le bout-en-bout conversationnel se rejouera stack montée.

**Objectif (rappel).** Le confort : un vrai IDE web + piloter l'atelier **à la voix / en chat**
depuis l'assistant, avec gate dans la conversation.

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

## S93 — Seam `EspaceTravail` (local ↔ distant) ✅ LIVRÉ (2026-08-22)

**Livré.** 4e et dernier chantier de la veille GitHub deepseek-ai/deepseek-harness (Cordis) :
applique le pattern **« capability seam » à 3 rôles** (Service Definition / Provider /
Consumer) à l'espace de travail du chantier. Jusqu'ici `main.py` (le Consumer) importait
directement `git_atelier` : le worktree jetable était câblé en dur sur CETTE machine, aucune
façon de basculer un jour vers un sandbox distant (conteneur, VM dédiée) sans réécrire les
endpoints. Nouveau module `espace_travail.py` :
  - **Service Definition** `EspaceTravail` : interface (`nom`, `disponible()`, `ouvrir`/`diff`/
    `resume_diff`/`briques_touchees`/`fusionner`/`jeter`) — le contrat dont `main.py` a
    réellement besoin, indépendant de git/du local.
  - **Provider** `EspaceTravailLocal` : délègue tel quel à `git_atelier` (comportement
    HISTORIQUE inchangé, `git_atelier.ErreurGit` traduite en `ErreurEspace` générique).
  - **Provider** `EspaceTravailDistant` : STUB HONNÊTE (même philosophie que le mock `Factice`
    d'`agents.py`) — `disponible()` répond toujours `False`, chaque opération lève
    `ErreurEspace` avec un message clair plutôt qu'un faux succès. Rien n'est implémenté :
    ce chantier pose le SEAM, pas un vrai sandbox distant.
  - `choisir_espace(nom="")` : factory (env `DEV_ESPACE`), retombe TOUJOURS sur Local si le nom
    demandé est absent/indisponible — jamais de silence trompeur, même logique que
    `agents.choisir()`.

`main.py` refactoré : les 6 usages directs de `git_atelier` (ouvrir/diff/resume_diff/
briques_touchees/fusionner/jeter + `/sante`) remplacés par `_espace()` = `choisir_espace()` ;
`import git_atelier` retiré de `main.py` — le Consumer ne connaît plus que l'interface.
`git_atelier.py` lui-même INCHANGÉ (toujours la seule implémentation réelle, testée en direct
par `test_git_atelier.py`).

**+17 tests** (`test_espace_travail.py`) → **90 tests brique dev verts** (0 régression) :
délégation fidèle de Local sur un vrai dépôt jetable (round-trip ouvrir/diff/briques_touchees/
fusion+conflit, même invariant « prod jamais touchée » que `test_git_atelier.py`), honnêteté de
Distant (jamais disponible, lève sur toute opération), et `choisir_espace()` (défaut local, nom
explicite, repli silencieux-mais-honnête sur nom inconnu/indisponible, lecture `DEV_ESPACE`).

**Revue finale** (skill `code-review`, niveau high) : voir résultat consigné dans la mémoire du
sprint.

**Why.** Clôt la veille [[veille-deepseek-harness-cordis-plugin]] (4/4 chantiers). Le seam est
POSÉ, pas exploité : aucun provider distant réel n'existe encore, mais `main.py` n'a plus besoin
d'être retouché le jour où un vrai sandbox distant sera câblé — seul `EspaceTravailDistant`
changera.

**Dépend de.** S86 (le filet git existant, `git_atelier.py`, non modifié par ce chantier).

---

### Récap des numéros

| Sprint | Titre | État |
|---|---|---|
| **S86** | Socle git | ✅ livré + prouvé LIVE |
| **S87** | Fusion contrôlée + rebuild ciblé | ✅ livré (26 tests) |
| **S88** | Flux BMAD léger (plan d'abord + DDD) | ✅ livré + prouvé LIVE (36 tests) |
| **S89** | Task trace activable | ✅ livré + prouvé LIVE (42 tests) |
| **S90** | Porte progressive (niveau-0/1) + prompt caching | ✅ livré + prouvé LIVE (cache 12×, 32 tests) |
| **S91** | Création de skills + accroche MCP | ✅ livré + prouvé LIVE (v0.5.0, 52 tests) |
| **S92** | IDE code-server + pilotage Cœur `dev_demander` | ✅ livré + prouvé LIVE (v0.6.0, 55 tests) |
| **S93** | Seam `EspaceTravail` (local ↔ distant) | ✅ livré (90 tests) |
