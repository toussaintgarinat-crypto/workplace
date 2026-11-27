import asyncio
import base64
import os

import pytest
from fastapi.testclient import TestClient

import chiffrement
import donnees_utilisateur as D
import main
import paquets as P
from client_executeur import ExecuteurErreur
from contrats import ContratErreur


@pytest.fixture(autouse=True)
def cle(monkeypatch):
    monkeypatch.setenv("LIVRAISON_CHIFFREMENT_CLE", base64.b64encode(os.urandom(32)).decode())


class FauxExecuteur:
    def __init__(self):
        self.objets, self.echec_depot, self.echec_suppression = {}, False, False

    async def deposer(self, cle, octets):
        if self.echec_depot:
            raise ExecuteurErreur("injoignable")
        self.objets[cle] = octets

    async def lire(self, cle):
        return self.objets[cle]

    async def supprimer(self, cle):
        if self.echec_suppression:
            raise ExecuteurErreur("injoignable")
        self.objets.pop(cle, None)


class FauxApp:
    nom, version_schema = "studio", "1"

    def __init__(self, paquet=b"PAQUET-CLAIR", empreinte="emp1", verif_emp="emp1", verif_exc=None):
        self.paquet, self.emp, self.verif_emp, self.verif_exc = paquet, empreinte, verif_emp, verif_exc
        self.recu_verif = None

    async def exporter(self, u):
        return self.paquet, {"empreinte": self.emp, "comptages": {"series": 2}}

    async def verifier(self, u, paquet):
        self.recu_verif = paquet
        if self.verif_exc:
            raise self.verif_exc
        return {"ok": True, "empreinte": self.verif_emp, "comptages": {"series": 2}}


def run(c):
    return asyncio.run(c)


def test_exporter_stocke_chiffre_et_ne_renvoie_aucune_donnee():
    ex, app = FauxExecuteur(), FauxApp()
    r = run(D.exporter_et_stocker(app, ex, "claire"))
    assert set(r) == {"paquet_id", "empreinte", "comptages", "version_schema", "expire_a", "h"}
    (cle_obj, blob), = ex.objets.items()
    assert b"PAQUET-CLAIR" not in blob and "claire" not in cle_obj
    assert chiffrement.dechiffrer(blob, cle_obj) == b"PAQUET-CLAIR"
    assert P.lire(r["paquet_id"])["objet"] == cle_obj
    assert "claire" not in str(P.lire(r["paquet_id"]))


def test_depot_en_echec_n_enregistre_rien():
    ex = FauxExecuteur()
    ex.echec_depot = True
    with pytest.raises(ExecuteurErreur):
        run(D.exporter_et_stocker(FauxApp(), ex, "claire"))
    assert not os.path.exists(os.path.join(os.environ["LIVRAISON_DATA"], "paquets.json"))


def test_verifier_valide_relit_depuis_le_stockage():
    ex, app = FauxExecuteur(), FauxApp()
    r = run(D.verifier_paquet(app, ex, "claire"))
    assert r["ok"] is True and r["verdict"] == "valide" and r["raisons"] == []
    assert r["preuve_id"] == r["paquet_id"]
    assert app.recu_verif == b"PAQUET-CLAIR"   # l'app a vérifié le paquet RELU puis déchiffré
    assert P.lire(r["paquet_id"])["verifie_a"] is not None


def test_verifier_empreinte_differente_invalide():
    r = run(D.verifier_paquet(FauxApp(verif_emp="autre"), FauxExecuteur(), "claire"))
    assert r["verdict"] == "invalide" and P.lire(r["paquet_id"])["verifie_a"] is None


def test_verifier_refus_de_l_app_invalide_sans_exception():
    app = FauxApp(verif_exc=ContratErreur("x", 422, "signature"))
    r = run(D.verifier_paquet(app, FauxExecuteur(), "claire"))
    assert r["ok"] is True and r["verdict"] == "invalide" and "signature" in " ".join(r["raisons"])


def test_verifier_objet_altere_dans_le_stockage_invalide():
    ex, app = FauxExecuteur(), FauxApp()
    orig = ex.deposer

    async def altere(cle, octets):
        await orig(cle, octets[:-1] + bytes([octets[-1] ^ 1]))
    ex.deposer = altere
    r = run(D.verifier_paquet(app, ex, "claire"))
    assert r["verdict"] == "invalide" and app.recu_verif is None


def test_purge_supprime_les_expires_et_garde_en_cas_d_echec():
    ex = FauxExecuteur()
    vieux = run(D.exporter_et_stocker(FauxApp(), ex, "a", maintenant=0.0))
    recent = run(D.exporter_et_stocker(FauxApp(), ex, "b"))
    ex.echec_suppression = True
    assert run(D.purger_expires(ex, maintenant=20 * 86400.0)) == {"supprimes": 0, "restants": 1}
    assert P.lire(vieux["paquet_id"]) is not None
    ex.echec_suppression = False
    assert run(D.purger_expires(ex, maintenant=20 * 86400.0)) == {"supprimes": 1, "restants": 0}
    assert P.lire(vieux["paquet_id"]) is None and P.lire(recent["paquet_id"]) is not None


# ── Routes ──
c = TestClient(main.app)


