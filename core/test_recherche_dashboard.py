"""S241 — onglet Recherche : présent, appelle /recherche, rend SANS innerHTML.

$ cd core && python3 -m pytest test_recherche_dashboard.py -v
"""
import re
from pathlib import Path

SOURCE = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


def _fonction(nom: str) -> str:
    debut = SOURCE.index(f"async function {nom}(")
    # Jusqu'à la prochaine déclaration de fonction de premier niveau, ou la fin du <script>.
    suite = re.search(r"\n(?:async )?function |</script>", SOURCE[debut + 1:])
    fin = debut + 1 + suite.start() if suite else len(SOURCE)
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


def test_course_entre_recherches_gardee():
    assert "let RECHERCHE_SEQ" in SOURCE
    corps = _fonction("lancerRecherche")
    assert "++RECHERCHE_SEQ" in corps
    assert corps.count("mon !== RECHERCHE_SEQ") >= 2


def test_session_expiree_et_reponse_inattendue():
    corps = _fonction("lancerRecherche")
    assert "401" in corps
    assert "Session expirée" in corps
    assert "Réponse inattendue du serveur" in corps


def test_detail_non_chaine_traite():
    corps = _fonction("lancerRecherche")
    assert "typeof d.detail" in corps
    assert "Requête invalide." in corps


def test_avertissement_sens_base_sur_le_champ_du_coeur_pas_sur_les_modes():
    corps = _fonction("lancerRecherche")
    assert "recherche_par_le_sens_indisponible" in corps
    assert "'lexical'" not in corps
