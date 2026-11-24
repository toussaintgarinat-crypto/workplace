"""Briques qui dorment (S243) — réveil à la demande, endormissement, garde-fous.

Une brique peu utilisée n'a pas besoin de tourner 24 h/24 : on l'éteint après un délai
d'inactivité et on la rallume à la première demande (l'assistant, un outil, ou l'utilisateur).

Principes :
  • OPT-IN par brique : seule une brique dont le manifeste déclare un bloc `sommeil` peut être
    endormie. Ex. `"sommeil": {"conteneurs": ["workplace_geo"], "inactivite_min": 30,
    "attente_s": 60}`. Aucune déclaration → jamais touchée.
  • LISTE NOIRE EN DUR (`NON_ENDORMISSABLES`) : le Cœur, la Gateway, Keycloak, la mémoire,
    l'agenda… ne dorment jamais, même si un manifeste le demandait. Sinon l'assistant pourrait
    couper la branche sur laquelle il est assis.
  • Docker n'est atteint que par un « backend » injectable : le socket Docker (comme le reste
    du Cœur) ou, si `SOMMEIL_DOCKER_URL` est posée, un proxy qui ne laisse passer que
    inspect/start/stop. Les tests injectent un faux backend : aucun conteneur réel touché.
  • HONNÊTETÉ : l'état « endormie » n'est affirmé que si le conteneur EXISTE et est arrêté.
    Un conteneur introuvable ou une API Docker muette donne « inconnue », jamais « endormie »
    (sinon une brique en panne passerait pour « endormie volontairement »).
  • INERTE PAR DÉFAUT : `SOMMEIL_ACTIF=1` est requis pour que le balayage d'inactivité éteigne
    quoi que ce soit. Réveiller et lire l'état marchent toujours.
"""
import asyncio
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

ACTIF = os.getenv("SOMMEIL_ACTIF", "0").lower() in ("1", "true", "yes", "on")
DOCKER_SOCK = os.getenv("DOCKER_SOCK", "/var/run/docker.sock")
DOCKER_URL = os.getenv("SOMMEIL_DOCKER_URL", "").rstrip("/")

INACTIVITE_DEFAUT_MIN = 30
ATTENTE_DEFAUT_S = 60.0
PAS_ATTENTE_S = 1.0  # intervalle de sondage pendant un réveil (0 dans les tests)

# Jamais endormies, quoi que dise un manifeste (le Cœur, l'identité, la mémoire, l'agenda,
# la passerelle LLM, le proxy Docker lui-même).
NON_ENDORMISSABLES = frozenset({
    "core", "gateway", "gateway-sync", "keycloak", "memoire", "agenda", "sommeil-proxy",
})

_ACTIVITE: dict[str, float] = {}      # brique → dernier appel (horloge monotone-ish : time.time())
_VERROUS: dict[str, asyncio.Lock] = {}
_backend = None


# ── Backend Docker (injectable) ──────────────────────────────────────────────

class DockerAPI:
    """Parle à l'API Docker : inspect, start, stop. Rien d'autre (surface minimale)."""

    def _client(self) -> httpx.AsyncClient:
        if DOCKER_URL:
            return httpx.AsyncClient(base_url=DOCKER_URL, timeout=60)
        transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCK)
        return httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=60)

    async def inspecter(self, nom: str) -> dict | None:
        """{"running": bool, "sante": "healthy"|"starting"|"unhealthy"|None} ou None si le
        conteneur n'existe pas. Lève en cas d'API muette (l'appelant traduit en « inconnue »)."""
        async with self._client() as c:
            r = await c.get(f"/containers/{nom}/json")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        etat = r.json().get("State") or {}
        return {"running": bool(etat.get("Running")),
                "sante": (etat.get("Health") or {}).get("Status")}

    async def demarrer(self, nom: str) -> None:
        async with self._client() as c:
            r = await c.post(f"/containers/{nom}/start")
        if r.status_code not in (204, 304):
            r.raise_for_status()

    async def arreter(self, nom: str) -> None:
        async with self._client() as c:
            r = await c.post(f"/containers/{nom}/stop", params={"t": 20})
        if r.status_code not in (204, 304):
            r.raise_for_status()


def definir_backend(backend) -> None:
    """Injecte un backend (tests) ; None = revient au backend Docker réel."""
    global _backend
    _backend = backend


def _docker():
    global _backend
    if _backend is None:
        _backend = DockerAPI()
    return _backend


# ── Configuration d'une brique ───────────────────────────────────────────────

def config(registre, nom: str) -> dict | None:
    """Bloc `sommeil` normalisé d'une brique, ou None si elle ne peut pas dormir
    (pas d'option, bloc mal formé, ou brique protégée en dur)."""
    if nom in NON_ENDORMISSABLES:
        return None
    brut = ((registre.briques.get(nom) or {}).get("sommeil"))
    if not isinstance(brut, dict):
        return None
    conteneurs = brut.get("conteneurs")
    if (not isinstance(conteneurs, list) or not conteneurs
            or not all(isinstance(c, str) and c for c in conteneurs)):
        logger.warning("sommeil ignoré pour %s : « conteneurs » doit être une liste non vide.", nom)
        return None

    def _nombre(cle, defaut, minimum):
        try:
            v = float(brut.get(cle, defaut))
        except (TypeError, ValueError):
            return defaut
        return v if v >= minimum else defaut

    return {"conteneurs": list(conteneurs),
            "inactivite_min": _nombre("inactivite_min", INACTIVITE_DEFAUT_MIN, 1),
            "attente_s": _nombre("attente_s", ATTENTE_DEFAUT_S, 1)}


