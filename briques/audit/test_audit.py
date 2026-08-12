import pytest
from fastapi.testclient import TestClient
import chiffrage


@pytest.fixture
def client(tmp_path, monkeypatch):
    import main as audit_main
    monkeypatch.setattr(audit_main, "DB_PATH", str(tmp_path / "audits.db"))
    with TestClient(audit_main.app) as c:
        yield c


def test_sante(client):
    resp = client.get("/sante")
    assert resp.status_code == 200
    assert resp.json()["statut"] == "ok"


def test_lister_audits_vide(client):
    resp = client.get("/audits")
    assert resp.status_code == 200
    assert resp.json() == []


def test_lire_audit_inexistant_retourne_404(client):
    resp = client.get("/audits/audit-inexistant-xyz")
    assert resp.status_code == 404


def test_supprimer_audit_inexistant(client):
    resp = client.delete("/audits/audit-inexistant-xyz")
    assert resp.status_code == 204


def test_importer_et_lire_audit(client):
    resp = client.post("/audits/import", json={
        "nom_entreprise": "Test SA",
        "statut": "termine",
    })
    assert resp.status_code == 200
    audit_id = resp.json()["id"]

    resp2 = client.get(f"/audits/{audit_id}")
    assert resp2.status_code == 200
    assert resp2.json()["nom_entreprise"] == "Test SA"


def test_importer_et_supprimer_audit(client):
    resp = client.post("/audits/import", json={"nom_entreprise": "Suppr SA"})
    audit_id = resp.json()["id"]
    resp2 = client.delete(f"/audits/{audit_id}")
    assert resp2.status_code == 204


def test_auditer_corps_invalide_retourne_422(client):
    resp = client.post("/auditer", json={"mauvais_champ": "x"})
    assert resp.status_code == 422


def test_auditer_corps_vide_retourne_422(client):
    resp = client.post("/auditer", json={})
    assert resp.status_code == 422


def test_auditer_docs_valide_retourne_202(client, monkeypatch):
    import main as audit_main

    async def _noop(*a, **kw):
        pass

    monkeypatch.setattr(audit_main, "_lancer_audit", _noop)
    resp = client.post("/auditer", json={"doc_ids": ["doc-1", "doc-2"]})
    assert resp.status_code == 202
    data = resp.json()
    assert "id" in data
    assert "statut" in data


def test_les_appels_a_l_ingestion_portent_la_cle_de_service(monkeypatch):
    """S211 : `ingestion` est fermée par API_KEYS — `audit` déclare `besoin: ingestion`,
    elle doit présenter INGESTION_KEY, sinon elle ne lit plus un seul document (401)."""
    import importlib
    import main as audit_main

    monkeypatch.setenv("INGESTION_KEY", "cle-ingestion-de-test")
    importlib.reload(audit_main)
    assert audit_main.INGESTION_ENTETES == {"X-API-Key": "cle-ingestion-de-test"}

    monkeypatch.delenv("INGESTION_KEY", raising=False)
    importlib.reload(audit_main)
    # Sans clé : dict vide, pas d'en-tête bidon — une brique en mode ouvert répond comme avant.
    assert audit_main.INGESTION_ENTETES == {}


def test_auditer_tout_sans_ingestion_retourne_502(client, monkeypatch):
    import main as audit_main

    async def _raise(*a, **kw):
        raise Exception("Brique ingestion inaccessible en test")

    monkeypatch.setattr(audit_main, "_recuperer_tous_ids", _raise)
    resp = client.post("/auditer/tout")
    assert resp.status_code == 502


def test_audit_roi_serialise_puis_relu_en_json(client):
    resp = client.post("/audits/import", json={
        "nom_entreprise": "ROI SA",
        "statut": "termine",
        "roi": {"problemes": [{"probleme": "Relances manuelles", "statut": "hypothese_llm"}]},
    })
    assert resp.status_code == 200
    audit_id = resp.json()["id"]

    resp2 = client.get(f"/audits/{audit_id}")
    assert resp2.json()["roi"] == {
        "problemes": [{"probleme": "Relances manuelles", "statut": "hypothese_llm"}]
    }


def test_audit_sans_roi_retourne_champ_absent_ou_null(client):
    resp = client.post("/audits/import", json={"nom_entreprise": "SansROI SA", "statut": "termine"})
    audit_id = resp.json()["id"]
    resp2 = client.get(f"/audits/{audit_id}")
    assert resp2.json().get("roi") is None


def test_chiffrer_cout_horaire_fourni_marque_fourni_client_et_efface_la_fourchette(monkeypatch):
    async def faux_llm(prompt):
        return {"problemes": [{
            "probleme": "Relances manuelles", "pole": "commercial",
            "temps_mensuel_heures": 20,
            "cout_horaire_estime": {"bas": 30, "moyen": 40, "haut": 50},
            "cout_actuel_estime": {"bas": 500, "haut": 700},
            "gain_potentiel_estime": {"bas": 300, "haut": 400},
        }], "synthese": "Gain notable sur les relances."}
    monkeypatch.setattr(chiffrage, "appeler_llm", faux_llm)

    import asyncio
    resultat = asyncio.run(chiffrage.chiffrer({}, {}, {}, {"commercial": 45}))

    entree = resultat["problemes"][0]
    assert entree["statut"] == "fourni_client"
    assert entree["avertissement"] == chiffrage.AVERTISSEMENT
    assert entree["cout_horaire_estime"] is None  # le client a fourni son coût, pas besoin d'hypothèse


