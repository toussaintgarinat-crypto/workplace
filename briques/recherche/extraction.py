"""Lecture de page web — « page_lire » : une URL → texte principal + liens.

Pendant naturel de la recherche : une fois qu'on a des liens (HuntR), on veut LIRE une
page et en sortir le contenu utile (sans la pub, les menus, le pied de page) ainsi que
les liens qu'elle contient — pour que l'assistant résume EN gardant des sources cliquables.

Souverain d'abord : extraction LOCALE via Trafilatura (réputée pour isoler le contenu
éditorial). Repli HONNÊTE si Trafilatura est absent ou échoue : nettoyage HTML basique
plutôt qu'un faux texte. On ne rend JAMAIS de contenu inventé.

Garde-fous (une page web est hostile par défaut) :
  • taille bornée (`RECHERCHE_MAX_OCTETS`, défaut 3 Mo) — on tronque au-delà ;
  • temps borné (timeout httpx) ;
  • redirections suivies, mais le schéma final doit rester http/https ;
  • `robots.txt` respecté par défaut (opt-out `RECHERCHE_ROBOTS=0`) — politesse + légalité ;
  • pas de rendu JavaScript en v1 (on lit le HTML servi tel quel).

Note : les variantes `BROWSER_*` (nommage HuntR) restent acceptées en repli.
"""
import logging
import os
import re
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

_SEUIL_JS = 300  # nb chars en-dessous duquel on tente le rendu Playwright


def _env(nom: str, defaut: str) -> str:
    """Lit RECHERCHE_<nom>, repli BROWSER_<nom> (compat HuntR), puis défaut."""
    return os.getenv(f"RECHERCHE_{nom}", os.getenv(f"BROWSER_{nom}", defaut))


def max_octets() -> int:
    try:
        return int(_env("MAX_OCTETS", str(3 * 1024 * 1024)))
    except ValueError:
        return 3 * 1024 * 1024


def _ua() -> str:
    return _env("UA", "Mozilla/5.0 (compatible; WorkplaceRecherche/1.0; +http://localhost:6040)")


class ErreurLecture(Exception):
    """Échec attendu de lecture (URL invalide, robots interdit, téléchargement KO)."""


def valider_url(url: str) -> str:
    """Refuse ce qui n'est pas une URL web http/https (anti file://, data:…)."""
    p = urlparse((url or "").strip())
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ErreurLecture("URL invalide : fournir une adresse http(s):// complète.")
    return url.strip()


async def robots_autorise(url: str) -> bool:
    """`robots.txt` autorise-t-il notre UA à lire cette URL ? (tolérant : oui si doute).

    Désactivable par `RECHERCHE_ROBOTS=0`. En cas d'erreur réseau sur le robots.txt, on
    AUTORISE (un robots injoignable ne doit pas bloquer une lecture légitime)."""
    if _env("ROBOTS", "1") == "0":
        return True
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as c:
            r = await c.get(base + "/robots.txt", headers={"User-Agent": _ua()})
        if r.status_code >= 400 or not r.text.strip():
            return True
        rp = RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp.can_fetch(_ua(), url)
    except Exception:  # noqa: BLE001  — robots injoignable ⇒ on n'empêche pas la lecture
        return True


async def telecharger(url: str) -> tuple[str, str]:
    """Télécharge la page (bornée en taille/temps) → (html, url_finale après redirections).

    Lève `ErreurLecture` si le contenu n'est pas du HTML/texte ou si le téléchargement
    échoue. Tronque au-delà de `max_octets()`."""
    limite = max_octets()
    timeout = httpx.Timeout(float(_env("TIMEOUT", "25")))
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                     max_redirects=5) as c:
            async with c.stream("GET", url, headers={"User-Agent": _ua()}) as r:
                r.raise_for_status()
                ct = r.headers.get("content-type", "")
                if ct and not any(t in ct for t in ("html", "text", "xml")):
                    raise ErreurLecture(f"Type de contenu non lisible ({ct}). "
                                        "page_lire ne lit que des pages web (HTML/texte).")
                octets = bytearray()
                async for morceau in r.aiter_bytes():
                    octets.extend(morceau)
                    if len(octets) >= limite:
                        break
                url_finale = str(r.url)
        encodage = "utf-8"
        m = re.search(r"charset=([\w-]+)", ct or "")
        if m:
            encodage = m.group(1)
        return octets.decode(encodage, errors="replace"), url_finale
    except ErreurLecture:
        raise
    except httpx.HTTPStatusError as e:
        raise ErreurLecture(f"Page inaccessible (HTTP {e.response.status_code}).")
    except Exception as e:  # noqa: BLE001
        raise ErreurLecture(f"Téléchargement impossible : {str(e)[:140]}")


