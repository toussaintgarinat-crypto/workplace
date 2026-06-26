# Brancher Boogu-Image (modèle souverain) sur la brique `images`

> **État : terrain préparé, PAS encore branché.** La couture logicielle existe et est testée ;
> il reste l'étape externe (un ComfyUI avec GPU + les nœuds Boogu). Tant que rien n'est
> configuré, la brique se comporte exactement comme avant (repli `gateway`/placeholder honnête).

## Pourquoi Boogu n'est pas un fournisseur de plus

[Boogu-Image](https://github.com/boogu-project/Boogu-Image) (Apache-2.0) est une famille de
modèles **texte→image / image→image** (Base 10B, Turbo distillé 4 pas, Edit). Il s'exécute
**localement sur GPU** et expose une **intégration ComfyUI**. Or la brique `images` possède déjà
un fournisseur **souverain `comfyui`** (`fournisseurs.py`) : on n'ajoute donc **aucun fournisseur**.
On réutilise `comfyui` — Boogu devient simplement le modèle servi par le ComfyUI ciblé.

Seule subtilité : Boogu est une architecture **DiT**, pas SDXL. Son pipeline ComfyUI
(chargeurs, échantillonneur) n'est **pas** le graphe SDXL par défaut de `workflow.py`. D'où la
couture ci-dessous.

## La couture : `COMFY_WORKFLOW_JSON` (déjà en place)

`workflow.construire()` accepte un **gabarit exporté depuis ComfyUI**. On y substitue 5 jetons :

| Jeton | Remplacé par | Type |
|---|---|---|
| `{{PROMPT}}` | le prompt | chaîne |
| `{{NEGATIF}}` | le prompt négatif | chaîne |
| `{{LARGEUR}}` / `{{HAUTEUR}}` | dimensions | entier |
| `{{SEED}}` | la graine | entier |

Un jeton **seul** dans une valeur (`"{{SEED}}"`) prend sa valeur **typée** (entier) ; un jeton
**inclus** dans du texte (`"portrait, {{NEGATIF}}"`) est remplacé en chaîne. Tout le reste du
graphe est préservé. Fichier absent/illisible → **repli automatique sur le graphe SDXL** (jamais
d'échec silencieux, jamais de fausse image).

## Mise en place (le jour où un GPU est disponible)

1. **GPU + ComfyUI + Boogu** (machine distante = « le Muscle », ou locale si GPU) :
   installer ComfyUI, les nœuds/poids Boogu (cf. HuggingFace/ModelScope du projet), démarrer
   ComfyUI sur `:8188`.
2. **Exporter le workflow** : dans ComfyUI, composer le graphe Boogu (Base ou Turbo), puis
   *Save (API Format)* → `boogu.json`. Remplacer dans ce JSON le prompt/négatif/taille/seed par
   les jetons ci-dessus.
3. **Configurer la brique** (`.env` racine) :
   ```bash
   IMAGE_PROVIDERS=comfyui          # le souverain en tête (ou comfyui,gateway)
   COMFY_URL=http://mon-gpu.exemple:8188,http://host.docker.internal:8188
   COMFY_WORKFLOW_JSON=/data/workflows/boogu.json   # fichier monté dans le conteneur
   ```
   (monter le dossier des workflows en volume sur la brique `images`).
4. **Vérifier** : `GET /sante` doit montrer `comfyui` dans `configures` et `backend=comfyui`
   sur un `POST /generer`. Sinon la brique le **dit** (placeholder honnête).

## Ce qui reste (hors de ce dépôt)

- Le **matériel GPU** (la roadmap prévoit le HP 800 G4 sans GPU costaud → Boogu attend un nœud GPU
  via la brique `calcul`/Netbird, « le Muscle »).
- Le **graphe Boogu exact** (à exporter depuis un ComfyUI réel) — non fabriqué ici exprès :
  on ne devine pas un pipeline qu'on ne peut pas tester.
