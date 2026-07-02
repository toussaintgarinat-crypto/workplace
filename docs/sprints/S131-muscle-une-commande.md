# S131 — Un muscle en UNE commande (auto-inscription)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Brancher un ordinateur (grosse RAM/VRAM) comme nœud de calcul (« le Muscle ») avec **une seule commande collée sur cette machine**, sans jamais éditer le `.env` ni recréer un conteneur côté serveur. Le muscle **s'auto-annonce** à la brique calcul, qui l'enregistre dans le Gateway toute seule.

**Décision de référence :** `docs/decisions/2026-07-01-muscle-une-commande.md` (le *pourquoi*, alternatives, quand rebasculer). Ce sprint est le *comment*.

**Architecture :** on inverse le sens de l'inscription. Aujourd'hui le serveur connaît ses muscles via `CALCUL_NOEUDS` (env figé, `briques/calcul/main.py:33`). On ajoute un **endpoint d'inscription dynamique persisté** sur la brique calcul, un **enregistrement automatique du modèle dans LiteLLM**, et un **script `bootstrap.sh`** servi par la brique qui, sur la machine cible, rejoint le mesh, auto-détecte (ou installe) un runtime LLM OpenAI-compatible taillé à la RAM/VRAM, puis s'inscrit. Tout le reste (élection, sonde, réveil WoL, tête de cascade) existe déjà et n'est pas touché.

**Tech Stack :** FastAPI + httpx (brique calcul existante), POSIX `sh` pour le bootstrap, pytest (tests offline). Aucune nouvelle dépendance lourde. Runtime muscle par défaut = Ollama, mais **auto-détecté** (réutilise LM Studio / llama.cpp / Ollama déjà présents).

## Global Constraints

