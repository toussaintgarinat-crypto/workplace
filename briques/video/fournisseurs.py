"""Fournisseurs de VIDÉO — registre PROVIDER-AGNOSTIQUE (miroir de la brique images).

Une vidéo peut venir de plusieurs moteurs, essayés dans un ORDRE de préférence
configurable (`VIDEO_PROVIDERS`). Chaque fournisseur expose la même interface minimale :

    nom            : identifiant court (clé du registre, valeur de `backend`) ;
    disponible()   : la config est-elle là (clé API) ? — sync, SANS réseau ;
    async generer(prompt, image_url, secondes, seed) -> bytes   # vidéo brute, sinon LÈVE.

Le moteur (moteur.py) balaie les fournisseurs DISPONIBLES dans l'ordre et retient la
PREMIÈRE vidéo obtenue ; si aucun ne répond, il rend un placeholder honnête. On ne fait
jamais passer un placeholder pour une vraie vidéo, et on n'invente jamais de vidéo.

La génération vidéo est INTRINSÈQUEMENT lente (souvent asynchrone : on soumet un job, on
interroge un statut jusqu'à obtenir l'URL du .mp4). La base `_HTTP` gère les deux cas :
réponse synchrone (vidéo directement présente) OU job asynchrone (un `_statut_url` à
interroger en boucle). Le Mac n'a pas de GPU → pas de moteur souverain local ici : on
s'appuie sur des fournisseurs hébergés, sinon placeholder honnête.

Fournisseurs livrés (paysage 2026 — conventions répandues) :
  • fal        — fal.ai : gros catalogue de modèles vidéo (Kling, Wan, LTX, Veo…) ;
  • replicate  — Replicate : large catalogue vidéo + `Prefer: wait` synchrone ;
  • luma       — Luma « Dream Machine » (Ray) : API de jobs, polling ;
  • runway     — Runway « Gen » : API de tâches, polling, en-tête de version ;
  • gateway    — via la GATEWAY Workplace (LiteLLM→OpenRouter) : zéro clé propre.

Aucune clé n'est embarquée : chaque fournisseur se configure par variables d'env (cf.
.env.example). Sans clé, le fournisseur est « non disponible » et ignoré — on retombe sur
le suivant, puis sur le placeholder honnête. Le MODÈLE de chaque fournisseur est lui aussi
paramétrable (FAL_VIDEO_MODEL, REPLICATE_VIDEO_MODEL, …) : on garde le moteur ouvert.
"""
import asyncio
import base64
import os
from typing import Optional

import httpx


# ── Décodage : retrouver une vidéo dans une réponse JSON, quelle que soit sa forme ──
def _b64(s: str) -> bytes:
    """Décode du base64, en tolérant un préfixe `data:...;base64,`."""
    return base64.b64decode(s.split(",")[-1])


_EXT_IMAGE = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")


def _cherche_video(obj):
    """Retrouve une vidéo dans une réponse JSON arbitraire.

    Renvoie ('url', str) ou ('b64', str), ou None. On PRIORISE les clés explicitement
    vidéo (`video`, `mp4`, `video_url`) pour ne pas confondre la vidéo avec une vignette
    image. Couvre les conventions répandues sans coupler à un fournisseur précis :
      • fal       → {"video": {"url": …}}
      • replicate → {"output": "url" | ["url", …]}
      • luma      → {"assets": {"video": "url"}}
      • runway    → {"output": ["url"]}  (après statut SUCCEEDED)
    On descend récursivement les conteneurs usuels ; le premier visuel vidéo gagne."""
    if obj is None:
        return None
    if isinstance(obj, str):
        s = obj.strip()
        if s.startswith("http") and not s.lower().split("?")[0].endswith(_EXT_IMAGE):
            return ("url", s)
        if s.startswith("data:video"):
            return ("b64", s)
        return None
    if isinstance(obj, dict):
        # 1) clés explicitement vidéo (la valeur peut être une str ou un dict {url:…})
        for cle in ("video", "video_url", "mp4", "videoUri", "video_uri"):
            v = obj.get(cle)
            if isinstance(v, dict):
                v = v.get("url") or v.get("uri")
            if isinstance(v, str) and v.strip():
                trouve = _cherche_video(v)
                if trouve:
                    return trouve
        # 2) URL/sortie génériques (filtrées sur « pas une image »)
        for cle in ("url", "uri", "output"):
            trouve = _cherche_video(obj.get(cle))
            if trouve:
                return trouve
        # 3) descente récursive dans les conteneurs habituels
        for cle in ("assets", "data", "result", "outputs", "videos", "artifacts",
                    "choices", "message", "delta", "content", "parts"):
            if cle in obj:
                trouve = _cherche_video(obj[cle])
                if trouve:
                    return trouve
        return None
    if isinstance(obj, (list, tuple)):
        for el in obj:
            trouve = _cherche_video(el)
            if trouve:
                return trouve
    return None


