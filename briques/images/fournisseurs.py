"""Fournisseurs d'images — registre PROVIDER-AGNOSTIQUE.

Une image peut venir de plusieurs moteurs, essayés dans un ORDRE de préférence
configurable (`IMAGE_PROVIDERS`). Chaque fournisseur expose la même interface minimale :

    nom            : identifiant court (clé du registre, valeur de `backend`) ;
    disponible()   : la config est-elle là (clé API / URL) ? — sync, SANS réseau ;
    async generer(prompt, negatif, largeur, hauteur, seed) -> bytes   # image brute, sinon LÈVE.

Le moteur (moteur.py) balaie les fournisseurs DISPONIBLES dans l'ordre et retient la
PREMIÈRE image obtenue ; si aucun ne répond, il rend un placeholder honnête. On ne fait
jamais passer un placeholder pour une vraie image, et on n'invente jamais d'image.

Fournisseurs livrés (cf. paysage 2026 — on s'aligne sur les conventions répandues) :
  • comfyui     — moteur SOUVERAIN auto-hébergé (GPU local/distant), cf. workflow.py ;
  • nanobanana  — Google « Nano Banana » (Gemini image) : rapide + bon rendu de texte ;
  • fal         — fal.ai : gros catalogue (FLUX & co.), facturation à la sortie ;
  • replicate   — Replicate : très large catalogue + fine-tunes communautaires ;
  • openai      — OpenAI gpt-image-1 ;
  • pruna       — Pruna AI « P-Image » : génération sub-seconde, REST.

Aucune clé n'est embarquée : chaque fournisseur se configure par variables d'env (cf.
.env.example). Sans clé, le fournisseur est simplement « non disponible » et ignoré —
on retombe alors sur le suivant, puis sur le placeholder honnête. Le MODÈLE de chaque
fournisseur est lui aussi paramétrable (FAL_MODEL, REPLICATE_MODEL, …) : on garde le
moteur ouvert sans figer un choix.
"""
import asyncio
import base64
import os
import time
from typing import Optional

import httpx

import workflow


# ── Décodage : retrouver une image dans une réponse JSON, quelle que soit sa forme ──
def _b64(s: str) -> bytes:
    """Décode du base64, en tolérant un préfixe `data:...;base64,`."""
    return base64.b64decode(s.split(",")[-1])


def _cherche_image(obj):
    """Retrouve une image dans une réponse JSON arbitraire.

    Renvoie ('url', str) ou ('b64', str), ou None. Couvre les conventions répandues
    sans coupler le code à un fournisseur précis :
      • fal       → {"images": [{"url": …}]}
      • replicate → {"output": "url" | ["url", …]}
      • openai    → {"data": [{"b64_json": …}]}  (ou {"url": …})
      • gemini    → {"candidates": [{"content": {"parts": [{"inlineData": {"data": …}}]}}]}
      • openrouter (chat) → {"choices": [{"message": {"images": [{"image_url": {"url": "data:…"}}]}}]}
    On descend récursivement les conteneurs usuels ; le premier visuel trouvé gagne."""
    if obj is None:
        return None
    if isinstance(obj, str):
        s = obj.strip()
        if s.startswith("http"):
            return ("url", s)
        if s.startswith("data:"):                           # data:image/png;base64,…
            return ("b64", s)
        if len(s) > 256 and not s.startswith(("{", "[")):   # gros blob = base64 probable
            return ("b64", s)
        return None
    if isinstance(obj, dict):
        for cle in ("b64_json", "inlineData", "inline_data"):
            v = obj.get(cle)
            if isinstance(v, dict):           # gemini : {"inlineData": {"data": …}}
                v = v.get("data")
            if isinstance(v, str) and v:
                return ("b64", v)
        for cle in ("url", "image_url", "image"):
            v = obj.get(cle)
            if isinstance(v, dict):           # openrouter chat : {"image_url": {"url": …}}
                v = v.get("url")
            if isinstance(v, str):
                if v.startswith("http"):
                    return ("url", v)
                if v.startswith("data:"):
                    return ("b64", v)
        for cle in ("images", "data", "output", "candidates", "content", "parts",
                    "artifacts", "result", "choices", "message", "delta"):
            if cle in obj:
                trouve = _cherche_image(obj[cle])
                if trouve:
                    return trouve
        return None
    if isinstance(obj, (list, tuple)):
        for el in obj:
            trouve = _cherche_image(el)
            if trouve:
                return trouve
    return None


