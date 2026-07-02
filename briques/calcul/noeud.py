"""Cycle de vie d'un nœud de calcul — logique PURE, agnostique du runtime.

Un nœud = une machine qui sert un LLM derrière un endpoint **OpenAI-compatible**
(Ollama, LM Studio, llama.cpp server, mlx_lm.server… peu importe). Cette brique ne
calcule RIEN : elle sait seulement *réveiller* le nœud (Wake-on-LAN et/ou wake-ping
mesh) et *sonder* sa disponibilité. La Gateway (LiteLLM) reste l'unique chemin de
complétion ; on ne fait que dire au Cœur « le Muscle est-il prêt ? ».

Conception pour la testabilité : tout ce qui est calculable hors-ligne (parsing de la
config, fabrication du magic packet) est une fonction pure ; les effets réseau (envoi
UDP, requête HTTP) sont isolés et injectables, pour des tests déterministes SANS réseau.

États possibles d'un nœud :
  • ``eveille``    : l'endpoint répond (HTTP < 500) — prêt à calculer ;
  • ``endormi``    : injoignable MAIS une méthode de réveil existe → probablement en veille ;
  • ``injoignable``: injoignable et AUCUN réveil possible → on n'en attend rien ;
  • ``inconnu``    : jamais sondé depuis le démarrage.

On reste HONNÊTE : on ne prétend jamais qu'un nœud est prêt sans l'avoir sondé, et un
réveil qui échoue le dit (``reveille: false``) plutôt que de faire semblant.
"""
import asyncio
import json
import os
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import httpx

# Chemins sondés par défaut sur un endpoint OpenAI-compatible. /v1/models couvre
# OpenAI/LM Studio/llama.cpp/MLX ; /api/tags couvre Ollama. Un 401/404 compte comme
# « joignable » (le serveur répond) — seul un échec réseau = injoignable.
SONDES_DEFAUT = ("/v1/models", "/api/tags")

# Méthodes de réveil reconnues (ordre = priorité d'essai déclarée par nœud).
METHODES_REVEIL = ("wol", "wakeping", "aucun")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Magic packet Wake-on-LAN (pur, sans réseau) ─────────────────────────────
def normaliser_mac(mac: str) -> str:
    """'AA:BB:CC:DD:EE:FF' / 'aa-bb-…' / 'aabbccddeeff' → 12 hex minuscules. Lève si invalide."""
    brut = "".join(c for c in (mac or "") if c not in ":-. ").lower()
    if len(brut) != 12 or any(c not in "0123456789abcdef" for c in brut):
        raise ValueError(f"Adresse MAC invalide : {mac!r}")
    return brut


def paquet_wol(mac: str) -> bytes:
    """Magic packet WoL : 6 octets 0xFF puis 16 répétitions des 6 octets de la MAC (102 o)."""
    corps = bytes.fromhex(normaliser_mac(mac))
    return b"\xff" * 6 + corps * 16


