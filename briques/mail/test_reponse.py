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


def test_reponse_forge_erreur_http_loggee_pas_bloquante(monkeypatch, caplog):
    """Finding 1: forge reachable but returns error status (404/500).
    Should log the error AND still record the reply (best-effort)."""
    def _faux_post_erreur(url, json=None, headers=None, timeout=None):
        class _Rep:
            status_code = 404
            def raise_for_status(self):
                raise main.httpx.HTTPStatusError(
                    message="404 Not Found",
                    request=None,
                    response=self
                )
        return _Rep()
    monkeypatch.setattr(main.httpx, "post", _faux_post_erreur)
    c = _courrier(lead_id="lead-not-found")
    r = client.post(f"/repondre/{c['token']}", data={"interesse": "true"})
    assert r.status_code == 200
    assert stockage.lire_courrier_par_token(c["token"])["statut"] == "repondu"
    # Verify the error was logged
    assert "qualification lead forge" in caplog.text and "lead-not-found" in caplog.text


def test_page_reponse_adresse_xss_echappee(monkeypatch):
    """Finding 2: adresse with malicious HTML/JS is escaped, not rendered.
    Prevents XSS on the public /repondre/{token} page."""
    # Override stockage.creer_courrier to set an XSS payload in the adresse field
    malicious_adresse = "<script>alert('xss')</script>"
    c = stockage.creer_courrier("t-xss", adresse=malicious_adresse, commune="Test",
                                lead_id=None, contenu="Test content")
    r = client.get(f"/repondre/{c['token']}")
    assert r.status_code == 200
    # The raw script tag should NOT appear in the response body
    assert "<script>" not in r.text
    # The escaped version SHOULD appear
    assert "&lt;script&gt;" in r.text
