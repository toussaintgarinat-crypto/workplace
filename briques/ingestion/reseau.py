"""Garde réseau de l'ingestion par URL (S211).

`/ingerer/url` télécharge une URL fournie par l'appelant **et range le corps
récupéré dans le document ingéré**, lisible ensuite via `/documents/{id}`.
Sans borne, c'est une SSRF : depuis le réseau Docker, `http://gateway:5100`,
`http://169.254.169.254/` ou `http://192.168.1.89` sont joignables, et la
validation `HttpUrl` de Pydantic les laisse toutes passer.

Trois règles :
  1. Schéma `http`/`https` uniquement (ni `file://`, ni `gopher://`…).
  2. **Toutes** les adresses derrière le nom d'hôte doivent être publiques —
     pas une seule, toutes : un nom qui résout en `1.2.3.4` *et* `127.0.0.1`
     est refusé.
  3. La règle 2 est réappliquée **après chaque redirection**. Une 302 vers
     `127.0.0.1` est le contournement classique, donc on suit les redirections
     à la main (`follow_redirects=False`) au lieu de laisser httpx le faire.

Limite assumée : entre notre résolution DNS et celle de httpx, un serveur DNS
hostile peut changer sa réponse (« DNS rebinding »). Fermer ce trou demande de
se connecter à l'IP vérifiée en forçant l'en-tête `Host` — impossible en HTTPS
sans casser la vérification du certificat. On borne donc le risque plutôt que
de le nier : le cas réaliste (URL interne, redirection vers la loopback) est
couvert, le rebinding actif ne l'est pas.
"""

import asyncio
import ipaddress
import logging
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

# Aligné sur le plafond de l'upload (`main.py::ingerer_fichier`).
TAILLE_MAX = 50 * 1024 * 1024
MAX_REDIRECTIONS = 5
TIMEOUT = 30


class UrlInterdite(ValueError):
    """L'URL vise une cible non publique (ou un schéma non autorisé)."""


class ContenuTropGros(ValueError):
    """La réponse dépasse le plafond de taille."""


def _est_publique(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Une adresse est publique si elle n'est dans aucune plage « interne ».

    `is_private` couvre déjà 10/8, 172.16/12, 192.168/16, 127/8, ::1 et fe80::/10,
    mais on énumère quand même le reste : multicast, réservé, non spécifiée
    (0.0.0.0 → « moi-même » sur beaucoup de piles réseau).
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        # ::ffff:127.0.0.1 doit être jugé sur son adresse IPv4 sous-jacente.
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def _resoudre(hote: str, port: int) -> list[str]:
    """Toutes les adresses derrière un nom d'hôte (A + AAAA), sans bloquer la boucle."""
    infos = await asyncio.get_running_loop().getaddrinfo(hote, port)
    return [info[4][0] for info in infos]


async def verifier_url(url: str) -> None:
    """Lève `UrlInterdite` si l'URL ne vise pas une cible publique."""
    morceaux = urlsplit(url)
    if morceaux.scheme not in ("http", "https"):
        raise UrlInterdite(f"schéma non autorisé : {morceaux.scheme or '(aucun)'}")

    hote = morceaux.hostname
    if not hote:
        raise UrlInterdite("URL sans nom d'hôte")

    port = morceaux.port or (443 if morceaux.scheme == "https" else 80)
    try:
        adresses = await _resoudre(hote, port)
    except OSError as e:
        raise UrlInterdite(f"nom d'hôte irrésolvable : {hote} ({e})") from e

    for adresse in adresses:
        ip = ipaddress.ip_address(adresse)
        if not _est_publique(ip):
            raise UrlInterdite(
                f"adresse non publique refusée : {hote} → {adresse} "
                "(réseau interne, loopback ou lien-local)"
            )


async def telecharger(url: str, taille_max: int | None = None) -> tuple[bytes, str, str]:
    """Télécharge une URL publique, redirections vérifiées une par une.

    Retourne `(contenu, url_finale, type_mime)`. Lève `UrlInterdite` (cible
    interdite ou boucle de redirections) ou `ContenuTropGros` (plafond dépassé,
    mesuré **en streaming** pour ne pas charger avant de compter).

    `taille_max=None` → `TAILLE_MAX` lu à l'appel, pas figé à la définition : le
    plafond reste ainsi réglable (tests, futur env).
    """
    taille_max = TAILLE_MAX if taille_max is None else taille_max
    async with httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT) as client:
        for _ in range(MAX_REDIRECTIONS + 1):
            await verifier_url(url)
            async with client.stream("GET", url) as reponse:
                if reponse.is_redirect:
                    cible = reponse.headers.get("location")
                    if not cible:
                        raise UrlInterdite("redirection sans en-tête Location")
                    url = str(httpx.URL(url).join(cible))
                    logger.info("Redirection suivie vers %s (re-vérifiée)", url)
                    continue

                reponse.raise_for_status()

                declaree = reponse.headers.get("content-length")
                if declaree and declaree.isdigit() and int(declaree) > taille_max:
                    raise ContenuTropGros(
                        f"réponse annoncée à {int(declaree)} octets (max {taille_max})"
                    )

                contenu = bytearray()
                async for morceau in reponse.aiter_bytes():
                    contenu += morceau
                    if len(contenu) > taille_max:
                        raise ContenuTropGros(
                            f"réponse dépassant {taille_max} octets (arrêtée en cours)"
                        )

                type_mime = reponse.headers.get("content-type", "").split(";")[0].strip()
                return bytes(contenu), url, type_mime

    raise UrlInterdite(f"plus de {MAX_REDIRECTIONS} redirections — abandon")