# ── Extraction du contenu ──────────────────────────────────────────────────────
_RE_SCRIPT = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_RE_TAGS = re.compile(r"<[^>]+>")
_RE_TITRE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_RE_LIEN = re.compile(r'<a\b[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
_RE_ESPACES = re.compile(r"\n\s*\n\s*\n+")


def _detoure(brut: str) -> str:
    import html as _h
    return _h.unescape(_RE_TAGS.sub(" ", brut or "")).strip()


def _trafilatura_dispo() -> bool:
    """Trafilatura est-il installé ? (souverain ; absent en test local → repli basique)."""
    import importlib.util
    try:
        return importlib.util.find_spec("trafilatura") is not None
    except (ImportError, ValueError):
        return False


def _playwright_dispo() -> bool:
    """Playwright est-il activé ET installé ? Opt-in via RECHERCHE_PLAYWRIGHT=1."""
    if _env("PLAYWRIGHT", "0") != "1":
        return False
    import importlib.util
    try:
        return importlib.util.find_spec("playwright") is not None
    except (ImportError, ValueError):
        return False


async def lire_page_js(url: str) -> tuple[str, str]:
    """Lit une page JS/SPA via Playwright headless Chromium → (html, url_finale)."""
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(user_agent=_ua())
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            html = await page.content()
            url_finale = page.url
        finally:
            await browser.close()
    return html, url_finale


def extraire_texte(page_html: str) -> tuple[str, str]:
    """(texte_principal, moteur) depuis un HTML — Trafilatura si présent, sinon basique.

    PURE (sans réseau) : testable hors-ligne. Le repli basique retire scripts/styles/balises
    et compacte les lignes vides ; il est honnête (il ne prétend pas isoler l'éditorial)."""
    if _trafilatura_dispo():
        try:
            import trafilatura
            texte = trafilatura.extract(page_html, include_links=False,
                                        include_comments=False, favor_recall=True)
            if texte and texte.strip():
                return texte.strip(), "trafilatura"
        except Exception:  # noqa: BLE001  — on bascule sur le repli basique
            pass
    sans_script = _RE_SCRIPT.sub(" ", page_html or "")
    texte = _RE_ESPACES.sub("\n\n", _detoure(sans_script))
    return texte.strip(), "html_basique"


def titre_page(page_html: str) -> str:
    m = _RE_TITRE.search(page_html or "")
    return _detoure(m.group(1)) if m else ""


def extraire_liens(page_html: str, url_base: str, limite: int = 50) -> list[dict]:
    """Liens ABSOLUS de la page (href résolu sur l'URL de base) → ``{texte, url}``.

    PURE. Déduplique, ignore les ancres et les schémas non-web (mailto:, javascript:…),
    pour que l'assistant garde des sources réellement cliquables."""
    sortie: list[dict] = []
    vus: set = set()
    for href, txt in _RE_LIEN.findall(page_html or ""):
        absolu = urljoin(url_base, href.strip())
        p = urlparse(absolu)
        if p.scheme not in ("http", "https") or not p.netloc or absolu in vus:
            continue
        vus.add(absolu)
        sortie.append({"texte": _detoure(txt)[:160] or absolu, "url": absolu})
        if len(sortie) >= limite:
            break
    return sortie


async def lire_page(url: str, js: bool = False) -> dict:
    """Lit une page web → ``{url, url_finale, titre, texte, tronque, nb_caracteres,
    moteur, liens}``. Lève `ErreurLecture` (URL invalide / robots interdit / réseau).

    Si `js=True` ou si le texte statique est < 300 chars ET Playwright est activé
    (RECHERCHE_PLAYWRIGHT=1), effectue un retry headless Chromium silencieux.
    """
    url = valider_url(url)
    if not await robots_autorise(url):
        raise ErreurLecture("Lecture refusée par le robots.txt du site (politesse). "
                             "Forçable côté admin via RECHERCHE_ROBOTS=0.")
    page_html, url_finale = await telecharger(url)
    texte, moteur = extraire_texte(page_html)

    # Rendu JS : explicite (`js=True`) ou détection automatique (texte trop court)
    besoin_js = js or (len(texte) < _SEUIL_JS and _playwright_dispo())
    if besoin_js and _playwright_dispo():
        try:
            page_html, url_finale = await lire_page_js(url)
            texte_js, moteur_js = extraire_texte(page_html)
            # On n'accepte le résultat JS que s'il est meilleur que le statique
            if len(texte_js) > len(texte):
                texte, moteur = texte_js, f"{moteur_js}+playwright"
        except Exception as e:
            logger.warning(f"[Playwright] retry échoué pour {url}: {e}")

    limite = max_octets()
    tronque = len(page_html.encode("utf-8", errors="ignore")) >= limite
    return {
        "url": url,
        "url_finale": url_finale,
        "titre": titre_page(page_html),
        "texte": texte,
        "nb_caracteres": len(texte),
        "tronque": tronque,
        "moteur": moteur,
        "liens": extraire_liens(page_html, url_finale or url),
    }
