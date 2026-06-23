"""ddg_lite : le parser HTML de DuckDuckGo est PUR et honnête (testable hors-ligne)."""
import ddg_lite


PAGE = """
<html><body>
  <a class="result__a" href="https://html.duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">
     Titre &amp; A</a>
  <span class="result__snippet">Extrait <b>A</b></span></a>
  <a class="result__a" href="https://example.org/b">Titre B</a>
  <span class="result__snippet">Extrait B</span></a>
  <a class="result__a" href="https://example.org/b">Titre B (doublon)</a>
</body></html>
"""


def test_parser_deballe_le_redirecteur_et_decode_entites():
    res = ddg_lite.parser_ddg_html(PAGE, 10)
    assert res[0]["url"] == "https://example.com/a"      # /l/?uddg= déballé
    assert res[0]["title"] == "Titre & A"                # entité décodée
    assert "Extrait" in res[0]["snippet"]


def test_parser_deduplique_par_url():
    res = ddg_lite.parser_ddg_html(PAGE, 10)
    urls = [r["url"] for r in res]
    assert urls == ["https://example.com/a", "https://example.org/b"]


def test_parser_respecte_la_limite_n():
    assert len(ddg_lite.parser_ddg_html(PAGE, 1)) == 1


def test_parser_vide_ne_plante_pas():
    assert ddg_lite.parser_ddg_html("", 5) == []
    assert ddg_lite.parser_ddg_html("<html></html>", 5) == []
