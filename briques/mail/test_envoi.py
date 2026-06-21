"""Envoi sur validation (v0.2.0) : simulé honnête (mock) et réel SMTP (monkeypatché).

Aucun email ne part pour de vrai : le SMTP est remplacé par un faux client qui capture le message.
On prouve aussi l'honnêteté du mode mock (mode="simule", rien n'est envoyé).
"""
import pytest
from fastapi.testclient import TestClient

import envoi
import fournisseurs
import main

client = TestClient(main.app)


# ── Envoi SIMULÉ depuis la boîte mock (tenant « public » par défaut) ─────────
def test_envoi_mock_est_simule_honnete():
    msg = client.get("/mail").json()["messages"][0]
    br = client.post("/mail/brouillon", json={"message_id": msg["id"]}).json()["brouillon"]
    r = client.post(f"/brouillons/{br['id']}/envoyer", json={})
    assert r.status_code == 200
    j = r.json()
    assert j["envoye"] is True and j["mode"] == "simule"   # rien n'est réellement parti
    # Le brouillon passe à « envoye ».
    envoye = next(b for b in client.get("/brouillons").json()["brouillons"] if b["id"] == br["id"])
    assert envoye["statut"] == "envoye"


def test_double_envoi_refuse():
    msg = client.get("/mail").json()["messages"][1]
    br = client.post("/mail/brouillon", json={"message_id": msg["id"]}).json()["brouillon"]
    assert client.post(f"/brouillons/{br['id']}/envoyer", json={}).status_code == 200
    assert client.post(f"/brouillons/{br['id']}/envoyer", json={}).status_code == 409


def test_envoyer_brouillon_inexistant_404():
    assert client.post("/brouillons/nope/envoyer", json={}).status_code == 404


# ── Envoi RÉEL via SMTP monkeypatché, depuis une vraie boîte ─────────────────
class _FauxImap:
    def __init__(self, compte): self.adresse = compte["utilisateur"]
    def recuperer(self, dossier="INBOX", limite=50):
        return [{"id": "x1", "de": "client@ext.fr", "de_nom": "Client", "sujet": "Question",
                 "date": "2026-06-21T08:00:00+00:00", "extrait": "?", "corps": "?",
                 "lu": False, "dossier": "INBOX", "source": "imap"}]


class _FauxSMTP:
    envoyes = []
    def __init__(self, host, port, timeout=None): self.host, self.port = host, port
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def ehlo(self): pass
    def starttls(self): pass
    def login(self, u, p): _FauxSMTP.creds = (u, p)
    def send_message(self, msg): _FauxSMTP.envoyes.append(msg)


def test_envoi_reel_smtp(monkeypatch):
    monkeypatch.setattr(fournisseurs, "Imap", _FauxImap)
    monkeypatch.setattr(envoi.smtplib, "SMTP", _FauxSMTP)
    _FauxSMTP.envoyes.clear()
    T = {"X-API-Key": "tenant-envoi"}
    # Boîte propre.
    for c in client.get("/comptes", headers=T).json()["comptes"]:
        client.delete(f"/comptes/{c['id']}", headers=T)
    client.post("/comptes", json={"host": "imap.gmail.com", "utilisateur": "moi@gmail.com",
                                  "mot_de_passe": "app-pass"}, headers=T)
    msg = client.get("/mail", headers=T).json()["messages"][0]
    br = client.post("/mail/brouillon", json={"message_id": msg["id"]}, headers=T).json()["brouillon"]
    # Envoi avec un corps « validé » qui remplace le brouillon.
    r = client.post(f"/brouillons/{br['id']}/envoyer", json={"corps": "Voici ma réponse validée."},
                    headers=T)
    assert r.status_code == 200
    j = r.json()
    assert j["mode"] == "reel" and j["de"] == "moi@gmail.com" and j["a"] == "client@ext.fr"
    # Un message a bien été remis au SMTP, avec le bon contenu validé.
    assert len(_FauxSMTP.envoyes) == 1
    envoye = _FauxSMTP.envoyes[0]
    assert envoye["From"] == "moi@gmail.com" and envoye["To"] == "client@ext.fr"
    assert "validée" in envoye.get_content()
    # SMTP deviné depuis l'hôte IMAP : imap.gmail.com → smtp.gmail.com.
    assert _FauxSMTP.creds == ("moi@gmail.com", "app-pass")


def test_serveur_smtp_devine():
    assert envoi.serveur_smtp({"host": "imap.gmail.com"}) == ("smtp.gmail.com", 587)
    assert envoi.serveur_smtp({"host": "imap.x.fr", "smtp_host": "mail.x.fr",
                               "smtp_port": 465}) == ("mail.x.fr", 465)
