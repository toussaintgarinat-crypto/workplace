"""Workflow ComfyUI au format API (txt2img SDXL), construit dynamiquement.

ComfyUI s'pilote en POSTant un graphe de NŒUDS JSON sur `/prompt`. On garde ici un
graphe SDXL minimal et standard (chargement modèle → encodage des prompts → latent →
échantillonnage → décodage VAE → sauvegarde), paramétrable par le prompt/négatif/taille/seed.

Le nom du checkpoint est configurable (`COMFY_CKPT`) : selon le modèle installé côté
ComfyUI. Si le modèle diffère, c'est la SEULE valeur à ajuster — le reste du graphe tient.
"""
import os
import random

CKPT = os.getenv("COMFY_CKPT", "sd_xl_base_1.0.safetensors")
SAMPLER = os.getenv("COMFY_SAMPLER", "euler")
STEPS = int(os.getenv("COMFY_STEPS", "28"))
CFG = float(os.getenv("COMFY_CFG", "7.0"))


def construire(prompt: str, negatif: str = "", largeur: int = 1024,
               hauteur: int = 1024, seed=None) -> dict:
    """Graphe ComfyUI (format API) pour un txt2img SDXL. Clés = identifiants de nœuds."""
    graine = int(seed) if seed is not None else random.randint(0, 2**31 - 1)
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