async def _resoudre(client: httpx.AsyncClient, trouve) -> Optional[bytes]:
    """('url'|'b64', valeur) → octets de l'image (télécharge l'URL, ou décode le b64)."""
    if not trouve:
        return None
    typ, val = trouve
    if typ == "b64":
        return _b64(val)
    r = await client.get(val)
    r.raise_for_status()
    return r.content


# ── Fournisseurs HTTP « one-shot » : 1 requête JSON → 1 image (url ou b64) ──
class _HTTP:
    """Base commune : un POST JSON suffit. On ne spécialise que `_requete` et `disponible`."""
    nom = ""
    timeout = 120

    def disponible(self) -> bool:
        raise NotImplementedError

    def _requete(self, prompt, negatif, largeur, hauteur, seed, modele=None):
        """→ (url, headers, json_body). À spécialiser par fournisseur.

        `modele` (optionnel) : override ponctuel, prioritaire sur la variable d'env du
        fournisseur — SEULE la classe Gateway l'utilise réellement (comparatif de
        modèles OpenRouter) ; les autres l'acceptent pour une signature uniforme mais
        l'ignorent (YAGNI : ils ne sont pas configurés en prod)."""
        raise NotImplementedError

    async def generer(self, prompt, negatif, largeur, hauteur, seed, modele=None) -> Optional[bytes]:
        url, headers, body = self._requete(prompt, negatif, largeur, hauteur, seed, modele)
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(url, headers=headers, json=body)
            r.raise_for_status()
            return await _resoudre(c, _cherche_image(r.json()))


class Gateway(_HTTP):
    """Passe par la GATEWAY Workplace (LiteLLM → OpenRouter) — déjà utilisée par l'assistant
    pour le texte. AUCUNE clé d'image à configurer : on réutilise la clé OpenRouter déjà
    posée dans l'env de la Gateway. On demande l'image via /chat/completions (modalité image)
    avec un modèle d'image OpenRouter — Nano Banana par défaut, paramétrable par env OU par
    requête (le `modele` explicite gagne toujours sur `IMAGE_GATEWAY_MODEL`, cf. comparatif
    de modèles dans l'Atelier Images & Vidéo).

    Réponse OpenRouter : l'image arrive dans choices[].message.images[].image_url.url
    (data URI base64), gérée par `_cherche_image`."""
    nom = "gateway"

    def _url(self):
        return os.getenv("GATEWAY_URL", "http://host.docker.internal:4001").rstrip("/")

    def disponible(self):
        # la clé OpenRouter vit côté Gateway ; ici il suffit de savoir joindre la Gateway.
        return bool(os.getenv("GATEWAY_KEY"))

    def _requete(self, prompt, negatif, largeur, hauteur, seed, modele=None):
        modele = modele or os.getenv("IMAGE_GATEWAY_MODEL", "google/gemini-2.5-flash-image")
        texte = prompt if not negatif else f"{prompt}\n\nÀ éviter : {negatif}"
        body = {"model": modele, "modalities": ["image", "text"],
                "messages": [{"role": "user", "content": texte}]}
        return (f"{self._url()}/v1/chat/completions",
                {"Authorization": f"Bearer {os.getenv('GATEWAY_KEY')}"}, body)


class NanoBanana(_HTTP):
    """Google « Nano Banana » (Gemini image). Réponse : inlineData base64."""
    nom = "nanobanana"

    def _cle(self):
        return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    def disponible(self):
        return bool(self._cle())

    def _requete(self, prompt, negatif, largeur, hauteur, seed, modele=None):
        modele = os.getenv("NANOBANANA_MODEL", "gemini-2.5-flash-image")
        texte = prompt if not negatif else f"{prompt}\n\nÀ éviter : {negatif}"
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{modele}:generateContent?key={self._cle()}")
        return url, {}, {"contents": [{"parts": [{"text": texte}]}]}


