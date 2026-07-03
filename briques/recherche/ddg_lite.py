"""Client DuckDuckGo SOUVERAIN, zéro clé — filet de la brique `recherche`.

Remplace la dépendance Gungnir `backend.core.agents.tools.web_fetch.web_search_lite`
par une implémentation autonome : on lit la page HTML « lite » de DuckDuckGo
(`https://html.duckduckgo.com/html/`) et on en extrait les liens. Pas d'API officielle
→ fragile par construction (le balisage peut changer), d'où son rôle de simple repli
gratuit derrière les providers à clé (Tavily, Brave, Serper…). Honnête : si le HTML ne
livre rien, on rend une liste vide plutôt que d'inventer.

Contrat (calqué sur web_fetch.web_search_lite, pour `search_providers.DDGProvider`) :

    await web_search_lite(query, num_results=10) -> {"ok": bool, "results": [...], "error"?: str}

    results = [{"title": str, "url": str, "snippet": str}, …]
"""
import html
import os
import re
from urllib.parse import parse_qs, urlparse

import httpx

_URL = "https://html.duckduckgo.com/html/"
_TIMEOUT = 20


def _kl_for(lang: str) -> str:
    """Convertit un code langue (fr, en…) en locale DDG (kl=fr-fr, en-us…)."""
    l = (lang or "fr").lower().strip()
    country = {"en": "us", "zh": "cn", "ja": "jp", "ko": "kr"}.get(l, l)
    return f"{l}-{country}"


def _ua() -> str:
    return os.getenv(
        "RECHERCHE_UA",
        os.getenv("BROWSER_UA",
                  "Mozilla/5.0 (compatible; WorkplaceRecherche/1.0; +http://localhost:6040)"),
    )


_RE_DDG_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<titre>.*?)</a>'
    r'(?P<reste>.*?)(?=<a[^>]+class="result__a"|</body>|\Z)',
    re.DOTALL | re.IGNORECASE)
_RE_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(?P<txt>.*?)</a>',
                         re.DOTALL | re.IGNORECASE)
_RE_TAGS = re.compile(r"<[^>]+>")


def _texte(brut: str) -> str:
    return html.unescape(_RE_TAGS.sub("", brut or "")).strip()


def _deballer(href: str) -> str:
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
    """Normalise la page HTML de DuckDuckGo → ``[{title, url, snippet}]`` (PURE, testable)."""
    sortie: list[dict] = []
    vus: set = set()
    for m in _RE_DDG_RESULT.finditer(page or ""):
        url = _deballer(m.group("href"))
        if not url or not url.startswith("http") or url in vus:
            continue
        vus.add(url)
        snip = _RE_SNIPPET.search(m.group("reste") or "")
        sortie.append({
            "title": _texte(m.group("titre")) or url,
            "url": url,
            "snippet": _texte(snip.group("txt")) if snip else "",
        })
        if len(sortie) >= n:
            break
    return sortie


async def web_search_lite(query: str, num_results: int = 10, langue: str = "fr") -> dict:
    """Cherche sur DuckDuckGo (HTML lite) → ``{"ok", "results"[, "error"]}``."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as c:
            r = await c.post(_URL, data={"q": query, "kl": _kl_for(langue)},
                             headers={"User-Agent": _ua()})
            r.raise_for_status()
        return {"ok": True, "results": parser_ddg_html(r.text, num_results)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "results": [], "error": str(e)[:160]}
