# Sprint S138 — Optimisation des coûts LLM (routage dynamique, cache sémantique, trimming, shadow)

> **But du sprint** : faire passer Forge d'un choix de modèle *statique* (preset par scope)
> à un pipeline d'appel LLM *intelligent et économe*, sans changer la config des agents.
> Chaque appel paie le juste prix : le bon modèle, le moins de tokens possible, et zéro
> token quand la réponse existe déjà.

- **Sprint** : S138
- **Pré-requis** : S128 (react_executor), S133 (governor + pricing), S129 (memory/embeddings Ollama)
- **Statut** : **les 5 chantiers (0,1,2,3,4) implémentés dans Workplace** (adaptés fichier, kill-switches par config) — **chat + cache sémantique + routage PROUVÉS LIVE le 2026-06-10**
- **Date de planification** : 2026-06-05
- **Date d'implémentation (Workplace)** : 2026-06-06
- **Date de preuve LIVE** : 2026-06-10

### Preuve LIVE (2026-06-10)

Script jetable exécuté **dans le conteneur `core-core-1`** contre la **vraie Gateway LiteLLM**
(`gateway-gateway-1`, `host.docker.internal:4001`), journal & cache isolés en `/tmp` :

| Chantier | Résultat LIVE |
|---|---|
| C0 chat + coût | `openai/gpt-4o-mini` → « Paris. », 19 tok in / 3 out, **coût réel $0.000005** lu dans l'en-tête `x-litellm-response-cost` |
| C2 cache sémantique | 1er appel miss (26 tok, $0.000160) → 2e identique **HIT à 0 token, $0** (embeddings `embedding/all-minilm` réels, 0 appel LLM) |
| C1 routage dynamique | « merci, c'est parfait ! » → `trivial` → servi par l'économe local **`ollama/llama3`** (coût $0) ; requête code → `complexe` → reste sur `gpt-4o-mini` |
| Journal | 5 appels agrégés, `cache_hits=1`, `appels_retrogrades=1` |

**Pièges notés** : les modèles `free/*` (OpenRouter) renvoient parfois **429** (rate limit) →
préférer un économe **local** `ollama/llama3` ; la Gateway met ~1 min à accepter les complétions
après un (re)démarrage Docker (`health: starting`) alors que `/v1/models` répond déjà.

**Reste non prouvé en réel** : shadow routing LIVE (validé offline seulement) et les **métriques
cibles du sprint** (−40 % coût, ≥25 % hit) sur du trafic réel.

---

## État d'implémentation dans **Workplace** (≠ workspace/forge)

> Le plan ci-dessous est écrit pour `workspace/forge` (base SQL, Alembic, pgvector).
> **Workplace** n'a pas de base dans le Cœur (la mémoire est une brique séparée) :
> la fondation a donc été **adaptée au style fichier** de `core/`.

| Élément | Fichier Workplace | Statut |
|---|---|---|
| Wrapper unifié `completer()` (= `complete()` du plan) | `core/llm_pipeline.py` | ✅ fait |
| Comptage tokens + coût (en-tête LiteLLM `x-litellm-response-cost`, sinon table de repli) | `core/llm_pipeline.py` | ✅ fait |
| Journal d'usage + budget jour/mois (alerte 80 % / blocage 95 %) = governor-lite | `core/journal_usage.py` (JSONL `/data/usage_llm.jsonl`) | ✅ fait |
| Garde-fou : budget atteint → repli sur modèles `free/*`/`ollama` only | `core/llm_pipeline.py` | ✅ fait |
| Trimming pur (dédup + fenêtre glissante, sans appel réseau) | `core/trimming.py` | ✅ fait |
| 3 call-sites unifiés (chat, classement, test cerveau) | `core/assistant.py`, `core/classer.py`, `core/config_assistant.py` | ✅ fait |
| Endpoint suivi des coûts | `GET /assistant/usage` (`core/main.py`) | ✅ fait |
| Cache sémantique (chantier 2) — embeddings Gateway + cosinus Python pur, JSONL | `core/cache_semantique.py` (`/data/llm_cache.jsonl`) | ✅ fait (opt-in `cache=True`) |
| Routage dynamique (chantier 1) — heuristiques pures + rétrogradation | `core/routage.py` + config `routage_actif`/`modele_econome` | ✅ fait (kill-switch) |
| Summarization à froid (chantier 3b) — condense l'historique via petit modèle | `core/summarisation.py` + config `resume_actif`/`modele_resume` | ✅ fait (off défaut) |
| Shadow routing (chantier 4) — candidat async + équivalence embedding | `core/shadow.py` + config `shadow_actif`/`shadow_candidat`/`shadow_taux` | ✅ fait (off défaut) |
| Endpoints | `GET /assistant/usage`, `GET /assistant/shadow`, `POST /assistant/routage` | ✅ fait |
| Tests autonomes (sans pytest ni vraie Gateway) — 8 tests | `core/test_s138.py` | ✅ verts |

