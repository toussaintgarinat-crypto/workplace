"""Tests des fournisseurs de recherche — parseurs PURS + cascade (hors-ligne)."""
import fournisseurs as f


def test_parser_searxng_normalise_et_borne():
    data = {"results": [
        {"title": "Logiciel libre", "url": "https://ex.org/a", "content": "def...", "engine": "google"},
        {"title": "", "url": "https://ex.org/b", "content": "", "engine": "bing"},
        {"title": "Sans url", "url": "", "content": "ignoré"},
        {"title": "Doublon", "url": "https://ex.org/a", "content": "dup"},
    ]}
    res = f.parser_searxng(data, n=10)
    assert [r["url"] for r in res] == ["https://ex.org/a", "https://ex.org/b"]  # url vide + doublon écartés
    assert res[0] == {"titre": "Logiciel libre", "url": "https://ex.org/a",
                      "extrait": "def...", "source": "google"}
    assert res[1]["titre"] == "https://ex.org/b"   # titre vide → on retombe sur l'url


def test_parser_searxng_respecte_n():
    data = {"results": [{"title": f"t{i}", "url": f"https://ex.org/{i}"} for i in range(20)]}
    assert len(f.parser_searxng(data, n=5)) == 5


def test_parser_ddg_html_deballe_le_redirecteur():
    page = '''
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fsite.fr%2Fpage&rut=x">
       Mon <b>titre</b></a>
    <a class="result__snippet" href="x">Un extrait &amp; co</a>
    <a class="result__a" href="https://direct.fr/p">Direct</a>
    '''
    res = f.parser_ddg_html(page, n=10)
    assert res[0]["url"] == "https://site.fr/page"      # redirecteur DDG déballé
    assert res[0]["titre"] == "Mon titre"
    assert res[0]["extrait"] == "Un extrait & co"
    assert res[1]["url"] == "https://direct.fr/p"


def test_parser_tavily():
    data = {"results": [{"title": "T", "url": "https://t.io/1", "content": "c"}]}
    res = f.parser_tavily(data, n=10)
    assert res == [{"titre": "T", "url": "https://t.io/1", "extrait": "c", "source": "tavily"}]


def test_ordre_par_defaut_et_surcharge(monkeypatch):
    monkeypatch.delenv("RECHERCHE_PROVIDERS", raising=False)
    assert f.ordre() == ["searxng", "duckduckgo", "tavily"]
    monkeypatch.setenv("RECHERCHE_PROVIDERS", "tavily, inconnu ,duckduckgo")
    assert f.ordre() == ["tavily", "duckduckgo"]   # inconnu filtré


def test_disponibles_vide_en_mode_test():
    # conftest a neutralisé SearXNG (URL vide), DDG (=0), pas de clé Tavily.
    assert f.disponibles() == []


def test_searxng_disponible_suit_l_url(monkeypatch):
    monkeypatch.setenv("SEARXNG_URL", "http://searxng:8080")
    assert f.REGISTRE["searxng"].disponible() is True
    monkeypatch.setenv("SEARXNG_URL", "")
    assert f.REGISTRE["searxng"].disponible() is False


def test_tavily_disponible_si_cle(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert f.REGISTRE["tavily"].disponible() is False
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
    assert f.REGISTRE["tavily"].disponible() is True
