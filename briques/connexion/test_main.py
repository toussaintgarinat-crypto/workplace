"""Tests API (TestClient) : santé, webhooks, sondage, administration des correspondances."""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert set(data["reseaux"]) == {"telegram", "whatsapp", "discord", "email_sms"}
    assert data["configures"] == []                    # aucun token en test
    assert data["mode_ouvert"] is False


def test_webhook_reseau_inconnu():
    assert client.post("/webhook/nawak", json={}).status_code == 404


def test_webhook_discord_ping_pong():
    # PING Discord (type 1) sans signature → la vérification refuse d'abord (401).
    r = client.post("/webhook/discord", json={"type": 1})
    assert r.status_code == 401


def test_webhook_telegram_inconnu_non_relaye():
    # Pas de token → verif webhook ne réclame rien ; l'interlocuteur n'étant pas relié,
    # rien n'est envoyé à l'assistant (aucun réseau réel touché).
    upd = {"message": {"chat": {"id": 555}, "text": "coucou", "from": {"first_name": "T"}}}
    r = client.post("/webhook/telegram", json=upd)
    assert r.status_code == 200
    data = r.json()
    assert data["recus"] == 1 and data["autorises"] == 0


def test_correspondances_lier_et_lister():
    # voir l'interlocuteur (en attente) via un sondage est inutile ; on lie directement
    r = client.post("/correspondances",
                    json={"reseau": "telegram", "id_externe": "777", "utilisateur": "p@wp"})
    assert r.status_code == 200 and r.json()["ok"] is True
    liste = client.get("/correspondances").json()["correspondances"]
    assert any(c["id_externe"] == "777" and c["statut"] == "lie" for c in liste)


def test_correspondances_lier_invalide():
    assert client.post("/correspondances", json={"utilisateur": "x"}).status_code == 422


def test_sonder_non_configure():
    r = client.post("/sonder/telegram")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "reseau": "telegram", "traites": 0, "configure": False}


def test_envoyer_non_configure():
    r = client.post("/envoyer", json={"reseau": "telegram", "id_externe": "1", "texte": "hi"})
    assert r.status_code == 409
