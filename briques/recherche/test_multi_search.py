"""Orchestrateur HuntR : parallèle + dédup par URL canonique + scoring consensus."""
import pytest

from search_providers import SearchResult, multi_search, _normalize_url


class FauxProvider:
    """Provider de test : renvoie une liste fixe de SearchResult (sans réseau)."""
    def __init__(self, source, urls):
        self.source = source
        self.urls = urls

    async def search(self, query, max_results=10, topic="web", langue="fr"):
        return [SearchResult(title=f"{self.source} {u}", url=u, snippet="", content="",
                             source=self.source) for u in self.urls]


def test_normalize_url_canonise():
    assert _normalize_url("https://WWW.Example.com/a/?q=1#frag") == "https://example.com/a"
    assert _normalize_url("http://example.com/a/") == "http://example.com/a"


@pytest.mark.anyio
async def test_dedup_par_url_canonique():
    p1 = FauxProvider("duckduckgo", ["https://example.com/a", "https://example.com/b"])
    p2 = FauxProvider("tavily", ["https://www.example.com/a/"])   # même URL canonique que /a
    out = await multi_search([("duckduckgo", p1), ("tavily", p2)], "q")
    urls = sorted(_normalize_url(r.url) for r in out)
    assert urls == ["https://example.com/a", "https://example.com/b"]   # /a fusionné


@pytest.mark.anyio
async def test_consensus_remonte_les_urls_partagees():
    # /commun trouvé par 2 moteurs → doit passer devant /seul trouvé par 1.
    p1 = FauxProvider("duckduckgo", ["https://x.test/seul", "https://x.test/commun"])
    p2 = FauxProvider("brave", ["https://x.test/commun"])
    out = await multi_search([("duckduckgo", p1), ("brave", p2)], "q")
    assert _normalize_url(out[0].url) == "https://x.test/commun"


@pytest.mark.anyio
async def test_provider_qui_plante_nempeche_pas_les_autres():
    class Casse:
        source = "casse"
        async def search(self, *a, **k):
            raise RuntimeError("boom")
    ok = FauxProvider("duckduckgo", ["https://ok.test/a"])
    out = await multi_search([("casse", Casse()), ("duckduckgo", ok)], "q")
    assert [r.url for r in out] == ["https://ok.test/a"]


@pytest.mark.anyio
async def test_sans_provider_rend_vide():
    assert await multi_search([], "q") == []


@pytest.fixture
def anyio_backend():
    return "asyncio"