class Fal(_HTTP):
    """fal.ai — endpoint synchrone https://fal.run/{modele}. Réponse : images[].url."""
    nom = "fal"

    def disponible(self):
        return bool(os.getenv("FAL_KEY"))

    def _requete(self, prompt, negatif, largeur, hauteur, seed, modele=None):
        modele = os.getenv("FAL_MODEL", "fal-ai/flux/schnell")
        body = {"prompt": prompt, "num_images": 1,
                "image_size": {"width": int(largeur), "height": int(hauteur)}}
        if negatif:
            body["negative_prompt"] = negatif
        if seed is not None:
            body["seed"] = int(seed)
        return (f"https://fal.run/{modele}",
                {"Authorization": f"Key {os.getenv('FAL_KEY')}"}, body)


class Replicate(_HTTP):
    """Replicate — `Prefer: wait` rend l'appel synchrone (pas de polling). Réponse : output."""
    nom = "replicate"
    timeout = 90

    def disponible(self):
        return bool(os.getenv("REPLICATE_API_TOKEN"))

    def _requete(self, prompt, negatif, largeur, hauteur, seed, modele=None):
        modele = os.getenv("REPLICATE_MODEL", "black-forest-labs/flux-schnell")
        inp = {"prompt": prompt, "width": int(largeur), "height": int(hauteur)}
        if seed is not None:
            inp["seed"] = int(seed)
        return (f"https://api.replicate.com/v1/models/{modele}/predictions",
                {"Authorization": f"Bearer {os.getenv('REPLICATE_API_TOKEN')}",
                 "Prefer": "wait"},
                {"input": inp})


class OpenAI(_HTTP):
    """OpenAI gpt-image-1. Réponse : data[].b64_json. Taille = format autorisé le + proche."""
    nom = "openai"

    def disponible(self):
        return bool(os.getenv("OPENAI_API_KEY"))

    def _requete(self, prompt, negatif, largeur, hauteur, seed, modele=None):
        modele = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
        body = {"model": modele, "prompt": prompt, "n": 1,
                "size": _taille_openai(largeur, hauteur)}
        return ("https://api.openai.com/v1/images/generations",
                {"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"}, body)


class Pruna(_HTTP):
    """Pruna AI « P-Image » (sub-seconde). Endpoint/modèle paramétrables (API récente) :
    le code reste tolérant — la réponse peut être une URL ou un b64, `_cherche_image` gère."""
    nom = "pruna"

    def disponible(self):
        return bool(os.getenv("PRUNA_API_KEY"))

    def _requete(self, prompt, negatif, largeur, hauteur, seed, modele=None):
        url = os.getenv("PRUNA_API_URL", "https://api.pruna.ai/v1/inference")
        body = {"model": os.getenv("PRUNA_MODEL", "p-image"), "prompt": prompt,
                "width": int(largeur), "height": int(hauteur)}
        if negatif:
            body["negative_prompt"] = negatif
        if seed is not None:
            body["seed"] = int(seed)
        return url, {"Authorization": f"Bearer {os.getenv('PRUNA_API_KEY')}"}, body


def _taille_openai(largeur, hauteur) -> str:
    """gpt-image-1 n'accepte que 1024x1024 / 1024x1536 / 1536x1024 : on prend le plus proche."""
    r = (largeur or 1) / (hauteur or 1)
    if r > 1.2:
        return "1536x1024"
    if r < 0.83:
        return "1024x1536"
    return "1024x1024"


# ── ComfyUI : moteur SOUVERAIN auto-hébergé (multi-étapes, cf. workflow.py) ──
def _premiere_image_comfy(outputs: dict):
    """Premiers {filename, subfolder, type} trouvés dans les sorties d'un job ComfyUI."""
    for noeud in (outputs or {}).values():
        for img in (noeud.get("images") or []):
            if img.get("filename"):
                return {"filename": img["filename"],
                        "subfolder": img.get("subfolder", ""),
                        "type": img.get("type", "output")}
    return None