def test_chiffrer_sans_cout_horaire_marque_hypothese_llm(monkeypatch):
    async def faux_llm(prompt):
        return {"problemes": [{
            "probleme": "Saisie manuelle", "pole": "administratif",
            "temps_mensuel_heures": 10,
            "cout_horaire_estime": {"bas": 25, "moyen": 30, "haut": 35},
            "cout_actuel_estime": {"bas": 250, "haut": 350},
            "gain_potentiel_estime": {"bas": 150, "haut": 200},
        }]}
    monkeypatch.setattr(chiffrage, "appeler_llm", faux_llm)

    import asyncio
    resultat = asyncio.run(chiffrage.chiffrer({}, {}, {}, None))

    entree = resultat["problemes"][0]
    assert entree["statut"] == "hypothese_llm"
    assert entree["avertissement"] == chiffrage.AVERTISSEMENT
    assert entree["cout_horaire_estime"] == {"bas": 25, "moyen": 30, "haut": 35}


def test_chiffrer_llm_echoue_retourne_none(monkeypatch):
    async def llm_ko(prompt):
        raise RuntimeError("Gateway indisponible")
    monkeypatch.setattr(chiffrage, "appeler_llm", llm_ko)

    import asyncio
    assert asyncio.run(chiffrage.chiffrer({}, {}, {}, None)) is None


def test_chiffrer_audit_inexistant_retourne_404(client):
    resp = client.post("/audits/audit-inexistant-xyz/chiffrer")
    assert resp.status_code == 404


def test_chiffrer_audit_non_termine_retourne_400(client):
    resp = client.post("/audits/import", json={"nom_entreprise": "EnCours SA", "statut": "en_cours"})
    audit_id = resp.json()["id"]
    resp2 = client.post(f"/audits/{audit_id}/chiffrer")
    assert resp2.status_code == 400


def test_chiffrer_endpoint_bout_en_bout_persiste_le_roi(client, monkeypatch):
    resp = client.post("/audits/import", json={
        "nom_entreprise": "Chiffrage SA", "statut": "termine",
        "territoire": {"repartition_ca": [{"libelle": "SAV", "temps_pct": 40}]},
        "problemes": {"pareto": [{"probleme": "Relances manuelles"}]},
        "priorites": {"moscow": {"must": ["Automatiser les relances"]}},
    })
    audit_id = resp.json()["id"]

    async def faux_llm(prompt):
        return {"problemes": [{"probleme": "Relances manuelles", "pole": "commercial",
                                "cout_actuel_estime": {"bas": 500, "haut": 700},
                                "gain_potentiel_estime": {"bas": 300, "haut": 400}}],
                "synthese": "Gain notable."}
    monkeypatch.setattr(chiffrage, "appeler_llm", faux_llm)

    resp2 = client.post(f"/audits/{audit_id}/chiffrer", json={"cout_horaire": {"commercial": 45}})
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["statut_roi"] == "termine"
    assert data["roi"]["problemes"][0]["statut"] == "fourni_client"

    resp3 = client.get(f"/audits/{audit_id}")
    assert resp3.json()["roi"]["problemes"][0]["statut"] == "fourni_client"


def test_chiffrer_echec_llm_roi_indisponible_audit_reste_termine(client, monkeypatch):
    resp = client.post("/audits/import", json={"nom_entreprise": "KO SA", "statut": "termine"})
    audit_id = resp.json()["id"]

    async def llm_ko(prompt):
        raise RuntimeError("Gateway indisponible")
    monkeypatch.setattr(chiffrage, "appeler_llm", llm_ko)

    resp2 = client.post(f"/audits/{audit_id}/chiffrer")
    assert resp2.status_code == 200
    assert resp2.json()["statut_roi"] == "roi_indisponible"
    assert resp2.json()["roi"] is None

    resp3 = client.get(f"/audits/{audit_id}")
    assert resp3.json()["statut"] == "termine"  # jamais remis en cause


def test_avertissement_est_le_litteral_exact_de_la_vision():
    """Garde-fou permanent : une régression qui changerait ce texte (ou le ferait générer
    par le LLM) doit casser CE test explicitement, pas être découverte en prod."""
    assert chiffrage.AVERTISSEMENT == "Estimation à valider avec le client — non contractuelle."


def test_toute_sortie_chiffrer_avec_hypothese_contient_l_avertissement_mot_pour_mot(client, monkeypatch):
    resp = client.post("/audits/import", json={"nom_entreprise": "Garde SA", "statut": "termine"})
    audit_id = resp.json()["id"]

    async def faux_llm(prompt):
        return {"problemes": [{"probleme": "X", "pole": "commercial",
                                "cout_actuel_estime": {"bas": 1, "haut": 2},
                                "gain_potentiel_estime": {"bas": 1, "haut": 2}}]}
    monkeypatch.setattr(chiffrage, "appeler_llm", faux_llm)

    resp2 = client.post(f"/audits/{audit_id}/chiffrer")
    assert chiffrage.AVERTISSEMENT in str(resp2.json())
