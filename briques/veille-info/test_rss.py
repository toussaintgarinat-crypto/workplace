"""Tests du parseur RSS (regex, indépendant du parseur de Forge — réécriture, pas de
partage de code entre les deux briques, cf. design doc)."""
import httpx
import pytest

import rss

_FLUX_VALIDE = """<?xml version="1.0"?>
<rss><channel>
<item>
  <title>Premier article</title>
  <link>https://example.com/1</link>
  <pubDate>Mon, 01 Jan 2026 10:00:00 GMT</pubDate>
</item>
<item>
  <title><![CDATA[Deuxième article &amp; CDATA]]></title>
  <link>https://example.com/2</link>
</item>
</channel></rss>
"""


def test_parser_items_extrait_titre_url_date():
    items = rss.parser_items(_FLUX_VALIDE)
    assert len(items) == 2
    assert items[0]["titre"] == "Premier article"
    assert items[0]["url"] == "https://example.com/1"
    assert "2026" in items[0]["published_at"]


def test_parser_items_gere_cdata():
    items = rss.parser_items(_FLUX_VALIDE)
    assert items[1]["titre"] == "Deuxième article &amp; CDATA"


def test_parser_items_repli_sur_guid_si_pas_de_link():
    flux = """<item>
      <title>Sans link</title>
      <guid>https://example.com/guid-1</guid>
    </item>"""
    items = rss.parser_items(flux)
    assert items[0]["url"] == "https://example.com/guid-1"


def test_parser_items_ignore_item_sans_titre_ou_url():
    flux = "<item><title>Sans URL du tout</title></item>"
    assert rss.parser_items(flux) == []


def test_parser_items_flux_vide():
    assert rss.parser_items("") == []


def test_fetcher_leve_sur_erreur_http(monkeypatch):
    def _get(*a, **k):
        raise httpx.ConnectError("DNS introuvable", request=None)
    monkeypatch.setattr(rss.httpx, "get", _get)
    with pytest.raises(httpx.ConnectError):
        rss.fetcher("https://exemple-invalide.test/rss")


def test_fetcher_leve_sur_status_erreur(monkeypatch):
    class _Rep:
        status_code = 404
        text = ""
        def raise_for_status(self):
            raise httpx.HTTPStatusError("404", request=None, response=None)
    monkeypatch.setattr(rss.httpx, "get", lambda *a, **k: _Rep())
    with pytest.raises(httpx.HTTPStatusError):
        rss.fetcher("https://exemple.test/rss")


def test_fetcher_renvoie_le_texte_si_ok(monkeypatch):
    class _Rep:
        status_code = 200
        text = _FLUX_VALIDE
        def raise_for_status(self):
            pass
    monkeypatch.setattr(rss.httpx, "get", lambda *a, **k: _Rep())
    assert rss.fetcher("https://exemple.test/rss") == _FLUX_VALIDE