class ComfyUI:
    """ComfyUI. `COMFY_URL` = liste d'URLs (distant rapide, local en repli), essayées dans
    l'ordre : la 1re joignable sert. POST /prompt → poll /history → GET /view."""
    nom = "comfyui"

    def urls(self):
        return [u.strip().rstrip("/")
                for u in os.getenv("COMFY_URL", "").split(",") if u.strip()]

    def disponible(self):
        return bool(self.urls())

    async def _joignable(self, client, url):
        try:
            r = await client.get(f"{url}/system_stats")
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    async def premier_joignable(self) -> Optional[str]:
        urls = self.urls()
        if not urls:
            return None
        async with httpx.AsyncClient(timeout=4) as c:
            for url in urls:
                if await self._joignable(c, url):
                    return url
        return None

    async def generer(self, prompt, negatif, largeur, hauteur, seed, modele=None) -> Optional[bytes]:
        cible = await self.premier_joignable()
        if not cible:
            raise RuntimeError("Aucun ComfyUI joignable")
        attente = int(os.getenv("COMFY_ATTENTE_S", "150"))
        wf = workflow.construire(prompt, negatif, largeur, hauteur, seed)
        async with httpx.AsyncClient(timeout=attente + 30) as c:
            r = await c.post(f"{cible}/prompt", json={"prompt": wf})
            r.raise_for_status()
            pid = r.json().get("prompt_id")
            for _ in range(attente):
                h = await c.get(f"{cible}/history/{pid}")
                job = (h.json() or {}).get(pid)
                if job and job.get("outputs"):
                    img = _premiere_image_comfy(job["outputs"])
                    if img:
                        v = await c.get(f"{cible}/view", params=img)
                        v.raise_for_status()
                        return v.content
                await asyncio.sleep(1)
        raise TimeoutError("Rendu ComfyUI trop long (timeout)")


# ── Registre + ordre de préférence ──────────────────────────────
REGISTRE = {f.nom: f for f in
            (ComfyUI(), Gateway(), NanoBanana(), Fal(), Replicate(), OpenAI(), Pruna())}

# Défaut : souverain d'abord (gratuit/auto-hébergé) ; puis la GATEWAY, qui marche SANS
# config supplémentaire (clé OpenRouter déjà posée côté Gateway) ; puis les hébergés à
# clé propre. Surchargé par `IMAGE_PROVIDERS` (liste, ex. "gateway" ou "nanobanana,fal").
ORDRE_DEFAUT = ["comfyui", "gateway", "nanobanana", "fal", "replicate", "openai", "pruna"]


def ordre() -> list:
    """Ordre de préférence effectif (filtré sur les fournisseurs connus du registre)."""
    brut = [n.strip().lower() for n in os.getenv("IMAGE_PROVIDERS", "").split(",") if n.strip()]
    noms = brut or ORDRE_DEFAUT
    return [n for n in noms if n in REGISTRE]


def disponibles() -> list:
    """Fournisseurs configurés (clé/URL présente), dans l'ordre de préférence."""
    return [n for n in ordre() if REGISTRE[n].disponible()]


# ── Modèles image OpenRouter (comparatif, Atelier Images & Vidéo) ──────────
# Endpoint PUBLIC (pas de clé requise pour lister). Cache mémoire 1h : évite de re-frapper
# OpenRouter à chaque ouverture de l'onglet Comparatif. Jamais de liste inventée : si
# l'appel échoue et qu'un cache existe encore (même périmé), on le sert plutôt que de
# casser l'UI ; si le cache est vide, l'erreur est propagée telle quelle.
_CACHE_TTL_S = 3600
_cache: dict = {"ts": 0.0, "modeles": []}


async def modeles_image_openrouter() -> list:
    """Modèles OpenRouter capables de générer une image (architecture.output_modalities
    contient "image"), routeurs auto (openrouter/auto*) exclus — ils choisissent eux-mêmes
    le modèle sous le capot, ce qui fausserait un comparatif."""
    maintenant = time.time()
    if _cache["modeles"] and maintenant - _cache["ts"] < _CACHE_TTL_S:
        return _cache["modeles"]
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://openrouter.ai/api/v1/models")
            r.raise_for_status()
            data = r.json()
    except Exception:
        if _cache["modeles"]:
            return _cache["modeles"]
        raise
    modeles = sorted(
        (
            {"id": m["id"], "prix_image": (m.get("pricing") or {}).get("image")}
            for m in data.get("data", [])
            if "image" in ((m.get("architecture") or {}).get("output_modalities") or [])
            and not m["id"].startswith("openrouter/auto")
        ),
        key=lambda m: m["id"],
    )
    _cache["modeles"], _cache["ts"] = modeles, maintenant
    return modeles