**Notes d'honnêteté technique**
- **Pas de pgvector** : adapté au Cœur (fichier JSONL + cosinus Python pur sur cache
  plafonné). À réévaluer si le cache grossit beaucoup (cf. hors-scope LiteLLM/Redis).
- **Cache** : opt-in par appel, jamais pour les tours à outils ni température élevée.
  Aujourd'hui surtout actif sur le **classement** (déterministe, sans outils).
- **Routage / shadow** : le chat passe toujours des outils → le garde-fou
  function-calling **empêche la rétrogradation** sur ces tours ; le routage calcule
  néanmoins la complexité (télémétrie) et le shadow ne se déclenche que sur les
  tours qui finissent en **texte**. Pleinement actifs sur les flux sans outils.
- `PRIX_PAR_MTOK` reste indicative (repli quand la Gateway ne renvoie pas le coût) ;
  un modèle hors table est compté à 0 (préférable à un chiffre faux).

---

## 0. Contexte — ce qui existe déjà

| Brique existante | Fichier | Rôle |
|---|---|---|
| Résolution de preset hiérarchique | `forge/core/app/llm.py` → `resolve_llm_config()` | agent → tool → pole → venture → global |
| Appel one-shot | `forge/core/app/llm.py` → `generate_text()` | complétion via gateway |
| Boucle ReAct | `forge/core/app/react_executor.py` | client `AsyncOpenAI` direct → gateway, function-calling |
| Catalogue providers/modèles | `forge/core/app/llm.py` → `AVAILABLE_PROVIDERS` | ollama / anthropic / openai / groq / gemini / openrouter / `free/*` |
| Gateway centralisée | `gateway/litellm_config.yaml` | endpoint OpenAI-compatible + virtual keys budgétées |
| Modèles gratuits auto-syncés | `gateway/sync_free_models.py` | top-12 modèles OpenRouter à coût 0 |
| Gouvernance budgétaire | `forge/core/app/routers/governor.py` | budget J/M, seuil alerte 80 % / blocage 95 %, journal usage |
| Embeddings locaux | `embedding/all-minilm` (gateway) | 384 dims, gratuit, alimente déjà la brique Memory |

**Constat clé** : il existe **deux** points de passage des appels LLM (`generate_text` et
`react_executor`). Le sprint commence par les unifier derrière **un seul wrapper** pour ne
brancher les 4 couches qu'une fois.

---

## Chantier 0 (fondation) — Unifier le chemin d'appel : `llm_pipeline.complete()`

Sans cette étape, les 4 idées devraient être codées deux fois.

- **Nouveau** : `forge/core/app/llm_pipeline.py` exposant
  `async def complete(messages, ctx: LlmContext, *, tools=None, max_tokens=None) -> CompletionResult`.
- Le pipeline applique, dans l'ordre :
  `trimming → cache lookup → routing → appel gateway → cache store → governor usage`.
- `generate_text()` (llm.py) et `react_executor` appellent désormais `complete()`.
- `CompletionResult` porte : `text`, `model_used`, `tokens_in/out`, `cout_usd`,
  `cache_hit: bool`, `routed_from/routed_to`, `trimmed_tokens`.

