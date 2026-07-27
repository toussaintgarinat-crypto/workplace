"""Tests de l'API de la brique gateway-sync (S202)."""
import os

os.environ.setdefault("LITELLM_MASTER_KEY", "cle-test")
os.environ.setdefault("OPENROUTER_API_KEY", "cle-openrouter-test")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import sync  # noqa: E402

client = TestClient(main.app)


def test_sante_expose_la_date_du_dernier_sync(monkeypatch):
    """C'est le point du sprint : une liste qui fige doit se VOIR. L'ancien script était
    orphelin depuis le premier jour et sa liste a figé 51 jours sans que rien ne le dise."""
    monkeypatch.setattr(sync, "synchroniser", lambda: {"statut": "ok", "ajoutes": ["free/x/y"]})
    r = client.get("/sante")
    assert r.status_code == 200
    assert "dernier_sync" in r.json()

    client.post("/sync")
    corps = client.get("/sante").json()
    assert corps["dernier_sync"] is not None
    assert corps["dernier_resultat"]["ajoutes"] == ["free/x/y"]


def test_sync_relaie_le_resultat(monkeypatch):
    monkeypatch.setattr(sync, "synchroniser",
                        lambda: {"statut": "ok", "ajoutes": [], "retires": ["free/a/b"]})
    r = client.post("/sync")
    assert r.status_code == 200
    assert r.json()["retires"] == ["free/a/b"]


def test_sync_en_echec_renvoie_502_pas_500(monkeypatch):
    """L'horloge journalise le corps de la réponse : un 502 explicite est lisible dans
    `GET /horloge/taches`, un 500 opaque ne l'est pas."""
    def _boom():
        raise RuntimeError("LiteLLM injoignable")
    monkeypatch.setattr(sync, "synchroniser", _boom)
    r = client.post("/sync")
    assert r.status_code == 502
    assert "LiteLLM injoignable" in r.json()["detail"]


def test_sync_gate_par_la_cle_si_configuree(monkeypatch):
    monkeypatch.setattr(sync, "synchroniser", lambda: {"statut": "ok"})
    monkeypatch.setenv("GATEWAY_SYNC_KEY", "secret-horloge")
    assert client.post("/sync").status_code == 401
    assert client.post("/sync", headers={"X-API-Key": "secret-horloge"}).status_code == 200
    assert client.post("/sync",
                       headers={"Authorization": "Bearer secret-horloge"}).status_code == 200


def test_sync_ouvert_si_aucune_cle_configuree(monkeypatch):
    monkeypatch.setattr(sync, "synchroniser", lambda: {"statut": "ok"})
    monkeypatch.delenv("GATEWAY_SYNC_KEY", raising=False)
    assert client.post("/sync").status_code == 200
