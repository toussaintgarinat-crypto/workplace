"""Capture de réponse publique (/repondre/{token}) : page SANS authentification —
un particulier scanne un QR sur un courrier papier, pas un client Workplace."""
from fastapi.testclient import TestClient

import main
import stockage

client = TestClient(main.app)


def _courrier(lead_id=None):
    return stockage.creer_courrier("t-repondre", adresse="12 Rue Test", commune="Castres",
                                   lead_id=lead_id, contenu="Bonjour...")


def test_page_reponse_token_valide_sans_authentification():
    c = _courrier()
    r = client.get(f"/repondre/{c['token']}")   # AUCUN header d'authentification
    assert r.status_code == 200
    assert "12 Rue Test" in r.text


def test_page_reponse_token_inconnu_message_neutre():
    r = client.get("/repondre/token-inconnu")
    assert r.status_code == 200   # jamais 404 : ne révèle pas la distinction
    assert "12 Rue Test" not in r.text


def test_enregistrer_reponse_marque_repondu():
    c = _courrier()
    r = client.post(f"/repondre/{c['token']}", data={"interesse": "true"})
    assert r.status_code == 200
    relu = stockage.lire_courrier_par_token(c["token"])
    assert relu["statut"] == "repondu" and relu["reponse_le"]


def test_enregistrer_reponse_deux_fois_message_neutre_la_2e_fois():
    c = _courrier()
    client.post(f"/repondre/{c['token']}", data={"interesse": "true"})
    r2 = client.post(f"/repondre/{c['token']}", data={"interesse": "true"})
    assert r2.status_code == 200
    assert "disponible" in r2.text.lower()   # message neutre, pas "merci" une 2e fois


def test_reponse_interessee_qualifie_le_lead_forge(monkeypatch):
    appels = []

    def _faux_post(url, json=None, headers=None, timeout=None):
        appels.append((url, json))
        class _Rep:
            def raise_for_status(self):
                pass
        return _Rep()
    monkeypatch.setattr(main.httpx, "post", _faux_post)
    c = _courrier(lead_id="lead-xyz")
    client.post(f"/repondre/{c['token']}", data={"interesse": "true"})
    assert len(appels) == 1
    url, corps = appels[0]
    assert url.endswith("/crm/lead-xyz") and corps == {"statut": "lead qualifié"}


def test_reponse_non_interessee_ne_qualifie_pas(monkeypatch):
    appels = []
    monkeypatch.setattr(main.httpx, "post", lambda *a, **k: appels.append(1))
    c = _courrier(lead_id="lead-abc")
    client.post(f"/repondre/{c['token']}", data={"interesse": "false"})
    assert appels == []


def test_reponse_forge_injoignable_najamais_bloquant(monkeypatch):
    def _casse(*a, **k):
        raise Exception("forge injoignable")
    monkeypatch.setattr(main.httpx, "post", _casse)
    c = _courrier(lead_id="lead-panne")
    r = client.post(f"/repondre/{c['token']}", data={"interesse": "true"})
    assert r.status_code == 200   # la capture de réponse réussit MALGRÉ la panne forge
    assert stockage.lire_courrier_par_token(c["token"])["statut"] == "repondu"