**Critères d'acceptation**
- [ ] Tous les call-sites LLM passent par `complete()` (aucun `AsyncOpenAI(...).chat` direct hors pipeline).
- [ ] Parité fonctionnelle : les tests existants de `react_executor` et des agents passent toujours.
- [ ] Chaque appel écrit **une** ligne `GovernorUsage` enrichie (champs cache/routing renseignés).

---

## Chantier 1 — Routage dynamique par complexité (Dynamic Routing)

> Un agent « complexe » reçoit parfois « Bonjour, t'as fini ? ». Inutile de payer Sonnet.

### Conception
- **Nouveau** : `forge/core/app/routing/complexity_router.py`.
- Stratégie en **2 étages**, du moins cher au plus cher :
  1. **Heuristiques locales (coût 0)** : longueur du prompt, présence de code/JSON, nb de tours,
     présence d'outils requis, mots-clés d'intention (résumé court, salutation, oui/non…).
     Tranche la majorité des cas sans appel réseau.
  2. **Classifieur LLM ultra-léger (fallback)** : si l'heuristique est ambiguë, un appel
     Groq (`llama-3.3-70b` / `gemma2-9b-it`) ou modèle `free/*` renvoie un label
     `trivial | simple | standard | complexe` en ~1 token. Mis en cache (cf. Chantier 2).
- **Politique de rétrogradation** : un mapping `complexité → famille de modèle` rétrograde
  l'appel *pour cette requête précise* vers `free/*` ou Ollama local, **sans toucher au preset**
  de l'agent. Le preset reste le plafond ; le routeur ne fait que descendre.
- **Garde-fous** : jamais de rétrogradation si `tools` requis et modèle cible sans function-calling ;
  jamais en dessous du modèle minimal déclaré par l'agent (`min_model` optionnel sur le preset).

### Schéma DB
- Table `routing_rules` (org-scopée) : `complexity_level`, `target_model`, `enabled`.
- Colonnes ajoutées à `governor_usage` : `routed_from`, `routed_to`, `complexity_level`.