def test_route_sans_cle_chiffrement_503(monkeypatch):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "k")
    monkeypatch.delenv("LIVRAISON_CHIFFREMENT_CLE")
    monkeypatch.setattr(main.contrats, "ouvrir", lambda nom: FauxApp())
    monkeypatch.setattr(main, "executeur", lambda: FauxExecuteur())
    r = c.post("/contrats/studio/exporter", json={"utilisateur": "claire"}, headers={"X-API-Key": "k"})
    assert r.status_code == 503


def test_route_fail_closed_sans_cles_api(monkeypatch):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "")
    assert c.post("/contrats/studio/exporter", json={"utilisateur": "claire"}).status_code == 403


@pytest.mark.parametrize("u", ["", "a b", "../x", "x" * 129, "a\nb"])
def test_route_utilisateur_invalide_422(monkeypatch, u):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "k")
    r = c.post("/contrats/studio/exporter", json={"utilisateur": u}, headers={"X-API-Key": "k"})
    assert r.status_code == 422


def test_route_exporter_nominale(monkeypatch):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "k")
    monkeypatch.setattr(main.contrats, "ouvrir", lambda nom: FauxApp())
    ex = FauxExecuteur()
    monkeypatch.setattr(main, "executeur", lambda: ex)
    r = c.post("/contrats/studio/exporter", json={"utilisateur": "claire"}, headers={"X-API-Key": "k"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert "claire" not in r.text and "PAQUET" not in r.text


def test_route_app_inconnue_404(monkeypatch):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "k")
    r = c.post("/contrats/inconnue/exporter", json={"utilisateur": "claire"}, headers={"X-API-Key": "k"})
    assert r.status_code == 404


class AppCasse(FauxApp):
    def __init__(self, retour=None, exc=None):
        super().__init__()
        self.retour, self.exc = retour, exc

    async def verifier(self, u, paquet):
        if self.exc:
            raise self.exc
        return self.retour


@pytest.mark.parametrize("app", [AppCasse(exc=ValueError("secret")), AppCasse(retour=[1]),
                                 AppCasse(retour=None)])
def test_verifier_erreur_inattendue_invalide_sans_exception(app):
    r = run(D.verifier_paquet(app, FauxExecuteur(), "claire"))
    assert r["ok"] is True and r["verdict"] == "invalide" and r["raisons"]
    assert "secret" not in str(r) and P.lire(r["paquet_id"])["verifie_a"] is None


def test_verifier_registre_sans_le_paquet_invalide(monkeypatch):
    monkeypatch.setattr(D.paquets, "lire", lambda pid: None)
    r = run(D.verifier_paquet(FauxApp(), FauxExecuteur(), "claire"))
    assert r["ok"] is True and r["verdict"] == "invalide"
    assert r["raisons"] == ["paquet introuvable dans le registre"]


def test_purge_une_erreur_disque_n_arrete_pas_les_suivants(monkeypatch):
    ex = FauxExecuteur()
    a = run(D.exporter_et_stocker(FauxApp(), ex, "a", maintenant=0.0))
    b = run(D.exporter_et_stocker(FauxApp(), ex, "b", maintenant=0.0))
    reel = P.retirer

    def retirer(pid):
        if pid == a["paquet_id"]:
            raise OSError("disque")
        reel(pid)
    monkeypatch.setattr(D.paquets, "retirer", retirer)
    r = run(D.purger_expires(ex, maintenant=20 * 86400.0))
    assert r == {"supprimes": 1, "restants": 1}
    assert P.lire(b["paquet_id"]) is None


def test_boucle_purge_journalise_un_avertissement(monkeypatch, caplog):
    async def echoue(ex):
        raise RuntimeError("detail-secret")
    monkeypatch.setattr(main.DU, "purger_expires", echoue)
    monkeypatch.setattr(main, "executeur", lambda: FauxExecuteur())
    with caplog.at_level("WARNING"):
        run(main._purger_une_fois())
    assert "RuntimeError" in caplog.text and "detail-secret" not in caplog.text


def test_route_registre_illisible_503_sans_fuite(monkeypatch):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "k")
    monkeypatch.setattr(main.contrats, "ouvrir", lambda nom: FauxApp())
    monkeypatch.setattr(main, "executeur", lambda: FauxExecuteur())
    d = os.path.join(os.environ["LIVRAISON_DATA"])
    os.makedirs(d)
    open(os.path.join(d, "paquets.json"), "w").write("{corrompu")
    r = c.post("/contrats/studio/exporter", json={"utilisateur": "claire"}, headers={"X-API-Key": "k"})
    assert r.status_code == 503 and r.json()["detail"] == "registre des paquets illisible"


def test_routes_reset_et_restitution_codes(monkeypatch):
    monkeypatch.setenv("LIVRAISON_API_KEYS", "k")
    H = {"X-API-Key": "k"}
    for route in ("reinitialiser", "restituer"):
        assert c.post(f"/contrats/studio/{route}", json={"utilisateur": "claire"}).status_code == 401
    monkeypatch.setattr(main.contrats, "ouvrir", lambda nom: FauxApp())
    monkeypatch.setattr(main, "executeur", lambda: FauxExecuteur())
    r = c.post("/contrats/studio/reinitialiser", json={"utilisateur": "claire"}, headers=H)
    assert r.status_code == 409 and "paquet vérifié" in r.json()["detail"]
    assert "claire" not in r.text
    r = c.post("/contrats/studio/restituer", json={"utilisateur": "claire"}, headers=H)
    assert r.status_code == 404
    r = c.post("/contrats/studio/restituer", json={"utilisateur": "claire", "paquet_id": "zz"}, headers=H)
    assert r.status_code == 422
