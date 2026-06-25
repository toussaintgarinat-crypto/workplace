"""Composition d'un mail NEUF (v0.6.0) : dictée → corrigé + mis en forme → brouillon → envoi.

Sans Gateway joignable (cas des tests), `rediger_nouveau` retombe sur la mise en forme LOCALE
honnête (genere_par="local", dictée NON corrigée). On prouve : le brouillon est rangé non envoyé,
le destinataire est requis, la boîte d'envoi est choisie automatiquement, et l'envoi réutilise le
flux validé (simulé honnête / réel SMTP monkeypatché).
"""
from fastapi.testclient import TestClient

import envoi
import fournisseurs
import main

client = TestClient(main.app)


class _FauxImap:
    def __init__(self, compte): self.adresse = compte["utilisateur"]
    def recuperer(self, dossier="INBOX", limite=50):
        return [{"id": "x1", "de": "client@ext.fr", "de_nom": "Client", "sujet": "Question",
                 "date": "2026-06-21T08:00:00+00:00", "extrait": "?", "corps": "?",
                 "lu": False, "dossier": "INBOX", "source": "imap"}]


def test_composer_range_un_brouillon_non_envoye():
    T = {"X-API-Key": "compose-public"}
    r = client.post("/mail/composer", json={
        "a": "jean@exemple.fr", "dictee": "salut jean on décale le rdv a jeudi 14h merci"}, headers=T)
    assert r.status_code == 201
    j = r.json()
    assert j["envoye"] is False
    br = j["brouillon"]
    assert br["a"] == "jean@exemple.fr"
    assert br["en_reponse_a"] == ""          # mail neuf, pas une réponse
    assert br["statut"] == "brouillon"
    # Mise en forme : formule d'appel + signature encadrent la dictée.
    assert "Bonjour" in br["corps"] and "Cordialement" in br["corps"]
    assert "décale le rdv" in br["corps"]    # la dictée est bien présente
    assert br["sujet"]                       # un objet a été proposé
    # Sans boîte réelle connectée : note honnête « envoi simulé ».
    assert j["genere_par"] == "local" and "SIMUL" in j["note"].upper()


def test_composer_exige_destinataire():
    assert client.post("/mail/composer", json={"a": "", "dictee": "coucou"}).status_code == 422


def test_composer_compte_inconnu_404():
    r = client.post("/mail/composer", json={
        "a": "x@y.fr", "dictee": "test", "compte": "pasconnu@nulle.part"})
    assert r.status_code == 404


def test_composer_puis_envoi_simule_honnete():
    T = {"X-API-Key": "compose-envoi-sim"}
    br = client.post("/mail/composer", json={
        "a": "amie@exemple.fr", "dictee": "on se voit demain ?"}, headers=T).json()["brouillon"]
    r = client.post(f"/brouillons/{br['id']}/envoyer", json={}, headers=T)
    assert r.status_code == 200 and r.json()["mode"] == "simule"   # rien ne part


class _FauxSMTP:
    envoyes = []
    def __init__(self, host, port, timeout=None): self.host, self.port = host, port
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def ehlo(self): pass
    def starttls(self): pass
    def login(self, u, p): _FauxSMTP.creds = (u, p)
    def send_message(self, msg): _FauxSMTP.envoyes.append(msg)


def test_composer_choisit_la_boite_unique_et_envoi_reel(monkeypatch):
    monkeypatch.setattr(fournisseurs, "Imap", _FauxImap)
    monkeypatch.setattr(envoi.smtplib, "SMTP", _FauxSMTP)
    _FauxSMTP.envoyes.clear()
    T = {"X-API-Key": "compose-envoi-reel"}
    for c in client.get("/comptes", headers=T).json()["comptes"]:
        client.delete(f"/comptes/{c['id']}", headers=T)
    client.post("/comptes", json={"host": "imap.gmail.com", "utilisateur": "moi@gmail.com",
                                  "mot_de_passe": "app-pass"}, headers=T)
    # Aucun `compte` précisé : la boîte unique connectée est choisie automatiquement.
    br = client.post("/mail/composer", json={
        "a": "client@ext.fr", "dictee": "voici le devis demandé"}, headers=T).json()["brouillon"]
    assert br["compte"] == "moi@gmail.com"
    r = client.post(f"/brouillons/{br['id']}/envoyer", json={}, headers=T)
    assert r.status_code == 200
    j = r.json()
    assert j["mode"] == "reel" and j["de"] == "moi@gmail.com" and j["a"] == "client@ext.fr"
    assert len(_FauxSMTP.envoyes) == 1
    assert _FauxSMTP.envoyes[0]["To"] == "client@ext.fr"