async def _resoudre(client: httpx.AsyncClient, trouve) -> Optional[bytes]:
    """('url'|'b64', valeur) → octets de la vidéo (télécharge l'URL, ou décode le b64)."""
    if not trouve:
        return None
    typ, val = trouve
    if typ == "b64":
        return _b64(val)
    r = await client.get(val)
    r.raise_for_status()
    return r.content


# ── Base HTTP : soumission + polling tolérant ────────────────────
class _HTTP:
    """Base commune. Un POST JSON soumet le job. Si la vidéo est déjà là (fournisseur
    synchrone), on la rend ; sinon on interroge `_statut_url(reponse)` en boucle jusqu'à
    obtenir la vidéo (fournisseur asynchrone) ou expiration."""
    nom = ""
    timeout = 120
    attente_s = int(os.getenv("VIDEO_ATTENTE_S", "300"))   # plafond de polling
    intervalle_s = 3

    def disponible(self) -> bool:
        raise NotImplementedError

    def _requete(self, prompt, image_url, secondes, seed):
        """→ (url, headers, json_body). À spécialiser par fournisseur."""
        raise NotImplementedError

    def _statut_url(self, reponse: dict):
        """URL à interroger en GET pour un job asynchrone (None si synchrone)."""
        return None

    def _entetes_statut(self) -> dict:
        return {}

    async def generer(self, prompt, image_url, secondes, seed) -> Optional[bytes]:
        url, headers, body = self._requete(prompt, image_url, secondes, seed)
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(url, headers=headers, json=body)
            r.raise_for_status()
            rep = r.json()
            trouve = _cherche_video(rep)
            if trouve:
                return await _resoudre(c, trouve)
            statut = self._statut_url(rep)
            if not statut:
                return None
            tours = max(1, self.attente_s // self.intervalle_s)
            for _ in range(tours):
                await asyncio.sleep(self.intervalle_s)
                g = await c.get(statut, headers=self._entetes_statut())
                g.raise_for_status()
                trouve = _cherche_video(g.json())
                if trouve:
                    return await _resoudre(c, trouve)
            raise TimeoutError(f"Rendu vidéo {self.nom} trop long (timeout)")


class Fal(_HTTP):
    """fal.ai — file d'attente https://queue.fal.run/{modèle}. Soumission → {response_url}
    (et/ou {status_url}). On interroge response_url jusqu'à obtenir {video:{url}}."""
    nom = "fal"
    timeout = 90

    def disponible(self):
        return bool(os.getenv("FAL_KEY"))

    def _entetes(self):
        return {"Authorization": f"Key {os.getenv('FAL_KEY')}"}

    def _entetes_statut(self):
        return self._entetes()

    def _requete(self, prompt, image_url, secondes, seed):
        modele = os.getenv("FAL_VIDEO_MODEL", "fal-ai/ltx-video")
        body = {"prompt": prompt}
        if image_url:
            body["image_url"] = image_url
        if secondes:
            body["duration"] = int(secondes)
        if seed is not None:
            body["seed"] = int(seed)
        return f"https://queue.fal.run/{modele}", self._entetes(), body

    def _statut_url(self, reponse):
        # fal renvoie response_url (résultat) et/ou status_url (état) ; on poll le résultat.
        return reponse.get("response_url") or reponse.get("status_url")


class Replicate(_HTTP):
    """Replicate — `Prefer: wait` rend l'appel synchrone (pas de polling). Réponse : output.
    Si le modèle dépasse la fenêtre `wait`, on retombe sur le polling de `urls.get`."""
    nom = "replicate"
    timeout = 120

    def disponible(self):
        return bool(os.getenv("REPLICATE_API_TOKEN"))

    def _entetes_statut(self):
        return {"Authorization": f"Bearer {os.getenv('REPLICATE_API_TOKEN')}"}

    def _requete(self, prompt, image_url, secondes, seed):
        modele = os.getenv("REPLICATE_VIDEO_MODEL", "wan-video/wan-2.2-t2v-fast")
        inp = {"prompt": prompt}
        if image_url:
            inp["image"] = image_url
        if seed is not None:
            inp["seed"] = int(seed)
        return (f"https://api.replicate.com/v1/models/{modele}/predictions",
                {"Authorization": f"Bearer {os.getenv('REPLICATE_API_TOKEN')}",
                 "Prefer": "wait"},
                {"input": inp})

    def _statut_url(self, reponse):
        return (reponse.get("urls") or {}).get("get")


class Luma(_HTTP):
    """Luma « Dream Machine » (Ray). Soumission → {id} ; on interroge la génération
    jusqu'à state=completed avec assets.video."""
    nom = "luma"

    def disponible(self):
        return bool(os.getenv("LUMAAI_API_KEY"))

    def _cle(self):
        return os.getenv("LUMAAI_API_KEY")

    def _entetes_statut(self):
        return {"Authorization": f"Bearer {self._cle()}", "accept": "application/json"}

    def _requete(self, prompt, image_url, secondes, seed):
        modele = os.getenv("LUMA_VIDEO_MODEL", "ray-2")
        body = {"prompt": prompt, "model": modele}
        if image_url:
            body["keyframes"] = {"frame0": {"type": "image", "url": image_url}}
        return ("https://api.lumalabs.ai/dream-machine/v1/generations",
                {"Authorization": f"Bearer {self._cle()}",
                 "accept": "application/json", "content-type": "application/json"}, body)

    def _statut_url(self, reponse):
        gid = reponse.get("id")
        return (f"https://api.lumalabs.ai/dream-machine/v1/generations/{gid}"
                if gid else None)


class Runway(_HTTP):
    """Runway « Gen ». Soumission → {id} ; on interroge la tâche jusqu'à SUCCEEDED avec
    output (liste d'URLs). En-tête de version requis."""
    nom = "runway"

    def disponible(self):
        return bool(os.getenv("RUNWAY_API_KEY"))

    def _cle(self):
        return os.getenv("RUNWAY_API_KEY")

    def _version(self):
        return os.getenv("RUNWAY_API_VERSION", "2024-11-06")

    def _entetes(self):
        return {"Authorization": f"Bearer {self._cle()}",
                "X-Runway-Version": self._version()}

    def _entetes_statut(self):
        return self._entetes()

    def _requete(self, prompt, image_url, secondes, seed):
        modele = os.getenv("RUNWAY_VIDEO_MODEL", "gen4_turbo")
        if image_url:
            url = "https://api.dev.runwayml.com/v1/image_to_video"
            body = {"model": modele, "promptImage": image_url, "promptText": prompt}
        else:
            url = "https://api.dev.runwayml.com/v1/text_to_video"
            body = {"model": modele, "promptText": prompt}
        if secondes:
            body["duration"] = int(secondes)
        return url, self._entetes(), body

    def _statut_url(self, reponse):
        tid = reponse.get("id")
        return f"https://api.dev.runwayml.com/v1/tasks/{tid}" if tid else None


class Gateway(_HTTP):
    """Passe par la GATEWAY Workplace (LiteLLM → OpenRouter) — déjà utilisée pour le texte
    et les images. AUCUNE clé vidéo à configurer : on réutilise la clé OpenRouter posée
    côté Gateway. Expérimental côté vidéo : on demande un modèle vidéo via /chat/completions
    et `_cherche_video` extrait ce qui revient ; si rien d'exploitable → on retombe."""
    nom = "gateway"
    timeout = int(os.getenv("VIDEO_ATTENTE_S", "300"))

    def _url(self):
        return os.getenv("GATEWAY_URL", "http://host.docker.internal:4001").rstrip("/")

    def disponible(self):
        return bool(os.getenv("GATEWAY_KEY"))

    def _requete(self, prompt, image_url, secondes, seed):
        modele = os.getenv("VIDEO_GATEWAY_MODEL", "google/veo-3-fast")
        contenu = prompt if not image_url else f"{prompt}\n\nImage de départ : {image_url}"
        body = {"model": modele, "modalities": ["video", "text"],
                "messages": [{"role": "user", "content": contenu}]}
        return (f"{self._url()}/v1/chat/completions",
                {"Authorization": f"Bearer {os.getenv('GATEWAY_KEY')}"}, body)


# ── Registre + ordre de préférence ──────────────────────────────
REGISTRE = {f.nom: f for f in (Fal(), Replicate(), Luma(), Runway(), Gateway())}

# Défaut : moteurs vidéo natifs hébergés d'abord (fal/replicate/luma/runway), puis la
# GATEWAY (expérimentale côté vidéo, mais zéro config). Surchargé par `VIDEO_PROVIDERS`.
ORDRE_DEFAUT = ["fal", "replicate", "luma", "runway", "gateway"]


def ordre() -> list:
    """Ordre de préférence effectif (filtré sur les fournisseurs connus du registre)."""
    brut = [n.strip().lower() for n in os.getenv("VIDEO_PROVIDERS", "").split(",") if n.strip()]
    noms = brut or ORDRE_DEFAUT
    return [n for n in noms if n in REGISTRE]


def disponibles() -> list:
    """Fournisseurs configurés (clé présente), dans l'ordre de préférence."""
    return [n for n in ordre() if REGISTRE[n].disponible()]
