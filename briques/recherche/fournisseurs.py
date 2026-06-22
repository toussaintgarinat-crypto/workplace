"""Fournisseurs de recherche web — registre PROVIDER-AGNOSTIQUE.

Une même requête (« comment installer Postgres ? ») peut être servie par plusieurs
moteurs de recherche, essayés dans un ORDRE de préférence configurable
(`RECHERCHE_PROVIDERS`). Chaque fournisseur expose la même interface minimale, calquée
sur `briques/vision/fournisseurs.py` :

    nom            : identifiant court (clé du registre, valeur de `source`) ;
    disponible()   : la config est-elle là (URL/clé) ? — sync, SANS réseau ;
    async rechercher(requete, n, langue) -> list[dict]   # résultats, sinon LÈVE.

Un résultat normalisé = ``{"titre", "url", "extrait", "source"}`` : un lien CLIQUABLE,
son titre et un court extrait. Le moteur (main.py) balaie les fournisseurs DISPONIBLES
dans l'ordre et retient les PREMIERS résultats non vides ; si aucun ne répond, il rend
une réponse VIDE qui le DIT (jamais de faux liens, jamais d'URL inventée).

Cascade livrée (souverain d'abord, puis hébergés à clé) :
  • searxng    — métamoteur SearXNG auto-hébergé (conteneur voisin). Souverain, 0 clé,
    agrège Google/Bing/DDG/Wikipédia… et rend du JSON propre. C'est le défaut.
  • duckduckgo — repli ZÉRO-INFRA : scraping de la page HTML « lite » de DuckDuckGo.
    Fragile par nature (pas d'API officielle, le HTML peut changer), mais ne demande
    NI conteneur NI clé. Filet de sécurité honnête si SearXNG est éteint.
  • tavily     — API Tavily (à clé), pensée pour les agents (résultats déjà nettoyés).
    Inerte sans `TAVILY_API_KEY`. Montre l'extension « clé payante par tenant » prévue
    pour plus tard (Brave, Serper… suivront le même contrat).

Aucune clé n'est embarquée : chaque fournisseur se configure par variables d'env. Un
fournisseur non configuré est simplement IGNORÉ — on retombe sur le suivant, puis sur
une réponse vide honnête.
"""
import html
import os
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx


def _n_defaut() -> int:
    """Nombre de résultats par défaut (borné)."""
    try:
        return max(1, min(50, int(os.getenv("RECHERCHE_N_DEFAUT", "8"))))
    except ValueError:
        return 8


# ── Métamoteur SOUVERAIN auto-hébergé ──────────────────────────────────────────
class SearXNG:
    """SearXNG — métamoteur auto-hébergé (conteneur voisin), format JSON.

    On interroge `GET {SEARXNG_URL}/search?q=…&format=json` ; la réponse contient
    `results: [{title, url, content, engine}, …]`. Souverain : aucune clé, aucune
    donnée envoyée à un tiers au-delà des moteurs agrégés par SearXNG lui-même."""
    nom = "searxng"
    timeout = 20

    def base(self) -> str:
        return os.getenv("SEARXNG_URL", "http://searxng:8080").rstrip("/")

    def disponible(self) -> bool:
        # Une URL est toujours là (défaut interne). On considère le moteur « disponible »
        # dès qu'une URL est configurée ; son indisponibilité réseau est gérée au runtime
        # (le moteur lève → la cascade replie sur DuckDuckGo).
        return bool(self.base())

    async def rechercher(self, requete: str, n: int, langue: str = "fr") -> list[dict]:
        params = {
            "q": requete,
            "format": "json",
            "language": langue or "fr",
            "safesearch": os.getenv("RECHERCHE_SAFESEARCH", "1"),
        }
        cats = os.getenv("SEARXNG_CATEGORIES", "general")
        if cats:
            params["categories"] = cats
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.get(self.base() + "/search", params=params,
                            headers={"Accept": "application/json"})
            r.raise_for_status()
            return parser_searxng(r.json(), n)


def parser_searxng(data: dict, n: int) -> list[dict]:
    """Normalise la réponse JSON de SearXNG → liste ``{titre, url, extrait, source}``.

    Fonction PURE (sans réseau) : c'est elle qu'on teste hors-ligne. On déduplique par
    URL et on ignore les entrées sans URL exploitable (jamais de lien creux)."""
    sortie: list[dict] = []
    vus: set = set()
    for item in (data or {}).get("results", []) or []:
        url = (item.get("url") or "").strip()
        titre = (item.get("title") or "").strip()
        if not url or url in vus:
            continue
        vus.add(url)
        sortie.append({
            "titre": titre or url,
            "url": url,
            "extrait": (item.get("content") or "").strip(),
            "source": item.get("engine") or "searxng",
        })
        if len(sortie) >= n:
            break
    return sortie