def briques_endormissables(registre) -> list[str]:
    return [n for n in registre.briques if config(registre, n)]


# ── État ─────────────────────────────────────────────────────────────────────

async def _etats_conteneurs(cfg: dict) -> list[dict | None]:
    return [await _docker().inspecter(c) for c in cfg["conteneurs"]]


async def etat(registre, nom: str) -> str:
    """« eveillee » | « demarrage » | « endormie » | « inconnue »."""
    cfg = config(registre, nom)
    if not cfg:
        return "inconnue"
    try:
        etats = await _etats_conteneurs(cfg)
    except Exception as e:  # noqa: BLE001 — API Docker muette : on ne devine pas
        logger.warning("état sommeil de %s illisible : %s", nom, e)
        return "inconnue"
    if any(e is None for e in etats):
        return "inconnue"
    if any(not e["running"] for e in etats):
        return "endormie"
    if any(e["sante"] in ("starting", "unhealthy") for e in etats):
        return "demarrage"
    return "eveillee"


# ── Réveil / endormissement ──────────────────────────────────────────────────

def _verrou(nom: str) -> asyncio.Lock:
    return _VERROUS.setdefault(nom, asyncio.Lock())


def noter_activite(nom: str, maintenant: float | None = None) -> None:
    _ACTIVITE[nom] = time.time() if maintenant is None else maintenant


async def reveiller(registre, nom: str, attente_s: float | None = None) -> dict:
    cfg = config(registre, nom)
    if not cfg:
        return {"ok": False, "brique": nom,
                "message": f"« {nom} » n'a pas d'option sommeil (ou ne peut pas dormir) : rien à réveiller."}
    delai = cfg["attente_s"] if attente_s is None else attente_s
    async with _verrou(nom):
        try:
            etats = await _etats_conteneurs(cfg)
            for conteneur, e in zip(cfg["conteneurs"], etats):
                if e is not None and not e["running"]:
                    await _docker().demarrer(conteneur)
            fin = time.monotonic() + delai
            while True:
                s = await etat(registre, nom)
                if s == "eveillee":
                    noter_activite(nom)
                    return {"ok": True, "brique": nom, "etat": "eveillee",
                            "message": f"« {nom} » est réveillée."}
                if time.monotonic() >= fin:
                    return {"ok": False, "brique": nom, "etat": s,
                            "message": f"Délai dépassé : « {nom} » n'est pas prête après {delai:g} s (état : {s})."}
                await asyncio.sleep(PAS_ATTENTE_S)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "brique": nom, "message": f"Réveil de « {nom} » impossible : {e}"}


async def endormir(registre, nom: str) -> dict:
    cfg = config(registre, nom)
    if not cfg:
        return {"ok": False, "brique": nom,
                "message": f"« {nom} » ne peut pas être endormie (protégée ou sans option sommeil)."}
    async with _verrou(nom):
        try:
            for conteneur in cfg["conteneurs"]:
                await _docker().arreter(conteneur)
            _ACTIVITE.pop(nom, None)
            return {"ok": True, "brique": nom, "etat": "endormie",
                    "message": f"« {nom} » est endormie ; elle se réveillera à la prochaine demande."}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "brique": nom, "message": f"Endormissement de « {nom} » impossible : {e}"}


async def assurer_eveillee(registre, nom: str, attente_s: float | None = None) -> str | None:
    """Avant un appel d'outil vers `nom` : réveille la brique si elle dort, et note l'usage.

    Renvoie None si tout va bien (ou si la brique n'est pas concernée), sinon un message
    d'erreur lisible à renvoyer au LLM à la place de l'appel."""
    if not config(registre, nom):
        return None
    if await etat(registre, nom) == "endormie":
        res = await reveiller(registre, nom, attente_s=attente_s)
        if not res["ok"]:
            return f"« {nom} » dormait et n'a pas pu être réveillée : {res['message']}"
    noter_activite(nom)
    return None


async def balayer(registre, maintenant: float | None = None) -> list[str]:
    """Endort les briques éveillées sans activité depuis plus que leur seuil. Renvoie les
    briques endormies. Inerte si `SOMMEIL_ACTIF` n'est pas posé."""
    if not ACTIF:
        return []
    t = time.time() if maintenant is None else maintenant
    dormies = []
    for nom in briques_endormissables(registre):
        cfg = config(registre, nom)
        if await etat(registre, nom) != "eveillee":
            continue
        derniere = _ACTIVITE.get(nom)
        if derniere is None:
            # Activité inconnue (Cœur redémarré) : le délai repart de zéro, on n'éteint pas
            # tout d'un coup.
            _ACTIVITE[nom] = t
            continue
        if t - derniere >= cfg["inactivite_min"] * 60:
            res = await endormir(registre, nom)
            if res["ok"]:
                dormies.append(nom)
                logger.info("sommeil : « %s » endormie après %.0f min d'inactivité.",
                            nom, (t - derniere) / 60)
    return dormies
