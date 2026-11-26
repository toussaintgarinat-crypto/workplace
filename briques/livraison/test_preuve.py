import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
import preuve
from dokploy import Dokploy
from faux_dokploy import fabrique_transport
from test_api import _etat

c = TestClient(main.app)
T0 = 1_000_000.0


@pytest.fixture
def e(monkeypatch):
    etat = _etat()
    monkeypatch.setattr(main, "fournisseur",
                        lambda: Dokploy("http://d.test", "k", transport=fabrique_transport(etat)))
    return etat


def test_sans_preuve_rien_de_valide():
    assert preuve.lire("A1") is None
    assert preuve.valide("A1", T0) is None


def test_preuve_valide_puis_expiree():
    r = preuve.noter("A1", "P1", "valide", {"agenda.evenements": 12}, maintenant=T0)
    assert r["expire_a"] == T0 + preuve.PREUVE_TTL_S
    assert preuve.valide("A1", T0 + 1)["preuve_id"] == "P1"
    assert preuve.valide("A1", T0 + preuve.PREUVE_TTL_S + 1) is None


def test_verdict_invalide_n_est_jamais_valide():
    preuve.noter("A1", "P2", "invalide", {}, maintenant=T0)
    assert preuve.valide("A1", T0 + 1) is None
    assert preuve.lire("A1")["verdict"] == "invalide"


def test_une_preuve_invalide_plus_recente_annule_la_precedente_valide():
    preuve.noter("A1", "P1", "valide", {}, maintenant=T0)
    preuve.noter("A1", "P2", "invalide", {}, maintenant=T0 + 5)
    assert preuve.valide("A1", T0 + 6) is None


def test_preuves_isolees_par_application():
    preuve.noter("A1", "P1", "valide", {}, maintenant=T0)
    assert preuve.valide("A2", T0 + 1) is None


def test_fichier_corrompu_vaut_aucune_preuve(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVRAISON_DATA", str(tmp_path / "d"))
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "preuves_sauvegarde.json").write_text("{pas du json")
    assert preuve.valide("A1", T0) is None


def test_route_preuve_absente(e):
    r = c.get("/apps/calendrier/preuve")
    assert r.status_code == 200
    assert r.json()["valide"] is False and r.json()["app_id"] == "A1"


def test_route_preuve_valide_ne_fuit_que_la_liste_blanche(e):
    preuve.noter("A1", "P1", "valide", {"t": 3})
    d = c.get("/apps/Calendrier/preuve").json()
    assert d["valide"] is True and d["preuve_id"] == "P1" and d["comptages"] == {"t": 3}
    assert set(d) == {"app", "app_id", "valide", "preuve_id", "verdict", "expire_a", "comptages"}


def test_exiger_preuve_refuse_sans_preuve():
    with pytest.raises(HTTPException) as ex:
        main.exiger_preuve("A1")
    assert ex.value.status_code == 409


def test_exiger_preuve_accepte_une_preuve_fraiche():
    preuve.noter("A1", "P1", "valide", {})
    assert main.exiger_preuve("A1")["preuve_id"] == "P1"


def test_verdict_non_valide_refuse_meme_avec_expiration_future(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("LIVRAISON_DATA", str(tmp_path / "data"))
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "preuves_sauvegarde.json").write_text(json.dumps(
        {"A1": {"preuve_id": "P9", "verdict": "invalide", "comptages": {},
                "cree_a": T0, "expire_a": T0 + 10_000}}))
    assert preuve.valide("A1", T0 + 1) is None


def test_expire_a_non_numerique_vaut_aucune_preuve(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("LIVRAISON_DATA", str(tmp_path / "d2"))
    (tmp_path / "d2").mkdir()
    (tmp_path / "d2" / "preuves_sauvegarde.json").write_text(json.dumps(
        {"A1": {"preuve_id": "P9", "verdict": "valide", "comptages": {},
                "cree_a": T0, "expire_a": "demain"}}))
    assert preuve.valide("A1", T0 + 1) is None
    (tmp_path / "d2" / "preuves_sauvegarde.json").write_text(json.dumps(
        {"A1": {"preuve_id": "P9", "verdict": "valide", "expire_a": None}}))
    assert preuve.valide("A1", T0 + 1) is None


def test_revoquer_supprime_la_preuve_et_laisse_les_autres():
    preuve.noter("A1", "P1", "valide", {}, maintenant=T0)
    preuve.noter("A2", "P2", "valide", {}, maintenant=T0)
    preuve.revoquer("A1")
    assert preuve.lire("A1") is None and preuve.valide("A2", T0) is not None


def test_revoquer_sans_fichier_ni_entree_est_sans_effet():
    preuve.revoquer("A1")
    preuve.noter("A2", "P2", "valide", {}, maintenant=T0)
    preuve.revoquer("A1")
    assert preuve.valide("A2", T0) is not None


def test_revoquer_propage_oserror(monkeypatch):
    preuve.noter("A1", "P1", "valide", {}, maintenant=T0)

    def boom(self, *a, **k):
        raise OSError("disque")
    monkeypatch.setattr("pathlib.Path.replace", boom)
    with pytest.raises(OSError):
        preuve.revoquer("A1")