# ── Repli ZÉRO-INFRA : page HTML « lite » de DuckDuckGo ─────────────────────────
class DuckDuckGo:
    """Repli sans conteneur ni clé : scraping de `https://html.duckduckgo.com/html/`.

    DuckDuckGo n'a pas d'API de recherche officielle ; on lit la page de résultats HTML
    et on en extrait les liens. C'est FRAGILE par construction (le balisage peut changer
    sans préavis) — d'où le rang de simple repli. Honnête : si le HTML ne livre rien, on
    rend une liste vide plutôt que d'inventer."""
    nom = "duckduckgo"
    timeout = 20
    URL = "https://html.duckduckgo.com/html/"

    def disponible(self) -> bool:
        # Activé seulement si on l'autorise explicitement (réseau sortant vers DDG).
        # Défaut: actif (c'est le filet). Mettre RECHERCHE_DDG=0 pour l'éteindre.
        return os.getenv("RECHERCHE_DDG", "1") != "0"

    async def rechercher(self, requete: str, n: int, langue: str = "fr") -> list[dict]:
        headers = {"User-Agent": os.getenv(
            "RECHERCHE_UA",
            "Mozilla/5.0 (compatible; WorkplaceRecherche/0.1; +http://localhost:6040)")}
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as c:
            r = await c.post(self.URL, data={"q": requete, "kl": (langue or "fr") + "-fr"},
                             headers=headers)
            r.raise_for_status()
            return parser_ddg_html(r.text, n)


_RE_DDG_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<titre>.*?)</a>'
    r'(?P<reste>.*?)(?=<a[^>]+class="result__a"|</body>|\Z)',
    re.DOTALL | re.IGNORECASE)
_RE_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(?P<txt>.*?)</a>',
                         re.DOTALL | re.IGNORECASE)
_RE_TAGS = re.compile(r"<[^>]+>")


def _texte(brut: str) -> str:
    return html.unescape(_RE_TAGS.sub("", brut or "")).strip()


def _url_ddg(href: str) -> str:
    """DDG enrobe les liens dans un redirecteur `/l/?uddg=<url encodée>` : on déballe."""
    href = html.unescape(href or "")
    if href.startswith("//"):
        href = "https:" + href
    p = urlparse(href)
    if "duckduckgo.com" in (p.netloc or "") and p.path.startswith("/l/"):
        cible = parse_qs(p.query).get("uddg", [])
        if cible:
            return cible[0]
    return href


def parser_ddg_html(page: str, n: int) -> list[dict]:
    """Normalise la page HTML de DuckDuckGo → ``{titre, url, extrait, source}`` (PURE)."""
    sortie: list[dict] = []
    vus: set = set()
    for m in _RE_DDG_RESULT.finditer(page or ""):
        url = _url_ddg(m.group("href"))
        if not url or not url.startswith("http") or url in vus:
            continue
        vus.add(url)
        snip = _RE_SNIPPET.search(m.group("reste") or "")
        sortie.append({
            "titre": _texte(m.group("titre")) or url,
            "url": url,
            "extrait": _texte(snip.group("txt")) if snip else "",
            "source": "duckduckgo",
        })
        if len(sortie) >= n:
            break
    return sortie


# ── Hébergé à clé (extension multi-tenant prévue) ──────────────────────────────
class Tavily:
    """Tavily Search API (`POST /search`) — résultats pensés pour les agents.

    À clé (`TAVILY_API_KEY`), donc INERTE par défaut. Présent pour matérialiser le
    contrat « fournisseur payant par tenant » : Brave Search, Serper, etc. se brancheront
    de la même façon (une classe, une clé d'env, le même format de sortie)."""
    nom = "tavily"
    timeout = 30
    URL = "https://api.tavily.com/search"

    def disponible(self) -> bool:
        return bool(os.getenv("TAVILY_API_KEY"))

    async def rechercher(self, requete: str, n: int, langue: str = "fr") -> list[dict]:
        body = {"api_key": os.getenv("TAVILY_API_KEY"), "query": requete,
                "max_results": n, "search_depth": "basic"}
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(self.URL, json=body)
            r.raise_for_status()
            return parser_tavily(r.json(), n)


def parser_tavily(data: dict, n: int) -> list[dict]:
    """Normalise la réponse Tavily → ``{titre, url, extrait, source}`` (PURE)."""
    sortie: list[dict] = []
    vus: set = set()
    for item in (data or {}).get("results", []) or []:
        url = (item.get("url") or "").strip()
        if not url or url in vus:
            continue
        vus.add(url)
        sortie.append({
            "titre": (item.get("title") or url).strip(),
            "url": url,
            "extrait": (item.get("content") or "").strip(),
            "source": "tavily",
        })
        if len(sortie) >= n:
            break
    return sortie


# ── Registre + ordre de préférence ─────────────────────────────────────────────
REGISTRE = {f.nom: f for f in (SearXNG(), DuckDuckGo(), Tavily())}

# Défaut : SearXNG souverain d'abord, puis DDG sans-infra, puis Tavily à clé.
# Surchargé par `RECHERCHE_PROVIDERS` (liste, ex. "tavily" ou "duckduckgo,searxng").
ORDRE_DEFAUT = ["searxng", "duckduckgo", "tavily"]


def ordre() -> list:
    """Ordre de préférence effectif (filtré sur les fournisseurs connus du registre)."""
    brut = [n.strip().lower() for n in os.getenv("RECHERCHE_PROVIDERS", "").split(",")
            if n.strip()]
    noms = brut or ORDRE_DEFAUT
    return [n for n in noms if n in REGISTRE]


def disponibles() -> list:
    """Fournisseurs configurés (URL/clé présente), dans l'ordre de préférence."""
    return [n for n in ordre() if REGISTRE[n].disponible()]
