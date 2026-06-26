# Brique `images` — moteur d'illustration en API

Produit autonome (port **5950**), **provider-agnostique**. Orchestre plusieurs moteurs
d'images dans un **ordre de préférence** et rapatrie l'image ; **repli honnête** en
placeholder SVG si aucun moteur n'est configuré ou si tous échouent (jamais de fausse image).

## Pourquoi

C'est le 3ᵉ sommet de la synergie **Personnages ↔ Studio ↔ Images** : une fiche de
personnage (nom, rôle, et son empreinte holistique : archétype, éléments) devient un
**prompt visuel cohérent**, puis une image. Idem pour les **couvertures** d'épisodes.

## Fournisseurs livrés

On s'aligne sur le paysage 2026 : un moteur **souverain** auto-hébergé + des **hébergés**
qu'on branche par clé API. Aucune clé n'est embarquée ; sans clé, le fournisseur est
ignoré et on passe au suivant.

| `backend` | Quoi | Config |
|---|---|---|
| `comfyui` | Moteur **souverain** (GPU local/distant), gratuit | `COMFY_URL` |
| `gateway` | **Gateway Workplace** (LiteLLM → OpenRouter) — **aucune clé à poser** | *(rien : réutilise `GATEWAY_KEY`)* |
| `nanobanana` | Google **Nano Banana** (Gemini image) : rapide, bon texte | `GEMINI_API_KEY` |
| `fal` | **fal.ai** : gros catalogue FLUX & co. | `FAL_KEY` (`FAL_MODEL`) |
| `replicate` | **Replicate** : très large catalogue + fine-tunes | `REPLICATE_API_TOKEN` (`REPLICATE_MODEL`) |
| `openai` | **OpenAI** gpt-image-1 | `OPENAI_API_KEY` |
| `pruna` | **Pruna AI** « P-Image » : sub-seconde | `PRUNA_API_KEY` (`PRUNA_API_URL`, `PRUNA_MODEL`) |

**`gateway` marche sans configuration** : il passe par la Gateway déjà branchée (celle de
l'assistant pour le texte), qui détient la clé OpenRouter. On demande l'image via
`/chat/completions` avec un modèle d'image OpenRouter (Nano Banana par défaut,
`IMAGE_GATEWAY_MODEL`). C'est le moteur retenu par défaut dès qu'aucun ComfyUI n'est branché.

L'ordre de préférence se règle par `IMAGE_PROVIDERS` (liste, ex.
`IMAGE_PROVIDERS=gateway` ou `nanobanana,fal,comfyui`). Défaut : `comfyui` → `gateway` →
hébergés. On peut aussi **forcer** un moteur par requête : `{"fournisseur": "gateway", …}`.

### Modèle souverain à pipeline propre (Boogu-Image, FLUX, SD3…)

Le fournisseur `comfyui` sert **n'importe quel** modèle. Pour un modèle dont le graphe ComfyUI
diffère de SDXL (ex. **Boogu-Image** 10B, DiT), exporter le workflow depuis ComfyUI
(« Save (API Format) »), y poser les jetons `{{PROMPT}}` `{{NEGATIF}}` `{{LARGEUR}}`
`{{HAUTEUR}}` `{{SEED}}`, puis pointer `COMFY_WORKFLOW_JSON` dessus — **aucun code à changer**,
repli SDXL si le fichier manque. Pas-à-pas : [`docs/BOOGU.md`](docs/BOOGU.md).

## Endpoints

| Route | Rôle |
|---|---|
| `GET /sante` | moteurs connus, ceux configurés, et le `backend` actif |
| `GET /fournisseurs` | catalogue (nom + configuré ?) — pour proposer un choix côté UI |
| `POST /generer` | `{prompt, negatif?, largeur?, hauteur?, seed?, fournisseur?}` → image |
| `POST /portrait` | `{fiche, fournisseur?}` → prompt visuel dérivé → portrait (synergie Personnages) |
| `POST /couverture` | `{titre, synopsis?, personnages?, fournisseur?}` → couverture (synergie Studio) |
| `GET /fichiers/{nom}` | sert l'image produite (PNG/JPEG/WEBP rapatrié ou placeholder SVG) |

## Exemples de configuration

```bash
# Souverain : ComfyUI local ET distant ouverts en même temps (1re URL joignable utilisée).
export COMFY_URL=http://mon-gpu.exemple:8188,http://host.docker.internal:8188
export COMFY_CKPT=sd_xl_base_1.0.safetensors

# Hébergés : il suffit d'une clé. Exemple « Nano Banana puis fal, sinon le souverain » :
export IMAGE_PROVIDERS=nanobanana,fal,comfyui
export GEMINI_API_KEY=...        # Nano Banana (Gemini)
export FAL_KEY=...               # fal.ai

uvicorn main:app --host 0.0.0.0 --port 5950
```

`GET /sante` indique les moteurs `configures` et celui `actif` ; tant que rien n'est
branché, `backend = placeholder` et la brique le **dit** (jamais de fausse image).

## Tests

```bash
pytest        # tests offline (prompts, fournisseurs, moteur, API), sans réseau ni clé
```

Les appels **live** (fal/Replicate/Nano Banana/OpenAI/Pruna) se prouvent avec de vraies
clés ; le code construit la requête au format de chaque API et tolère les formes de
réponse répandues (`images[].url`, `output`, `b64_json`, `inlineData`).
