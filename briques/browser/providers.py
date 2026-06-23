"""Assemblage des providers HuntR ACTIFS depuis l'environnement (provider-agnostique).

Le moteur (search_providers.py) sait chercher ; ce module décide QUELS moteurs sont
branchés selon la config d'env, dans un ordre de préférence. Souverain d'abord :
SearXNG auto-hébergé (conteneur voisin) puis DuckDuckGo sans-infra ; les providers à
clé (Tavily, Brave, Exa, Serper, SerpAPI, Kagi, Bing) sont INERTES tant que leur clé
n'est pas renseignée. Un provider non configuré est simplement ignoré.

Compat : les variables `RECHERCHE_*` de l'ancienne brique restent acceptées en repli.
"""
import os

from search_providers import (
    BingProvider, BraveProvider, DDGProvider, ExaProvider, KagiProvider,
    SearXNGProvider, SerpAPIProvider, SerperProvider, TavilyProvider,
)


def _env(nom: str, defaut: str = "") -> str:
    return os.getenv(f"BROWSER_{nom}", os.getenv(f"RECHERCHE_{nom}", defaut))


def _ddg():
    # Filet souverain sans-infra. Défaut actif ; BROWSER_DDG=0 pour l'éteindre.
    return DDGProvider() if _env("DDG", "1") != "0" else None


def _searxng():
    url = os.getenv("SEARXNG_URL", "http://searxng:8080")
    return SearXNGProvider(url) if url else None


def _a_cle(cls, *envs):
    """Instancie `cls(cle)` si l'une des variables d'env est renseignée, sinon None."""
    for e in envs:
        cle = os.getenv(e)
        if cle:
            return cls(cle)
    return None


# Catalogue : nom → fabrique (renvoie une instance configurée, ou None).
CATALOGUE = {
    "duckduckgo": _ddg,
    "searxng":    _searxng,
    "tavily":     lambda: _a_cle(TavilyProvider, "TAVILY_API_KEY"),
    "brave":      lambda: _a_cle(BraveProvider, "BRAVE_API_KEY"),
    "exa":        lambda: _a_cle(ExaProvider, "EXA_API_KEY"),
    "serper":     lambda: _a_cle(SerperProvider, "SERPER_API_KEY"),
    "serpapi":    lambda: _a_cle(SerpAPIProvider, "SERPAPI_API_KEY"),
    "kagi":       lambda: _a_cle(KagiProvider, "KAGI_API_KEY"),
    "bing":       lambda: _a_cle(BingProvider, "BING_API_KEY", "AZURE_BING_KEY"),
}

# Souverain d'abord, puis hébergés à clé. Surchargé par BROWSER_PROVIDERS (CSV).
ORDRE_DEFAUT = ["searxng", "duckduckgo", "tavily", "brave", "exa",
                "serper", "serpapi", "kagi", "bing"]


def ordre() -> list[str]:
    """Ordre de préférence effectif (filtré sur les providers connus)."""
    brut = [n.strip().lower() for n in _env("PROVIDERS", "").split(",") if n.strip()]
    noms = brut or ORDRE_DEFAUT
    return [n for n in noms if n in CATALOGUE]


def actifs() -> list[tuple[str, object]]:
    """Liste ``[(nom, instance)]`` des providers configurés, dans l'ordre. Pour multi_search."""
    out: list[tuple[str, object]] = []
    for n in ordre():
        try:
            inst = CATALOGUE[n]()
        except Exception:  # noqa: BLE001 — un provider mal configuré ne casse pas les autres
            inst = None
        if inst is not None:
            out.append((n, inst))
    return out


def noms_actifs() -> list[str]:
    return [n for n, _ in actifs()]
