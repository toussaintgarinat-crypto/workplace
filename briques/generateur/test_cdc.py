"""Tests S229 : table cahiers_des_charges + endpoints cahier des charges."""
import os
import tempfile

os.environ.setdefault("GATEWAY_KEY", "test-offline")
os.environ.setdefault("DB_PATH", os.path.join(tempfile.gettempdir(), "test_generateur_cdc.db"))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    import main as gen_main
    monkeypatch.setattr(gen_main, "DB_PATH", str(tmp_path / "apps.db"))
    with TestClient(gen_main.app) as c:
        yield c


def test_table_cahiers_des_charges_existe(client):
    import main as gen_main
    with gen_main._connexion() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(cahiers_des_charges)").fetchall()}
    assert cols == {"id", "audit_id", "markdown", "pdf_chemin", "pptx_chemin", "statut", "created_at"}


def test_dernier_cdc_absent_retourne_none(client):
    import main as gen_main
    assert gen_main._dernier_cdc("audit-inexistant") is None


import asyncio

import cdc


def test_section_roi_absente_dit_chiffrage_non_disponible():
    markdown = cdc._section_roi_markdown(None)
    assert "relancer" in markdown.lower()


def test_section_roi_presente_contient_avertissement_mot_pour_mot():
    roi = {"synthese": "Gain notable.", "problemes": [{
        "probleme": "Relances manuelles", "pole": "commercial",
        "cout_actuel_estime": {"bas": 500, "haut": 700},
        "gain_potentiel_estime": {"bas": 300, "haut": 400},
        "statut": "hypothese_llm", "avertissement": cdc.AVERTISSEMENT,
    }]}
    markdown = cdc._section_roi_markdown(roi)
    assert cdc.AVERTISSEMENT in markdown
    assert "Relances manuelles" in markdown


def test_generer_cahier_des_charges_assemble_12_sections_llm_plus_roi(monkeypatch):
    async def faux_llm(prompt, langue="fr"):
        return {cle: f"Contenu {cle}" for cle, _ in cdc._SECTIONS_CDC}
    monkeypatch.setattr(cdc, "appeler_llm", faux_llm)

    audit = {"nom_entreprise": "Test SA", "roi": None}
    markdown = asyncio.run(cdc.generer_cahier_des_charges(audit, "fr"))

    for _, titre in cdc._SECTIONS_CDC:
        assert f"## {titre}" in markdown
    assert "## ROI" in markdown
    assert "relancer" in markdown.lower()


def test_generer_cahier_des_charges_repli_si_llm_echoue(monkeypatch):
    async def llm_ko(prompt, langue="fr"):
        raise RuntimeError("Gateway indisponible")
    monkeypatch.setattr(cdc, "appeler_llm", llm_ko)

    markdown = asyncio.run(cdc.generer_cahier_des_charges({"nom_entreprise": "KO SA"}, "fr"))
    assert "Non disponible" in markdown  # aucune section n'a de contenu, mais le doc existe


def test_construire_diapositives_5_a_8_slides_avec_avertissement_dans_roi():
    audit = {
        "nom_entreprise": "Slides SA",
        "problemes": {"pareto": [{"probleme": "Relances manuelles"}]},
        "priorites": {"moscow": {"must": ["Automatiser"]}, "chemin_critique": [{"id": "T1", "duree_jours": 5}]},
        "roi": {"synthese": "Gain notable."},
    }
    diapos = cdc.construire_diapositives(audit)
    assert 5 <= len(diapos) <= 8
    roi_slide = next(d for d in diapos if d["titre"] == "ROI estimé")
    assert roi_slide["notes"] == cdc.AVERTISSEMENT
