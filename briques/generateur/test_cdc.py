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


def test_generer_cdc_audit_inexistant_retourne_404(client, monkeypatch):
    import main as gen_main

    async def audit_ko(audit_id):
        return {}
    monkeypatch.setattr(gen_main, "_charger_audit", audit_ko)

    resp = client.post("/audits/audit-inexistant/cahier-des-charges")
    assert resp.status_code == 404


def test_generer_cdc_audit_non_termine_retourne_400(client, monkeypatch):
    import main as gen_main

    async def audit_en_cours(audit_id):
        return {"statut": "en_cours"}
    monkeypatch.setattr(gen_main, "_charger_audit", audit_en_cours)

    resp = client.post("/audits/audit-en-cours/cahier-des-charges")
    assert resp.status_code == 400


def test_generer_cdc_bout_en_bout_puis_le_lire(client, monkeypatch):
    import main as gen_main
    import cdc

    async def audit_termine(audit_id):
        return {"statut": "termine", "nom_entreprise": "CDC SA"}
    monkeypatch.setattr(gen_main, "_charger_audit", audit_termine)

    async def faux_llm(prompt, langue="fr"):
        return {cle: f"Contenu {cle}" for cle, _ in cdc._SECTIONS_CDC}
    monkeypatch.setattr(cdc, "appeler_llm", faux_llm)

    resp = client.post("/audits/cdc-audit-1/cahier-des-charges")
    assert resp.status_code == 200
    assert "## Objectifs" in resp.json()["markdown"]
    assert resp.json()["pdf_chemin"] is None

    resp2 = client.get("/audits/cdc-audit-1/cahier-des-charges")
    assert resp2.status_code == 200
    assert resp2.json()["markdown"] == resp.json()["markdown"]


def test_lire_cdc_sans_generation_prealable_retourne_404(client):
    resp = client.get("/audits/jamais-genere/cahier-des-charges")
    assert resp.status_code == 404


def test_generer_cdc_deux_fois_lit_le_plus_recent(client, monkeypatch):
    """Extra test for DESC ordering: verify that when multiple CDC rows exist for the same
    audit_id, the newest (most recent created_at) is returned."""
    import main as gen_main
    import cdc

    async def audit_termine(audit_id):
        return {"statut": "termine", "nom_entreprise": "CDC SA"}
    monkeypatch.setattr(gen_main, "_charger_audit", audit_termine)

    call_count = [0]

    async def faux_llm_variable(prompt, langue="fr"):
        """Return different content based on call count to verify we get the latest."""
        call_count[0] += 1
        marker = f"MARKER_{call_count[0]}"
        return {cle: f"{marker} Contenu {cle}" for cle, _ in cdc._SECTIONS_CDC}

    monkeypatch.setattr(cdc, "appeler_llm", faux_llm_variable)

    # Generate CDC the first time
    resp1 = client.post("/audits/cdc-audit-multi/cahier-des-charges")
    assert resp1.status_code == 200
    first_markdown = resp1.json()["markdown"]
    assert "MARKER_1" in first_markdown

    # Generate CDC the second time
    resp2 = client.post("/audits/cdc-audit-multi/cahier-des-charges")
    assert resp2.status_code == 200
    second_markdown = resp2.json()["markdown"]
    assert "MARKER_2" in second_markdown

    # Read should return the SECOND (newest) one
    resp3 = client.get("/audits/cdc-audit-multi/cahier-des-charges")
    assert resp3.status_code == 200
    read_markdown = resp3.json()["markdown"]
    assert read_markdown == second_markdown
    assert "MARKER_2" in read_markdown
    assert "MARKER_1" not in read_markdown