def envoyer_wol(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """Émet le magic packet en broadcast UDP. Effet de bord isolé (monkeypatchable en test)."""
    paquet = paquet_wol(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(paquet, (broadcast, port))


# ── Modèle de nœud + parc ───────────────────────────────────────────────────
@dataclass
class Noeud:
    id: str
    endpoint: str                                   # base URL OpenAI-compatible
    nom: str = ""
    mac_wol: Optional[str] = None
    broadcast_wol: str = "255.255.255.255"
    port_wol: int = 9
    methode_reveil: tuple = ("wol", "wakeping")     # ordre d'essai
    sondes: tuple = SONDES_DEFAUT
    reveil_timeout_s: int = 60
    intervalle_sonde_s: float = 2.0
    # Pool multi-muscles : priorité d'élection (plus petit = préféré) et noms de modèles.
    # ``modele`` = nom brut tel que fourni lors de l'inscription (ex. "llama3.3") ; utilisé
    # pour reconstruire la clé LiteLLM au re-push (republier). ``modele_gateway`` = nom tel
    # qu'enregistré dans LiteLLM (ex. "ollama/llama3.3") = ce que le Cœur met en cascade.
    priorite: int = 100
    modele: Optional[str] = None
    modele_gateway: Optional[str] = None
    # État courant (rafraîchi par les sondes) :
    etat: str = "inconnu"
    derniere_vue: Optional[str] = None
    derniere_erreur: Optional[str] = None

    @property
    def reveillable(self) -> bool:
        if "wakeping" in self.methode_reveil:
            return True
        return "wol" in self.methode_reveil and bool(self.mac_wol)

    def vue_publique(self) -> dict:
        return {
            "id": self.id, "nom": self.nom or self.id, "endpoint": self.endpoint,
            "etat": self.etat, "reveillable": self.reveillable,
            "priorite": self.priorite, "modele_gateway": self.modele_gateway,
            "derniere_vue": self.derniere_vue, "derniere_erreur": self.derniere_erreur,
            "methode_reveil": list(self.methode_reveil),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Noeud":
        """Construit un Noeud depuis un dict (mêmes normalisations que charger_noeuds).

        Utilisé par charger_noeuds, persistance.py et (futur) l'endpoint d'inscription API.
        Lève ValueError si le dict n'est pas valide (pas un dict, id manquant, endpoint
        manquant) — l'appelant décide de l'ignorer ou de propager.
        """
        if not isinstance(d, dict):
            raise ValueError(f"Attendu un dict, reçu {type(d).__name__!r}")
        nid = str(d.get("id") or "").strip()
        endpoint = str(d.get("endpoint") or "").strip().rstrip("/")
        if not nid or not endpoint:
            raise ValueError(f"Nœud incomplet (id={nid!r}, endpoint={endpoint!r})")
        methodes = d.get("methode_reveil")
        if isinstance(methodes, str):
            methodes = [methodes]
        methodes = tuple(m for m in (methodes or ["wol", "wakeping"]) if m in METHODES_REVEIL)
        sondes = d.get("sondes")
        if isinstance(sondes, str):
            sondes = [sondes]
        sondes = tuple(sondes) if sondes else SONDES_DEFAUT
        return cls(
            id=nid, endpoint=endpoint, nom=str(d.get("nom") or ""),
            mac_wol=(str(d["mac_wol"]).strip() if d.get("mac_wol") else None),
            broadcast_wol=str(d.get("broadcast_wol") or "255.255.255.255"),
            port_wol=int(d.get("port_wol") or 9),
            methode_reveil=methodes or ("aucun",), sondes=sondes,
            reveil_timeout_s=int(d.get("reveil_timeout_s") or 60),
            intervalle_sonde_s=float(d.get("intervalle_sonde_s") or 2.0),
            priorite=int(d.get("priorite") if d.get("priorite") is not None else 100),
            modele=(str(d["modele"]).strip() if d.get("modele") else None),
            modele_gateway=(str(d["modele_gateway"]).strip() if d.get("modele_gateway") else None),
        )

    def to_dict(self) -> dict:
        """Sérialise le nœud vers un dict JSON compatible from_dict (ronde-trip).

        Seuls les champs de CONFIGURATION sont inclus ; l'état transitoire (etat,
        derniere_vue, derniere_erreur) est volontairement omis — il sera recalculé
        par les sondes au redémarrage, ce qui garantit un verdict honnête.
        """
        return {
            "id": self.id,
            "endpoint": self.endpoint,
            "nom": self.nom,
            "mac_wol": self.mac_wol,
            "broadcast_wol": self.broadcast_wol,
            "port_wol": self.port_wol,
            "methode_reveil": list(self.methode_reveil),
            "sondes": list(self.sondes),
            "reveil_timeout_s": self.reveil_timeout_s,
            "intervalle_sonde_s": self.intervalle_sonde_s,
            "priorite": self.priorite,
            "modele": self.modele,
            "modele_gateway": self.modele_gateway,
        }


def charger_noeuds(brut: Optional[str] = None) -> dict:
    """Parse ``CALCUL_NOEUDS`` (JSON : liste d'objets) → {id: Noeud}. Vide/illisible → {}.

    Tolérant : un nœud sans ``id`` ou sans ``endpoint`` est ignoré (honnêteté : on ne
    fabrique pas un nœud bancal). Délègue le parsing de chaque entrée à Noeud.from_dict."""
    brut = os.getenv("CALCUL_NOEUDS", "") if brut is None else brut
    if not (brut or "").strip():
        return {}
    try:
        items = json.loads(brut)
    except (ValueError, TypeError):
        return {}
    if isinstance(items, dict):
        items = [items]
    parc: dict = {}
    for it in items or []:
        try:
            n = Noeud.from_dict(it)
            parc[n.id] = n
        except (ValueError, TypeError):
            continue          # nœud bancal ignoré silencieusement (honnêteté)
    return parc


# ── Sonde de disponibilité (motif `premier_joignable` des fournisseurs d'images) ──
async def sonder(noeud: Noeud, client: Optional[httpx.AsyncClient] = None,
                 timeout: float = 4.0) -> bool:
    """Le nœud répond-il ? Essaie ses chemins de sonde ; 1ʳᵉ réponse HTTP < 500 = prêt.

    Un 401/404 prouve que le serveur est vivant → prêt. Seuls un échec réseau / timeout /
    5xx comptent comme indisponibles. Met à jour l'état du nœud en conséquence."""
    propre = client is None
    client = client or httpx.AsyncClient(timeout=timeout)
    try:
        for chemin in noeud.sondes:
            url = noeud.endpoint + chemin
            try:
                r = await client.get(url)
                if r.status_code < 500:
                    noeud.etat = "eveille"
                    noeud.derniere_vue = _maintenant()
                    noeud.derniere_erreur = None
                    return True
            except httpx.HTTPError as e:
                noeud.derniere_erreur = str(e) or e.__class__.__name__
        # Aucun chemin n'a répondu : endormi (réveillable) ou franchement injoignable.
        noeud.etat = "endormi" if noeud.reveillable else "injoignable"
        return False
    finally:
        if propre:
            await client.aclose()


async def reveiller(noeud: Noeud,
                    sonde_fn: Callable[[Noeud], Awaitable[bool]] = None,
                    wol_fn: Callable[..., None] = envoyer_wol) -> dict:
    """Réveille le nœud puis attend qu'il réponde. Verdict HONNÊTE (jamais de faux positif).

    1. Si déjà prêt → on le dit (``methode: "deja"``, durée ~0).
    2. Sinon on déclenche les méthodes déclarées (WoL = magic packet ; wakeping = on
       compte sur le simple fait de re-sonder, le mesh pouvant relayer/réveiller l'hôte).
    3. On re-sonde en boucle jusqu'à ``reveil_timeout_s``. Retour : ``{reveille, methode,
       duree_s, etat}``.

    ``sonde_fn``/``wol_fn`` sont injectables pour des tests déterministes sans réseau."""
    sonde_fn = sonde_fn or sonder
    debut = time.monotonic()

    if await sonde_fn(noeud):
        return {"reveille": True, "methode": "deja",
                "duree_s": round(time.monotonic() - debut, 2), "etat": noeud.etat}

    tentees: list = []
    for m in noeud.methode_reveil:
        if m == "wol" and noeud.mac_wol:
            try:
                wol_fn(noeud.mac_wol, noeud.broadcast_wol, noeud.port_wol)
                tentees.append("wol")
            except Exception as e:                  # noqa: BLE001 — on reste honnête
                noeud.derniere_erreur = f"wol: {e}"
        elif m == "wakeping":
            tentees.append("wakeping")

    while time.monotonic() - debut < noeud.reveil_timeout_s:
        await asyncio.sleep(noeud.intervalle_sonde_s)
        if await sonde_fn(noeud):
            return {"reveille": True, "methode": "+".join(tentees) or "sonde",
                    "duree_s": round(time.monotonic() - debut, 2), "etat": noeud.etat}

    return {"reveille": False, "methode": "+".join(tentees) or "aucune",
            "duree_s": round(time.monotonic() - debut, 2), "etat": noeud.etat}


# ── Élection dans un POOL de muscles (plusieurs Mac/PC) ──────────────────────
def ordre_election(parc) -> list:
    """Nœuds triés par priorité croissante (plus petit = préféré), ordre stable sinon."""
    valeurs = parc.values() if isinstance(parc, dict) else parc
    return sorted(valeurs, key=lambda n: n.priorite)


async def elire(parc, reveiller_si_besoin: bool = False,
                sonde_fn: Callable[[Noeud], Awaitable[bool]] = None,
                reveiller_fn: Callable[[Noeud], Awaitable[dict]] = None) -> Optional[Noeud]:
    """Choisit UN muscle utilisable dans le pool. Préfère un nœud DÉJÀ éveillé (économie
    d'énergie) ; en dernier recours seulement, en réveille un.

    1. Balaye par priorité : renvoie le premier nœud qui répond (déjà éveillé).
    2. Si aucun n'est éveillé et ``reveiller_si_besoin`` : tente de réveiller les nœuds
       réveillables par priorité, renvoie le premier qui se réveille.
    3. Sinon → ``None`` (le Cœur retombe alors honnêtement sur sa cascade gratuite).

    ``sonde_fn``/``reveiller_fn`` injectables pour des tests déterministes."""
    sonde_fn = sonde_fn or sonder
    reveiller_fn = reveiller_fn or reveiller
    ordonnes = ordre_election(parc)

    for n in ordonnes:                              # 1 — un muscle déjà chaud ?
        if await sonde_fn(n):
            return n
    if not reveiller_si_besoin:
        return None
    for n in ordonnes:                              # 2 — en réveiller un, par priorité
        if n.reveillable:
            res = await reveiller_fn(n)
            if res.get("reveille"):
                return n
    return None
