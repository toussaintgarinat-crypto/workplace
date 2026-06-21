"""Multi-adresses (v0.1.1) : plusieurs boîtes → boîte unifiée, filtre par compte, déconnexion.

Le vrai IMAP est remplacé par un faux fournisseur (monkeypatch) qui rend des messages canonisés
selon l'adresse — aucun réseau. On travaille sur un tenant dédié (clé API) pour ne pas interférer
avec les autres modules de test qui utilisent le tenant « public ».
"""
import pytest
from fastapi.testclient import TestClient

import fournisseurs
import main

client = TestClient(main.app)
T = {"X-API-Key": "tenant-multi"}


class _FauxImap:
    """Rend 2 messages dont le contenu dépend de l'adresse (pour distinguer les boîtes)."""
    def __init__(self, compte):
        self.adresse = compte["utilisateur"]

    def recuperer(self, dossier="INBOX", limite=50):
        court = self.adresse.split("@")[0]
        return [
            {"id": f"{court}-1", "de": f"facture@{court}.fr", "de_nom": f"Facture {court}",
             "sujet": f"Facture pour {court}", "date": "2026-06-21T08:00:00+00:00",
             "extrait": "montant dû", "corps": "facture", "lu": False, "dossier": "INBOX",
             "source": "imap"},
            {"id": f"{court}-2", "de": f"ami@{court}.fr", "de_nom": f"Ami {court}",
             "sujet": f"Coucou {court}", "date": "2026-06-21T07:00:00+00:00",
             "extrait": "salut", "corps": "salut", "lu": True, "dossier": "INBOX",
             "source": "imap"},
        ]


@pytest.fixture(autouse=True)
def _faux_imap(monkeypatch):
    monkeypatch.setattr(fournisseurs, "Imap", _FauxImap)
    # Repart d'un tenant propre à chaque test.
    for c in client.get("/comptes", headers=T).json()["comptes"]:
        client.delete(f"/comptes/{c['id']}", headers=T)


def _connecter(adresse):
    return client.post("/comptes", json={"host": "imap.x.fr", "utilisateur": adresse,
                                         "mot_de_passe": "app-pass"}, headers=T)


def test_connecter_deux_boites_et_boite_unifiee():
    assert _connecter("perso@gmail.com").status_code == 201
    assert _connecter("pro@boulot.com").status_code == 201
    # Deux comptes listés.
    comptes = client.get("/comptes", headers=T).json()["comptes"]
    assert {c["adresse"] for c in comptes} == {"perso@gmail.com", "pro@boulot.com"}
    # Boîte unifiée : messages des deux adresses, chacun tagué de son compte.
    msgs = client.get("/mail", headers=T).json()["messages"]
    comptes_vus = {m["compte"] for m in msgs}
    assert comptes_vus == {"perso@gmail.com", "pro@boulot.com"}
    assert len(msgs) == 4


def test_config_liste_les_comptes():
    _connecter("perso@gmail.com")
    j = client.get("/config", headers=T).json()
    assert j["configure"] is True and j["fournisseur"] == "imap"
    assert any(c["adresse"] == "perso@gmail.com" for c in j["comptes"])


def test_filtre_par_compte():
    _connecter("perso@gmail.com")
    _connecter("pro@boulot.com")
    seul = client.get("/mail", params={"compte": "pro@boulot.com"}, headers=T).json()
    assert seul["compte"] == "pro@boulot.com"
    assert seul["messages"] and all(m["compte"] == "pro@boulot.com" for m in seul["messages"])


def test_deconnecter_une_boite_garde_l_autre():
    _connecter("perso@gmail.com")
    _connecter("pro@boulot.com")
    pro = next(c for c in client.get("/comptes", headers=T).json()["comptes"]
               if c["adresse"] == "pro@boulot.com")
    assert client.delete(f"/comptes/{pro['id']}", headers=T).status_code == 200
    restant = client.get("/comptes", headers=T).json()["comptes"]
    assert {c["adresse"] for c in restant} == {"perso@gmail.com"}
    # Les messages du pro ont disparu, ceux du perso restent.
    comptes_vus = {m["compte"] for m in client.get("/mail", headers=T).json()["messages"]}
    assert comptes_vus == {"perso@gmail.com"}


def test_reconnecter_meme_adresse_ne_duplique_pas():
    _connecter("perso@gmail.com")
    _connecter("perso@gmail.com")  # mise à jour, pas un doublon
    comptes = client.get("/comptes", headers=T).json()["comptes"]
    assert len(comptes) == 1


def test_deconnecter_inexistant_404():
    assert client.delete("/comptes/inexistant", headers=T).status_code == 404
