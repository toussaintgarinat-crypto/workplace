"""Fetch + parsing RSS pour la brique veille-info. Réécriture indépendante du parseur déjà
éprouvé dans `briques/forge/forge/core/app/routers/veille.py` — PAS importée depuis Forge
(décision : les deux briques restent indépendantes, cf. design doc)."""
from __future__ import annotations

import re

import httpx

_ITEM_RE = re.compile(r"<item[^>]*>([\s\S]*?)</item>", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", re.IGNORECASE | re.DOTALL)
_LINK_RE = re.compile(r"<link[^>]*>(.*?)</link>", re.IGNORECASE | re.DOTALL)
_GUID_RE = re.compile(r"<guid[^>]*>(https?://[^<]+)</guid>", re.IGNORECASE)
_PUBDATE_RE = re.compile(r"<pubDate[^>]*>(.*?)</pubDate>", re.IGNORECASE | re.DOTALL)


def parser_items(texte: str) -> list[dict]:
    """Parse les <item> d'un flux RSS → [{titre, url, published_at}]."""
    items: list[dict] = []
    for m in _ITEM_RE.finditer(texte):
        item = m.group(1)
        title_m = _TITLE_RE.search(item)
        titre = (title_m.group(1).strip() if title_m else "")
        link_m = _LINK_RE.search(item)
        url = link_m.group(1).strip() if link_m and link_m.group(1).strip() else ""
        if not url:
            guid_m = _GUID_RE.search(item)
            url = guid_m.group(1).strip() if guid_m else ""
        pub_m = _PUBDATE_RE.search(item)
        published_at = pub_m.group(1).strip() if pub_m else ""
        if titre and url:
            items.append({"titre": titre, "url": url, "published_at": published_at})
    return items


def fetcher(url: str) -> str:
    """Récupère le contenu brut d'un flux RSS. Lève en cas d'échec réseau/HTTP — à
    l'appelant de journaliser et continuer avec les autres sources."""
    r = httpx.get(url, timeout=10.0, headers={"User-Agent": "VeilleInfo/1.0 RSS Reader"},
                  follow_redirects=True)
    r.raise_for_status()
    return r.text
