# S240 — Modèles LLM configurables dans ⚙ Cerveau (sans YAML)

> Demande utilisateur 2026-10-05 : « je veux que ce soit configurable directement dedans sans
> passer par le yaml ». Périmètre choisi : **Forge + modèles** — un sélecteur « Modèle de la
> Forge » ET l'ajout/retrait de modèles de n'importe quel fournisseur, depuis ⚙ Cerveau.

## Constat
- Côté Cœur, clé fournisseur (`POST /assistant/cle-fournisseur`, écrit `briques/gateway/.env` +
  recrée la Gateway) et modèle de tête (`POST /assistant/config`) sont déjà réglables.
- Restent dans `briques/gateway/litellm_config.yaml` : l'alias `forge/defaut` (câblé Mistral, repli
  `[gratuit/auto, gratuit/secours]` dans `router_settings.fallbacks`) et la liste des modèles de
  chaque fournisseur (ex. Groq = seulement `llama-3.3-70b-versatile`).
- LiteLLM v1.86.2 gère des modèles **en base** à chaud (`/model/new`, `/model/delete`,
  `/model/info` avec `model_info.db_model`), déjà utilisé par gateway-sync (préfixes `free/`,
  `kilo/`). `GATEWAY_KEY` du Cœur = `LITELLM_MASTER_KEY` (vérifié sur le HP, empreintes égales).
- **Sécurité (préexistant)** : `core/main.py:110` monte `assistant.router` avec le seul
  `lire_contexte_tenant` (non bloquant) — **aucune session exigée**. Sur le HP
  (`AUTH_ENABLED=true`), `GET /assistant/config` répond 200 sans cookie, en local comme via le
  domaine (résolu sur l'IP NetBird 100.x : LAN + mesh, pas Internet). N'importe quel appareil du
  LAN/mesh peut donc poser des clés et changer le cerveau. Pas de notion de rôle admin dans le
  Cœur (`/admin/inviter-proche` = simple `exiger_session`).

## Conception
- **Catalogue de fournisseurs côté serveur** (étendre `FOURNISSEURS_CLES`) : pour chaque
  fournisseur, le préfixe LiteLLM (`mistral/`, `groq/`, `gemini/`, `anthropic/`, `openai/`,
  `deepseek/`, `openrouter/`, OpenCode Go = `openai/` + `api_base` `/zen/go/v1`…), l'`api_base`
  éventuel et la variable de clé (`os.environ/XXX_API_KEY`). L'utilisateur ne fournit QUE
  `fournisseur` + `identifiant du modèle` : **jamais** d'`api_base` ni de clé libres (sinon on
  pourrait faire envoyer une clé existante vers un serveur arbitraire). Validation stricte de
  l'identifiant (caractères autorisés, longueur).
- **Modèles ajoutés par l'utilisateur** : nom `<fournisseur>/<id>` sous un préfixe réservé qui ne
  collisionne ni avec le YAML ni avec gateway-sync (ex. `perso/<fournisseur>/<id>`), créés en
  base via `/model/new`, **testés avant d'être gardés** (une complétion courte ; échec → retrait
  et message clair), retirés via `/model/delete`. On ne peut retirer que ses propres modèles
  (préfixe réservé, `db_model`), jamais un modèle du YAML ni un `free/*`/`kilo/*`.
- **Modèle de la Forge** : `forge/defaut` sort du YAML et devient un modèle **en base**, recréé à
  la demande avec les paramètres du modèle choisi (n'importe quel modèle servi, sauf alias
  réservés et gratuits Kilo/OpenRouter si on veut respecter l'option B — à trancher : autoriser
  mais avertir). Le repli `forge/defaut → [gratuit/auto, gratuit/secours]` reste dans
  `router_settings.fallbacks` du YAML — **à prouver** sur LiteLLM v1.86.2 qu'un repli déclaré
  en YAML s'applique à un groupe de modèles créé en base, et que le `cooldown_time` 120 suit.
  Au premier démarrage (base vide), un `forge/defaut` par défaut = `mistral/small` doit exister
  (créé par le Cœur ou par gateway-sync au démarrage — choisir le plus simple et robuste ; la
  Forge ne doit jamais se retrouver sans `forge/defaut`). Choix persisté (config du Cœur) pour
  être recréé si la base LiteLLM est réinitialisée.
- **Sécurité** : toutes les routes qui MODIFIENT le cerveau (`POST/PUT /assistant/config*`,
  `/assistant/cle-*`, `/assistant/routage`, `/assistant/muscle`, `/assistant/persona`,
  `/assistant/langue`, `/assistant/voix`, nouvelles routes modèles/Forge) exigent
  `exiger_session`, plus une liste blanche optionnelle `CERVEAU_ADMINS` (subs Keycloak séparés par
  des virgules ; vide = toute session valide, comportement documenté). NE PAS casser
  `/assistant/chat` et les autres routes utilisées par Telegram/Mini App/S2S (vérifier tous les
  appelants avant de restreindre une route ; lectures `GET` : décider au cas par cas, la config
  contient-elle un secret ?).
- **Front** : ⚙ Cerveau (`core/dashboard.html`) — section « Modèles » : liste des modèles servis
  (origine : YAML / gratuits synchronisés / ajoutés par toi), formulaire fournisseur + id →
  « Ajouter et tester », bouton retirer sur les siens, sélecteur « Modèle de la Forge ». Style
  existant du dashboard.

## Tâches
- T1 — Sécurité des routes de configuration du cerveau (+ `CERVEAU_ADMINS`), tests.
- T2 — Catalogue fournisseurs + ajout/test/retrait de modèles en base (Cœur → LiteLLM), tests.
- T3 — `forge/defaut` en base, sélecteur Forge, défaut au démarrage, preuve du repli YAML sur un
  groupe en base (LiteLLM locale v1.86.2), tests.
- T4 — Front ⚙ Cerveau (section Modèles + sélecteur Forge), vérifié dans un navigateur.

## Déploiement HP (après revue + fusion)
Cœur reconstruit sur le Mac ; YAML gateway (retrait de `forge/defaut`) + recréation ; vérifier que
la Forge répond toujours (`generate_text`) ; preuve : ajouter un modèle depuis l'UI, le retirer,
changer le modèle de la Forge et le voir servir ; accès sans session → refusé.
