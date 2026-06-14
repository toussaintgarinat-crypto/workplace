# Brique `video` — moteur de génération vidéo en API

Produit autonome (port **5970**), **provider-agnostique** (miroir de la brique `images`).
Orchestre plusieurs moteurs vidéo dans un **ordre de préférence**, rapatrie le MP4 et le
sert depuis son propre stockage ; **repli honnête** en placeholder SVG si aucun moteur
n'est configuré ou si tous échouent (jamais de fausse vidéo).

## Pourquoi

4ᵉ sommet de la synergie créative, après Personnages ↔ Studio ↔ Images : le **Studio**
(S55) compose la brique vidéo sans l'absorber. Deux synergies :

- **bande-annonce d'épisode** (Studio → Vidéo) : titre + synopsis → clip teaser ;
- **animation de portrait** (Personnages → Vidéo) : un portrait (image) + la fiche
  holistique du personnage → clip animé (image→vidéo).

Le Mac de dev n'a **pas de GPU** → pas de moteur souverain local ici : on s'appuie sur des
fournisseurs hébergés, sinon placeholder honnête.

## Fournisseurs livrés

Aucune clé n'est embarquée ; sans clé, le fournisseur est ignoré et on passe au suivant.

| `backend` | Quoi | Config |
|---|---|---|
| `fal` | **fal.ai** : gros catalogue vidéo (Kling, Wan, LTX, Veo…) | `FAL_KEY` (`FAL_VIDEO_MODEL`) |
| `replicate` | **Replicate** : large catalogue vidéo, `Prefer: wait` synchrone | `REPLICATE_API_TOKEN` (`REPLICATE_VIDEO_MODEL`) |
| `luma` | **Luma « Dream Machine »** (Ray) : jobs + polling | `LUMAAI_API_KEY` (`LUMA_VIDEO_MODEL`) |
| `runway` | **Runway « Gen »** : tâches + polling | `RUNWAY_API_KEY` (`RUNWAY_VIDEO_MODEL`, `RUNWAY_API_VERSION`) |
| `gateway` | **Gateway Workplace** (LiteLLM → OpenRouter) — **aucune clé à poser** | *(rien : réutilise `GATEWAY_KEY`)* |

La génération vidéo est **asynchrone** chez la plupart des fournisseurs (on soumet un job,
on interroge un statut jusqu'au MP4). La base `_HTTP` gère les deux cas (réponse synchrone
ou polling d'un `_statut_url`). `gateway` est **expérimental** côté vidéo : il marche sans
config, mais ne rend une vidéo que si le modèle OpenRouter choisi en produit une ; sinon on
retombe sur le fournisseur suivant, puis le placeholder.

L'ordre se règle par `VIDEO_PROVIDERS` (liste, ex. `VIDEO_PROVIDERS=fal,replicate`). Défaut :
`fal` → `replicate` → `luma` → `runway` → `gateway`. On peut **forcer** un moteur par
requête : `{"fournisseur": "fal", …}`.

## Endpoints

| Route | Rôle |
|---|---|
| `GET /sante` | moteurs connus, ceux configurés, et le `backend` actif |
| `GET /fournisseurs` | catalogue (nom + configuré ?) — pour proposer un choix côté UI |
| `POST /generer` | `{prompt, image_url?, secondes?, seed?, fournisseur?}` → vidéo |
| `POST /teaser` | `{titre, synopsis?, personnages?, secondes?, fournisseur?}` → bande-annonce (synergie Studio) |
| `POST /animer` | `{fiche, image_url?, secondes?, fournisseur?}` → clip animé du perso (synergie Personnages) |
| `GET /fichiers/{nom}` | sert la vidéo produite (MP4/WEBM/MOV rapatriée ou placeholder SVG) |

## Exemples de configuration

```bash
# Le plus simple : passer par la Gateway (aucune clé vidéo à poser).
export VIDEO_PROVIDERS=gateway
export GATEWAY_KEY=...            # déjà posée pour l'assistant
export VIDEO_GATEWAY_MODEL=google/veo-3-fast

# Ou un fournisseur vidéo natif (une clé suffit). Exemple « fal puis Replicate » :
export VIDEO_PROVIDERS=fal,replicate
export FAL_KEY=...               # fal.ai
export REPLICATE_API_TOKEN=...   # Replicate

uvicorn main:app --host 0.0.0.0 --port 5970
```

`GET /sante` indique les moteurs `configures` et celui `actif` ; tant que rien n'est
branché, `backend = placeholder` et la brique le **dit** (jamais de fausse vidéo).

## Tests

```bash
pytest        # tests offline (prompts, fournisseurs, moteur, API), sans réseau ni clé
```

Les appels **live** (fal/Replicate/Luma/Runway) se prouvent avec de vraies clés ; le code
construit la requête au format de chaque API et tolère les formes de réponse répandues
(`video.url`, `output`, `assets.video`) + le polling des jobs asynchrones.
