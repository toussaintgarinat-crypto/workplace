"""Workflow ComfyUI au format API (txt2img SDXL), construit dynamiquement.

ComfyUI s'pilote en POSTant un graphe de NŒUDS JSON sur `/prompt`. On garde ici un
graphe SDXL minimal et standard (chargement modèle → encodage des prompts → latent →
échantillonnage → décodage VAE → sauvegarde), paramétrable par le prompt/négatif/taille/seed.

Le nom du checkpoint est configurable (`COMFY_CKPT`) : selon le modèle installé côté
ComfyUI. Si le modèle diffère, c'est la SEULE valeur à ajuster — le reste du graphe tient.

Modèle À ARCHITECTURE DIFFÉRENTE (Boogu-Image, FLUX, SD3…) : leur pipeline ComfyUI n'est PAS
celui de SDXL (chargeurs/échantillonneurs propres). Plutôt que de coder un graphe par modèle,
on accepte un **gabarit exporté depuis ComfyUI** (« Save (API Format) ») via
`COMFY_WORKFLOW_JSON` (chemin d'un fichier monté). On y substitue les jetons
`{{PROMPT}}` / `{{NEGATIF}}` / `{{LARGEUR}}` / `{{HAUTEUR}}` / `{{SEED}}` : on branche ainsi
N'IMPORTE QUEL modèle SANS toucher au code. Absent/illisible → repli sur le graphe SDXL.
"""
import json
import os
import random

CKPT = os.getenv("COMFY_CKPT", "sd_xl_base_1.0.safetensors")
SAMPLER = os.getenv("COMFY_SAMPLER", "euler")
STEPS = int(os.getenv("COMFY_STEPS", "28"))
CFG = float(os.getenv("COMFY_CFG", "7.0"))


def _injecter(noeud, jetons: dict):
    """Substitue récursivement les jetons dans un graphe exporté. Une chaîne ÉGALE à un jeton
    (`"{{SEED}}"`) prend sa valeur TYPÉE (int) ; un jeton inclus dans du texte est remplacé en
    chaîne (`"un chat, {{NEGATIF}}"`). Préserve la forme du graphe pour le reste."""
    if isinstance(noeud, dict):
        return {k: _injecter(v, jetons) for k, v in noeud.items()}
    if isinstance(noeud, list):
        return [_injecter(v, jetons) for v in noeud]
    if isinstance(noeud, str):
        if noeud in jetons:                       # jeton seul → valeur typée
            return jetons[noeud]
        for jeton, valeur in jetons.items():      # jeton inclus dans du texte → str
            if jeton in noeud:
                noeud = noeud.replace(jeton, str(valeur))
        return noeud
    return noeud


def _gabarit_personnalise(prompt, negatif, largeur, hauteur, graine):
    """Charge le gabarit `COMFY_WORKFLOW_JSON` et y injecte les jetons. None si non configuré
    ou illisible (le moteur retombe alors sur le graphe SDXL — repli honnête, jamais d'échec
    silencieux : un fichier illisible n'invente pas d'image, il rend la main au défaut)."""
    chemin = os.getenv("COMFY_WORKFLOW_JSON")
    if not chemin:
        return None
    try:
        with open(chemin, encoding="utf-8") as f:
            graphe = json.load(f)
    except (OSError, ValueError):
        return None
    return _injecter(graphe, {
        "{{PROMPT}}": prompt, "{{NEGATIF}}": negatif,
        "{{LARGEUR}}": int(largeur), "{{HAUTEUR}}": int(hauteur), "{{SEED}}": int(graine),
    })


def construire(prompt: str, negatif: str = "", largeur: int = 1024,
               hauteur: int = 1024, seed=None) -> dict:
    """Graphe ComfyUI (format API). Gabarit personnalisé (`COMFY_WORKFLOW_JSON`) si présent —
    pour brancher un modèle à pipeline propre (Boogu, FLUX…) ; sinon txt2img SDXL par défaut."""
    graine = int(seed) if seed is not None else random.randint(0, 2**31 - 1)
    personnalise = _gabarit_personnalise(prompt, negatif, largeur, hauteur, graine)
    if personnalise is not None:
        return personnalise
    return {
        "4": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": CKPT}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negatif, "clip": ["4", 1]}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": int(largeur), "height": int(hauteur), "batch_size": 1}},
        "3": {"class_type": "KSampler",
              "inputs": {"seed": graine, "steps": STEPS, "cfg": CFG,
                         "sampler_name": SAMPLER, "scheduler": "normal", "denoise": 1.0,
                         "model": ["4", 0], "positive": ["6", 0],
                         "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode",
              "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": "oria", "images": ["8", 0]}},
    }