- Ne **jamais** casser le chemin actuel : les nœuds déclarés par `CALCUL_NOEUDS` (env) restent valides ; le parc dynamique est **fusionné** avec eux.
- Port brique calcul inchangé : **5990**. Endpoint LLM muscle par défaut : `11434` (Ollama).
- **Honnêteté** : aucun nœud inscrit sans qu'il réponde à une sonde ; un enregistrement Gateway qui échoue le dit (pas de faux `modele_gateway`).
- **Sécurité fail-closed** : `POST/DELETE /noeuds` exigent `MUSCLE_KEY` (via `API_KEYS`). Rien exposé hors mesh.
- Tests **offline uniquement** : mocker LiteLLM et les sondes réseau (jamais d'appel réel en test), motif injectable déjà présent dans `noeud.py` (`sonde_fn`/`wol_fn`).
- Langue code : français (cohérence codebase). Commits fréquents, une tâche = un commit.
- Bump version brique calcul `0.1.0 → 0.2.0` (manifest + `main.py`), image `workplace/calcul:0.2.0`.

---

## Fichiers créés / modifiés

```
briques/calcul/
├── noeud.py            # + sauver_noeuds()/charger_noeuds_fichier() ; Noeud depuis dict (from_dict)
├── persistance.py      # NOUVEAU — parc sur disque (CALCUL_PARC_FILE), fusion env + fichier
├── gateway_admin.py    # NOUVEAU — enregistre/retire un modèle dans LiteLLM (POST /model/new), re-push boot
├── main.py             # + POST /noeuds, DELETE /noeuds/{id}, POST /noeuds/republier ; charge parc persisté au boot
├── bootstrap.sh        # NOUVEAU — le one-liner (détection matériel + runtime + mesh + auto-inscription)
├── manifest.json       # version 0.2.0 (capacités inchangées côté LLM — c'est de l'ops)
├── test_noeud.py       # + tests persistance / from_dict
├── test_persistance.py # NOUVEAU — fusion env+fichier, save/load, dédup par id
├── test_gateway_admin.py # NOUVEAU — enregistrement modèle (LiteLLM mocké), échec honnête
└── test_api.py         # + tests POST/DELETE /noeuds (clé requise, persistance, republier)

GUIDE-mesh-netbird.md   # partie F réécrite : « une commande » (l'ancien manuel passe en annexe/repli)
```

Le Cœur (`core/muscle.py`) n'est **pas** modifié : il lit déjà `/muscle` et met le `modele_gateway` en tête de cascade.

---

## Tâches

### Étape 1 — Parc persisté (sans casser l'env)
- [x] `noeud.py` : extraire un `Noeud.from_dict(d)` (réutilisé par `charger_noeuds` **et** l'inscription API) ; ajouter `Noeud.to_dict()` (sérialisation ronde-trip).
- [x] `persistance.py` : `charger_parc()` = fusion `charger_noeuds()` (env) **+** fichier `CALCUL_PARC_FILE` (défaut `/data/noeuds.json`), dédupliqué par `id` (fichier prioritaire) ; `sauver_noeud(n)` / `retirer_noeud(id)` écrivent le fichier atomiquement.
- [x] `main.py` : au boot, `PARC = persistance.charger_parc()` au lieu de `charger_noeuds()`.
- [x] Tests `test_persistance.py` : env seul, fichier seul, fusion, écrasement par id, fichier absent/illisible → tolérant.
- [x] **Commit** : `feat S131 : parc de calcul persisté sur disque (fusion env + fichier)`.

### Étape 2 — Inscription dynamique (API)
- [x] `main.py` : `POST /noeuds` (body = descripteur nœud) — valide `endpoint` obligatoire, **sonde live** avant d'accepter (honnêteté), persiste, renvoie la vue publique. Gardé par `cle_api`.
- [x] `main.py` : `DELETE /noeuds/{id}` — retire du parc + du fichier. Gardé.
- [x] Rendre `MUSCLE_KEY` fonctionnel : documenter `API_KEYS` sur la brique calcul (déjà lu `main.py:30`), la commande d'inscription envoie `X-API-Key`.
- [x] Tests `test_api.py` : inscription sans clé → 401 ; avec clé + nœud qui sonde → 200 + persisté + visible dans `GET /noeuds` ; suppression ; nœud qui ne répond pas → refus honnête.
- [x] **Commit** : `feat S131 : POST/DELETE /noeuds — un muscle s'auto-inscrit (gardé par clé)`.

### Étape 3 — Enregistrement automatique dans le Gateway
- [x] `gateway_admin.py` : `enregistrer_modele(model_name, api_base, cle_master)` → `POST {LITELLM_URL}/model/new` (LiteLLM), `retirer_modele(id)`, best-effort + **verdict honnête** (retourne False si LiteLLM refuse, ne lève pas). Env : `LITELLM_URL`, `LITELLM_MASTER_KEY`.
- [x] Brancher dans `POST /noeuds` : si le nœud annonce un `modele` + `endpoint`, enregistrer `ollama/<modele>` (ou nom fourni) avec `api_base = endpoint mesh` ; stocker le `model_name` retourné comme `modele_gateway` du nœud.
- [x] `main.py` : `POST /noeuds/republier` — re-pousse tous les modèles du parc dans LiteLLM (idempotent) ; appelé **au boot** (contourne le fait que LiteLLM sans DB est en mémoire).
- [x] Tests `test_gateway_admin.py` : LiteLLM mocké OK → `modele_gateway` posé ; LiteLLM en erreur → nœud inscrit **sans** `modele_gateway` (dégradé honnête, pas de crash) ; republier idempotent.
- [x] **Commit** : `feat S131 : la brique calcul enregistre le modèle du muscle dans LiteLLM (+ re-push boot)`.

### Étape 4 — Le script `bootstrap.sh` (le one-liner)
- [x] `main.py` : `GET /bootstrap.sh` sert le script (texte, sans auth — la clé est demandée à l'exécution, pas au téléchargement).
- [x] `bootstrap.sh` (POSIX `sh`) :
  - [x] **Mesh** : si `netbird status` ≠ Connected et `SETUP_KEY` fourni → `curl … netbird install | sh && netbird up --setup-key`. Récupère l'**IP mesh** (interface `wt0` / `netbird status`).
  - [x] **Auto-détecter le runtime existant** : sonder `127.0.0.1:11434/api/tags` (Ollama), `:1234/v1/models` (LM Studio), `:8080/v1/models` (llama.cpp). Si un répond → réutiliser son endpoint + un modèle qu'il sert déjà. **Aucune install.**
  - [x] **Sinon installer Ollama** : `curl … ollama … | sh`, `OLLAMA_HOST=0.0.0.0:11434 ollama serve` (service), puis choisir un modèle par **RAM/VRAM détectée** :
    - Mac : `sysctl -n hw.memsize` ; Linux+NVIDIA : `nvidia-smi --query-gpu=memory.total` ; sinon `/proc/meminfo`.
    - Table : `<8 Go → qwen2.5:3b`, `~16 Go → llama3.1:8b`, `~32 Go → qwen2.5:14b`, `≥64 Go → llama3.3:70b-q4`. Override `MUSCLE_MODELE`.
    - `ollama pull <modele>`.
  - [x] **S'inscrire** : `POST https://<CALCUL_MESH>/muscle/noeuds` avec `X-API-Key: $MUSCLE_KEY`, corps = `{id, nom, endpoint: http://<IP_MESH>:<port>, modele, mac_wol, methode_reveil:["wakeping"], priorite}`. Affiche le verdict.
  - [x] Idempotent : relancer le script ré-inscrit le même `id` (dérivé du hostname) sans doublon.
- [x] Tester le script en **dry-run** (`MUSCLE_DRYRUN=1` : détecte + affiche le payload, n'installe/n'inscrit rien) — vérifiable sans matériel.
- [x] **Commit** : `feat S131 : bootstrap.sh — un muscle en une commande (auto-détection matériel + runtime)`.

### Étape 5 — Doc & clôture
- [x] Réécrire `GUIDE-mesh-netbird.md` partie F en « une commande » ; garder l'ancien manuel en **annexe « repli »**.
- [x] Mettre l'ADR `2026-07-01-muscle-une-commande.md` en **Statut : Adopté** une fois prouvé.
- [x] Marquer **CODE-COMPLET, LIVE DIFFÉRÉ** (preuve sur le HP + un vrai 2ᵉ ordi, groupée à la fin — régime preuve Docker différé).

---

## Definition of Done
- [x] `curl … /muscle/bootstrap.sh | MUSCLE_KEY=… sh` sur une machine (Mac ou PC) la rend visible 🟢 dans ⚙ Cerveau **sans** toucher au `.env` ni recréer de conteneur.
- [x] Le modèle du muscle apparaît dans LiteLLM et une réponse tombe dessus (`modele_utilise` dans le journal d'usage).
- [x] `MUSCLE_KEY` absente ⇒ inscription refusée (401). Rien exposé hors mesh.
- [x] Le chemin `CALCUL_NOEUDS` (env) fonctionne toujours (rétrocompat prouvée par test).
- [x] Tests offline verts (persistance + API + gateway_admin + dry-run script).

---

> **CODE-COMPLET, LIVE DIFFÉRÉ** — Preuve sur le HP + un vrai 2ᵉ ordi groupée à la fin (régime preuve Docker différé).

## Hors périmètre (différé)
- LiteLLM en mode base de données (vraie persistance des modèles) — cf. déclencheur de bascule de l'ADR.
- Réveil/sommeil automatique du muscle pour l'énergie (WoL est déjà là, mais BIOS/carte = ops manuelles).
- Quotas / routage par utilisateur (épopée multi-tenant).
