# S239 — Modèles gratuits sans clé (Kilo Code) + correctif OpenCode Go

> Décision utilisateur 2026-10-05 : option **B** — un fournisseur aux conditions propres en tête
> (Mistral, clé à renouveler par l'utilisateur), Kilo Code en **filet de secours**. Correctif
> OpenCode Go préparé mais **Go NON réactivé** (pas dans la cascade) : l'utilisateur remettra un
> abonnement plus tard. Objectif immédiat : pouvoir tester Workplace avec des modèles gratuits.

## Contexte (constaté 2026-10-05, cf. `docs/sprints/S238b-forge-openai-httpx-resultats.md`)

- Aucun modèle de chat de la Gateway ne répond : OpenRouter 401 « User not found », `go/*`
  400 « missing x-opencode-session », clés directes refusées/absentes, Ollama sans modèle de chat.
- Cascade du Cœur sur le HP (`/data/assistant_config.json`) : `go/deepseek-v4-pro` → 3 `free/*`
  (OpenRouter) → `deepseek/deepseek-v4-flash` (OpenRouter). Tout est mort.
- Source : https://github.com/mnfst/awesome-free-llm-apis (CC0). Testé depuis le HP :
  **Kilo Code** répond SANS clé (`https://api.kilo.ai/api/gateway`, OpenAI-compatible) —
  `Authorization: Bearer anonymous` ou pas d'en-tête = 200 ; `Bearer None` = 401. Streaming et
  `tool_calls` OK. Limite 200 req/h/IP. Catalogue `GET /models` au **même format qu'OpenRouter**
  (pricing prompt/completion "0", `supported_parameters` avec `tools`, `architecture.modality`).
  Méta-routeurs dans le catalogue : `kilo-auto/free`, `openrouter/free`.
  OVH anonyme : 2 req/min, inutilisable ; LLM7 : clé désormais requise.
- ⚠ Confidentialité : les gratuits Kilo peuvent journaliser (NVIDIA : « do not submit personal or
  confidential data »). D'où leur rang de SECOURS, jamais de tête.
- OpenCode Go (doc opencode.ai/docs/go) : exige `x-opencode-session` = identifiant **stable par
  conversation**, et un User-Agent propre au client (pas celui d'un SDK générique).
- LiteLLM du HP : `ghcr.io/berriai/litellm:v1.86.2`, modèles dynamiques en base
  (`STORE_MODEL_IN_DB=True`), `router_settings` : `AuthenticationErrorAllowedFails: 0`,
  `cooldown_time: 3600`.

## Tâches

### T1 — gateway-sync : Kilo comme deuxième source de gratuits
`briques/gateway-sync/sync.py` (+ tests, README, manifest si besoin).
- Généraliser en **sources** : OpenRouter (préfixe `free/`, existant, clé requise) et Kilo
  (préfixe `kilo/`, aucune clé, `api_key: "anonymous"`, `api_base:
  https://api.kilo.ai/api/gateway`, `model: openai/<id>`, timeout court + `num_retries: 0`
  comme les `free/*`). Même filtre gratuit + `tools` + texte. Exclure les méta-routeurs
  (ids `*/free`, ex. `kilo-auto/free`, `openrouter/free`). `KILO_TOP_N` (défaut 6) ;
  `KILO_EXCLURE` (préfixes d'ids séparés par des virgules, défaut vide) pour écarter un
  fournisseur amont sans toucher au code.
- Chaque source ne gère QUE son préfixe ; une source en échec (catalogue injoignable, clé
  absente) n'efface rien et n'empêche pas l'autre de se synchroniser. Ne jamais toucher aux
  modèles déclarés dans le YAML (vérifier comment `/model/info` les distingue des modèles en base).
- Le résultat de `synchroniser()` détaille par source ; garder la compatibilité de `/sync` et de
  la tâche d'horloge (`sync-modeles-gratuits`).

### T2 — Cœur : les `kilo/*` dans la cascade, après les `free/*`
`core/config_assistant.py` (`chaine_modeles`), `core/llm_pipeline.py` (`_sans_cout_marginal`),
`core/routage.py` (`_premier_gratuit`) + tests.
- Cascade auto : `[tête]` → `free/*` (top N) → `kilo/*` (top N) → souverain/repli payant.
- `kilo/*` = coût marginal nul (pas jetés par le garde-fou budget).
- Tests sur l'ordre exact de la chaîne et sur `_sans_cout_marginal("kilo/…")`.

### T3 — Gateway (YAML) : alias stable pour la Forge + OpenCode Go
`briques/gateway/litellm_config.yaml`.
- Alias **`gratuit/auto`** → `kilo-auto/free` (le routeur de Kilo, nom stable) avec
  `api_key: anonymous`. Préfixe distinct de `kilo/` pour que le sync ne le supprime jamais.
- Alias **`forge/defaut`** → même déploiement que `mistral/small` (clé `MISTRAL_API_KEY`), avec
  `router_settings.fallbacks: [{"forge/defaut": ["gratuit/auto"]}]`. La Forge n'a pas de cascade :
  c'est la Gateway qui lui donne l'option B. Le Cœur, lui, garde `mistral/small` SANS repli
  Gateway (sa cascade et son journal de modèles restent la vérité — un repli caché fausserait
  `journal_modele`).
- OpenCode Go : sur les entrées `go/*`, `extra_headers` avec un User-Agent propre
  (`workplace-coeur/1.0`). L'identifiant de session ne peut pas être statique : voir T4.
- Vérifier sur une Gateway LiteLLM v1.86.2 LOCALE (docker sur le Mac, config du dépôt) que
  le YAML se charge, que `gratuit/auto` répond, et que `forge/defaut` sans clé Mistral bascule
  bien sur `gratuit/auto` (réponse réelle).

### T4 — OpenCode Go : identifiant de session par conversation
- Établir sur LiteLLM v1.86.2 le mécanisme qui transmet un en-tête par requête jusqu'au
  fournisseur (ex. `forward_client_headers_to_llm_api`, ou `extra_headers` dans le corps) —
  le prouver contre un faux serveur amont local qui journalise les en-têtes reçus, sans
  appeler OpenCode.
- Côté Cœur (`llm_pipeline.py`), n'envoyer `x-opencode-session` (identifiant stable de la
  conversation, dérivé de la session existante — pas de donnée personnelle) que pour les
  modèles `go/*`. Tests.
- Go reste HORS de la cascade : aucune config ne le remet en tête.

## Déploiement HP (après revue + fusion dans main)
- Gateway : YAML + `docker compose up -d --force-recreate gateway` (piège bind-mount) ;
  gateway-sync reconstruit sur le Mac (piège DNS) ; `POST :4002/sync`.
- Cœur : image reconstruite sur le Mac ; config `/data/assistant_config.json` : `model` passe de
  `go/deepseek-v4-pro` à `mistral/small` (sauvegarde du JSON avant).
- Forge : `DEFAULT_LLM_PROVIDER=gateway`, `DEFAULT_LLM_MODEL=forge/defaut` ; recréation.
- Sauvegardes avant ; images `avant-s239`.
- Preuve LIVE : vraie réponse via le Cœur (journal du modèle réellement utilisé) et via la Forge
  (`generate_text`, `/pipeline-assistant/chat`) ; sync listant des `kilo/*` ; Go : un appel avec
  l'en-tête pour voir si le 400 disparaît (le statut d'abonnement peut donner 401/402 — c'est
  attendu, l'abonnement est en pause).
