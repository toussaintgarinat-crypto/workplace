# Guide — brancher llama.cpp comme cerveau local de l'assistant

> **Statut : documentation, RIEN n'est installé.** À exécuter quand tu veux.
> Cible : ce Mac précis → **Intel x86_64**, i9-8950HK, **16 Go RAM**, Homebrew dans
> `/usr/local`. Pas d'Apple Silicon → inférence **CPU** (l'i9 a AVX2, ça marche,
> mais c'est lent sur les gros modèles : vise du 3B–7B quantisé).

## 0. À savoir avant (honnêteté technique)
- **Ollama (déjà installé) embarque déjà llama.cpp.** Installer llama.cpp seul
  fait surtout sens si tu veux le contrôle direct (`llama-server`, un GGUF précis,
  les options `--jinja`/grammar). Sinon `ollama pull qwen2.5` fait le même travail.
- L'assistant du Cœur **appelle des outils** (function-calling). `llama3`/`gemma4`
  testés ici **ne savent pas** le faire → choisis un modèle **« tools »** :
  **Qwen2.5-Instruct** ou **Llama-3.1-Instruct** (les plus fiables en local).
- Vitesse attendue sur ton CPU : un 7B Q4 ≈ 3–8 tokens/s (utilisable, pas instantané).
  Un 3B Q4 est nettement plus rapide si tu trouves la latence trop haute.

## 1. Installer llama.cpp
```bash
brew install llama.cpp
# fournit : llama-server (API compatible OpenAI), llama-cli, llama-bench…
llama-server --version
```

## 2. Lancer le serveur avec un modèle « tools »
`llama-server` télécharge le GGUF tout seul depuis Hugging Face avec `-hf`.
Le port 8080 est **pris** ici (fleuriste-keycloak) → on prend **8088**.

```bash
# Qwen2.5-7B-Instruct (≈4,7 Go en Q4_K_M) — bon function-calling
llama-server \
  -hf Qwen/Qwen2.5-7B-Instruct-GGUF:Q4_K_M \
  --port 8088 \
  --host 0.0.0.0 \
  --ctx-size 8192 \
  --jinja            # ⬅ active le gabarit de chat AVEC support des outils

# Variante plus rapide si trop lent : Qwen/Qwen2.5-3B-Instruct-GGUF:Q4_K_M
```
- `--jinja` est **indispensable** pour le function-calling (sinon pas de `tool_calls`).
- `--host 0.0.0.0` pour que la Gateway (dans Docker) le joigne via `host.docker.internal`.
- Vérif rapide : `curl http://localhost:8088/v1/models`

## 3. Brancher à la Gateway LiteLLM
Édite `briques/gateway/litellm_config.yaml`, ajoute un modèle qui pointe sur
llama.cpp (provider `openai` = « endpoint compatible OpenAI ») :

```yaml
  - model_name: local/qwen2.5
    litellm_params:
      model: openai/qwen2.5
      api_base: http://host.docker.internal:8088/v1
      api_key: "none"            # llama.cpp n'exige pas de clé
```
Puis redémarre la Gateway pour qu'elle prenne le nouveau modèle :
```bash
cd briques/gateway && docker compose restart
```
> Astuce : le bouton **« Enregistrer la clé »** du panneau Cerveau redémarre aussi
> la Gateway — mais ici c'est un ajout de modèle, donc le `restart` ci-dessus est
> le plus direct.

## 4. Choisir le modèle dans l'assistant
Dashboard → onglet **Assistant** → **⚙ Cerveau** → le menu déroulant doit
maintenant proposer **`local/qwen2.5`** → sélectionne-le → « Choisir ce modèle ».
Le panneau **teste une vraie complétion** : tu vois tout de suite s'il répond.

Puis pose-lui une question qui exige un outil (« combien d'entreprises livrées ? »)
pour vérifier qu'il **appelle vraiment** ses outils en local.

## 5. (Optionnel) Démarrer llama.cpp avec le reste
Pour qu'il se lance avec `Lancer Workplace.command`, on pourrait ajouter au script
un bloc qui démarre `llama-server` en arrière-plan (hors Docker) avant le Cœur.
À faire seulement si tu adoptes cette voie — dis-le-moi et je l'intègre proprement.

## Récapitulatif des chemins possibles
| Voie | Effort | Pilote les outils ? | Coût |
|---|---|---|---|
| **llama.cpp + Qwen2.5** (ce guide) | moyen (install + GGUF) | oui (à valider, `--jinja`) | gratuit, local, lent CPU |
| **Ollama + qwen2.5** (`ollama pull qwen2.5`) | faible | oui (à valider) | gratuit, local, lent CPU |
| **Clé OpenRouter** (panneau Cerveau) | très faible | oui, fiable | payant à l'usage |
| Ollama llama3/gemma4 (déjà là) | nul | **non** | gratuit — chat seulement |
