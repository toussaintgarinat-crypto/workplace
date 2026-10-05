# S239 — Résultats : modèles gratuits sans clé (Kilo Code) + correctif OpenCode Go

Date : 2026-10-05. Branche : `sprint/s239-modeles-gratuits-kilo`, fusionnée dans `main` (946f658).
Plan : [plan](../superpowers/plans/2026-10-05-S239-modeles-gratuits-kilo.md). Source :
https://github.com/mnfst/awesome-free-llm-apis (CC0).

## Décision (utilisateur, 2026-10-05)
Option **B** : un fournisseur aux conditions propres en tête (Mistral — clé à poser par
l'utilisateur, vide sur le HP), les gratuits Kilo Code (sans clé, prompts possiblement
journalisés : NVIDIA « do not submit personal or confidential data ») en **secours seulement**.
OpenCode Go corrigé mais **non réactivé** (abonnement en pause).

## Livré
- **gateway-sync 0.2.0** : sources OpenRouter (`free/*`) et Kilo (`kilo/*`, `api_key: anonymous`) ;
  chaque source ne gère que son préfixe, ne touche jamais au YAML (`db_model`), une source en
  échec ou un catalogue brut vide n'efface rien ; retrait volontaire possible
  (`KILO_TOP_N=0`, `KILO_EXCLURE` par segment de chemin) ; méta-routeurs `*/free` exclus ;
  `cooldown_time: 60` sur les modèles ajoutés ; filtre de modalité corrigé (sortie texte).
- **Cœur** : cascade `[tête] → free/* → kilo/* → souverain/repli payant` ; `kilo/*` à coût
  marginal nul ; le routage économe ne prépose JAMAIS un `kilo/*` ; ⚙ Cerveau ne propose pas les
  alias `forge/defaut` / `gratuit/*`.
- **Gateway (YAML)** : `gratuit/auto` (`kilo-auto/free`) et `gratuit/secours` (`openrouter/free` via
  Kilo), `forge/defaut` = Mistral small avec repli `[gratuit/auto, gratuit/secours]` ;
  politique de frigo conforme à LiteLLM v1.86.2 (0 retombait sur 3 ; clé inexistante retirée) ;
  `cooldown_time` 120 s sur `mistral/*` et `forge/defaut`, 60 s sur les gratuits.
- **Forge** : défaut `gateway` / `forge/defaut` (compose, config, création des presets) ; journal
  honnête du modèle réellement servi lors d'un repli Gateway (non-streaming).
- **OpenCode Go** : User-Agent `workplace-coeur/1.0` (YAML) + `x-opencode-session` par
  conversation (HMAC-SHA256 du fil, `wp-<32 hex>`) relayé par
  `model_group_settings.forward_client_headers_to_llm_api: [go/*]` — LiteLLM retire
  `Authorization`/clés avant tout relais. Aussi pour `moa.py`.

## Tests
Cœur 802 passed ; forge 340 passed, 2 skipped ; gateway-sync 28 ; filets racine
(`test_gateway_config_s239.py` + `test_couple_openai_httpx.py`) 100 passed.

## Revue
Revue finale : 0 Critical, 4 Important (routage économe pouvant mettre Kilo en tête ; défaut Forge
figé sur Go par le compose ; journal Forge faux lors d'un repli ; politique de frigo inopérante),
tous corrigés. Relecture des correctifs : 3 Important (seuil timeout global, frigo d'1 h de Mistral,
cooldown non appliqué aux modèles déjà en base) corrigés ou traités au déploiement.
Actés, non traités : streaming Forge sans trace de repli (LiteLLM n'envoie pas les en-têtes sur un
flux) ; ReAct multi-tours attribué au dernier modèle ; `definir_modele` accepte encore un alias
saisi à la main ; renommage des ids à 3 segments ; compteur d'échecs LiteLLM à TTL 1 h (un
Mistral sorti du frigo y retourne 120 s au premier échec) ; `/sync` 200 même si OpenRouter 401.

## Déploiement HP (2026-10-05)
Images construites sur le Mac (`git archive main`), étiquettes `avant-s239` (core-core,
gateway-gateway-sync, workplace-forge-core) ; sauvegardes `~/s239-avant/` (dumps forge et
gateway, `assistant_config.json`, `.env` et YAML gateway, compose forge). Fichiers du sprint
copiés dans le dépôt du HP (resté sur 4ce4141).
- Gateway recréée (`--force-recreate`), saine. Sync : 6 `kilo/*` ajoutés. 10 anciens `free/*` en
  base (frigo 1 h) purgés puis recréés à 60 s.
- Forge : `s239_presets_forge_defaut.sql` (`ON_ERROR_STOP`) → 25 presets (24 pôles, 1 venture)
  `opencode/go/deepseek-v4-flash` → `gateway/forge/defaut`. Env `DEFAULT_LLM_*` vérifié.
- Cœur : `/data/assistant_config.json` `model` `go/deepseek-v4-pro` → `mistral/small`.
  Chaîne : `mistral/small, free/×3, kilo/×3, deepseek/deepseek-v4-flash`.

## Preuve LIVE
- Cœur, question simple : réponse « La capitale de la France est Paris. » en 8,1 s par
  `kilo/nvidia/nemotron-3.5-lightning` (Mistral sans clé, `free/*` 401, un `kilo/*` 429 écartés).
- Cœur, appel d'outil : `tool_calls=['heure']` en 3,1 s par `kilo/nvidia/nemotron-3-ultra-550b-a55b`.
- Forge `generate_text` : « La capitale de l'Italie est Rome. » en 9,4 s, journal
  « forge/defaut servi par repli Gateway → gratuit/secours ».
- `forge/defaut` brut : `pong`, `x-litellm-model-group: gratuit/secours`, `attempted-fallbacks: 1`.
- OpenCode Go (un seul appel d'essai, hors cascade) : l'erreur « missing x-opencode-session » a
  disparu ; nouvelle réponse : « This Go model requires Global regions. Select Global in your
  workspace's Privacy settings » → réglage du compte OpenCode à faire à la réactivation.

## Reste à faire (utilisateur)
- Poser une clé Mistral (offre gratuite, refuser l'entraînement) dans ⚙ Cerveau : Mistral devient
  alors la vraie tête (Cœur et Forge).
- À la réactivation de Go : abonnement + région « Global » dans le workspace OpenCode, puis
  remettre un `go/*` en tête dans ⚙ Cerveau.
- OpenRouter : compte « User not found » — les `free/*` sont resynchronisés chaque jour mais
  échouent en 401 (rapidement) tant qu'une clé valide n'est pas posée.