### Fichiers touchés
- `+ routing/complexity_router.py`, `+ routers/routing.py` (CRUD règles), `~ llm_pipeline.py`,
  `~ models/` (+ migration Alembic), `~ governor.py` (afficher l'économie estimée).

### Critères d'acceptation
- [ ] « Bonjour, t'as fini ? » sur un agent configuré en Sonnet part vers un `free/*`.
- [ ] Une requête de raisonnement long reste sur le modèle du preset.
- [ ] `routing_rules` désactivable par org (kill-switch) → comportement = S137 (statique).
- [ ] Le coût du classifieur n'excède jamais l'économie (mesuré sur le dashboard governor).

### Risques / honnêteté technique
- Mauvaise classification = réponse de moindre qualité sur une requête importante.
  → mitigé par le `min_model` plancher + le Chantier 4 (shadow) qui mesure la casse avant généralisation.

---

## Chantier 2 — Caching sémantique centralisé (Semantic Caching)

> Prompts système, structures, et requêtes utilisateurs se répètent à ~90 %.

### Conception
- **Nouveau** : `forge/core/app/cache/semantic_cache.py`.
- **Clé** : embedding du prompt normalisé via `embedding/all-minilm` (déjà dispo, gratuit, local).
- **Stockage** : on réutilise pgvector (déjà en place pour Memory, `Vector(384)`) →
  table `llm_cache` (`org_id`, `scope_hash`, `embedding vector(384)`, `prompt_norm`, `response`,
  `model`, `hits`, `created_at`, `ttl`). Pas de nouvelle dépendance Redis pour le MVP.
- **Lookup** : recherche du plus proche voisin ; **hit** si `cosine_sim ≥ SEUIL` (param, défaut 0.97)
  **et** même `scope_hash` (système + modèle + outils) → réponse renvoyée à **0 token**.
- **Invalidation** : TTL + `scope_hash` (un changement de prompt système invalide naturellement).
  Exclusion explicite des appels non-cachables (`temperature` élevée, requêtes datées, outils à effet de bord).

### Pourquoi pas le cache natif LiteLLM d'abord ?
LiteLLM propose un cache (exact + sémantique via Redis). On le garde comme **option de
fallback/futur** (Chantier hors-scope), mais le MVP vit dans Forge pour :
(a) réutiliser pgvector déjà branché, (b) scoper par org/preset finement, (c) tracer les hits
dans `governor_usage`. À réévaluer en rétro.

### Schéma DB
- Table `llm_cache` (pgvector). Colonne `cache_hit bool` + `cache_sim float` sur `governor_usage`.

### Fichiers touchés
- `+ cache/semantic_cache.py`, `~ llm_pipeline.py`, `~ models/` (+ migration), `~ governor.py` (taux de hit).

### Critères d'acceptation
- [ ] Deux requêtes quasi-identiques → 2ᵉ appel `cache_hit=true`, `tokens=0`, latence < 50 ms.
- [ ] Un changement de prompt système invalide le cache (scope_hash différent).
- [ ] Taux de hit visible sur le dashboard governor.
- [ ] Faux positifs maîtrisés : seuil réglable par org, désactivable.

### Risques / honnêteté technique
- **Risque principal = faux positif** (renvoyer une réponse « proche » mais fausse).
  Seuil prudent (0.97), `scope_hash` strict, et opt-in par scope sensible (legal/contrats : cache off par défaut).

---

## Chantier 3 — Gestion intelligente du contexte (Context Trimming)

> Les tokens **input** sont souvent la majorité de la facture ; et le « lost in the middle »
> dégrade les petits modèles.

### Conception
- **Nouveau** : `forge/core/app/context/trimmer.py`, appelé en **premier** dans `complete()`.
- Stratégies cumulables, du moins destructif au plus :
  1. **Dédup / nettoyage** : suppression métadonnées d'outils redondantes, espaces, JSON verbeux.
  2. **Fenêtre glissante** : garder N derniers tours + le message système + les ancres importantes.
  3. **Summarization à froid** : au-delà d'un seuil de tokens, condenser l'historique ancien via
     un **petit modèle** (`free/*` ou Ollama) en un résumé compact réinjecté comme contexte.
  4. **Budget de tokens cible** par appel (dérivé du modèle effectivement routé).
- Compatible avec le react_executor (l'historique d'agent gonfle vite : c'est le gros gisement).

### Fichiers touchés
- `+ context/trimmer.py`, `~ llm_pipeline.py`, `~ react_executor.py` (history compaction).

### Critères d'acceptation
- [ ] Sur une conversation longue, réduction mesurable des tokens input (cible : −40 % à iso-qualité).
- [ ] La summarization ne perd pas les faits critiques (validé via jeu de tests scénarisés).
- [ ] Désactivable ; seuils paramétrables par org.

### Risques / honnêteté technique
- La summarization automatique peut perdre une info clé. → garder les messages « épinglés »
  intacts, et logguer ce qui est condensé pour audit.

---

## Chantier 4 — Shadow routing / A-B coût vs qualité (Governor)

> Comment prouver qu'un agent peut passer en `free/*` sans casser la prod ?

### Conception
- **Nouveau** : mode `shadow` dans le governor + `forge/core/app/shadow/evaluator.py`.
- Sur un **échantillon** (défaut 5 % des appels, paramétrable), l'appel part en parallèle vers :
  (a) le modèle configuré/routé (sert la prod), (b) un modèle candidat moins cher (asynchrone, ne bloque pas).
- Un **évaluateur** compare les deux réponses : similarité d'embedding + (option) juge LLM
  léger notant l'équivalence sur 0–1. Résultat stocké, jamais renvoyé à l'utilisateur.
- Agrégat par agent/scope : « le modèle candidat est équivalent à X % des cas » →
  **recommandation automatique de rétrogradation** sûre, alimentant le Chantier 1.

### Schéma DB
- Table `shadow_runs` : `scope`, `model_prod`, `model_candidate`, `equiv_score`, `cost_prod`,
  `cost_candidate`, `verdict`, `created_at`.

### Fichiers touchés
- `+ shadow/evaluator.py`, `~ routers/governor.py` (mode shadow + endpoint rapport), `~ llm_pipeline.py`,
  `~ models/` (+ migration), `~ frontend` (panneau « Recommandations d'économie »).

### Critères d'acceptation
- [ ] Le mode shadow n'affecte ni la latence perçue ni la réponse renvoyée (candidat 100 % async).
- [ ] Rapport par agent : score d'équivalence + économie projetée €/mois.
- [ ] Recommandation « cet agent peut passer à `free/X` sans risque » exploitable en 1 clic.

### Risques / honnêteté technique
- Le shadow **augmente** temporairement le coût (double appel sur l'échantillon).
  → échantillon faible (5 %), candidats `free/*` en priorité, activable par campagne limitée.

---

## Séquencement & dépendances

```
Chantier 0 (fondation: complete())  ──►  obligatoire en premier
        │
        ├─► Chantier 3 (trimming)        ─ indépendant, gros ROI immédiat
        ├─► Chantier 2 (cache sémantique) ─ indépendant
        ├─► Chantier 1 (routage)          ─ s'appuie sur 0
        └─► Chantier 4 (shadow)           ─ valide/pilote le Chantier 1 (à faire après ou en // de 1)
```

**Ordre recommandé par ROI/risque** : `0 → 3 → 2 → 1 → 4`.
(Trimming = gain rapide sans risque qualité ; cache = gain fort risque faible ; routage = gain fort
risque moyen, sécurisé ensuite par le shadow.)

---

## Backlog découpé (tickets)

| # | Ticket | Chantier | Estim. |
|---|---|---|---|
| S138-1 | Wrapper `llm_pipeline.complete()` + `CompletionResult`, brancher les 2 call-sites | 0 | M |
| S138-2 | Enrichir `governor_usage` (cache/routing/complexity) + migration | 0 | S |
| S138-3 | `context/trimmer.py` : dédup + fenêtre glissante + budget tokens | 3 | M |
| S138-4 | Summarization à froid de l'historique (petit modèle) + messages épinglés | 3 | M |
| S138-5 | `cache/semantic_cache.py` : table pgvector `llm_cache`, lookup/store, scope_hash | 2 | L |
| S138-6 | Dashboard governor : taux de hit + tokens économisés | 2 | S |
| S138-7 | `complexity_router.py` : heuristiques locales | 1 | M |
| S138-8 | Classifieur LLM léger (Groq/free) + cache du verdict | 1 | M |
| S138-9 | `routing_rules` (CRUD `routers/routing.py`) + kill-switch + plancher `min_model` | 1 | M |
| S138-10 | `shadow/evaluator.py` + mode shadow governor (échantillon async) | 4 | L |
| S138-11 | Rapport shadow + recommandations de rétrogradation (frontend) | 4 | M |
| S138-12 | Tests d'intégration bout-en-bout + jeux de scénarios qualité | tous | M |

Tailles indicatives : S ≈ ½j, M ≈ 1–2j, L ≈ 3j+.

---

## Métriques de succès du sprint

- **Coût** : −X % de coût LLM mensuel à charge constante (cible initiale : **−40 %**).
- **Cache** : taux de hit sémantique ≥ 25 % sur les flux répétitifs (briefs, prompts système).
- **Tokens input** : −40 % sur les conversations longues d'agents (trimming).
- **Qualité** : score d'équivalence shadow ≥ 0,9 sur les agents rétrogradés (pas de régression).
- **Sécurité** : chaque couche désactivable par org (kill-switch) → retour au comportement S137.

## Hors-scope (sprint suivant)

- Cache exact/sémantique natif LiteLLM + Redis (réévaluation après MVP pgvector).
- Routage multi-objectif (latence + coût + qualité) par optimisation.
- Fine-tuning / distillation d'un routeur maison sur l'historique `governor_usage`.
- Budgets par utilisateur final (au-delà des virtual keys gateway).
