"""S241 — onglet Recherche : présent, appelle /recherche, rend SANS innerHTML.

$ cd core && python3 -m pytest test_recherche_dashboard.py -v
"""
import re
from pathlib import Path

SOURCE = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


def _fonction(nom: str) -> str:
    debut = SOURCE.index(f"async function {nom}(")
    fin = SOURCE.index("\n}\n", debut)
    return SOURCE[debut:fin]


def test_onglet_et_vue_presents():
    assert 'data-vue="recherche"' in SOURCE
    assert 'id="vue-recherche"' in SOURCE


def test_appelle_la_route_du_coeur():
    assert "'/recherche?'" in _fonction("lancerRecherche")


def test_rendu_par_textcontent_uniquement():
    corps = _fonction("lancerRecherche")
    assert "innerHTML" not in corps and "insertAdjacentHTML" not in corps
    assert re.search(r"\.textContent\s*=", corps)
