import json
import os
import pytest
from pathlib import Path
import operations


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVRAISON_DATA", str(tmp_path))
    return tmp_path


def test_persistance_apres_relecture():
    oid = operations.demarrer("app", "reset")
    d = operations.lire("app")
    assert d["op"]["id"] == oid and d["op"]["etat"] == "en_cours" and d["op"]["type"] == "reset"
    operations.etape("app", oid, "clonage", essais=2)
    op = operations.lire("app")["op"]
    assert op["etape"] == "clonage" and op["essais"] == 2


def test_demarrer_deux_fois():
    operations.demarrer("app", "reset")
    with pytest.raises(operations.OperationEnCours):
        operations.demarrer("app", "reset")


def test_redemarrer_apres_terminer():
    oid = operations.demarrer("app", "reset")
    operations.terminer("app", oid, "reussie", "ok")
    op = operations.lire("app")["op"]
    assert op["etat"] == "reussie" and op["fin"] and op["message"] == "ok"
    assert operations.demarrer("app", "reset") != oid


def test_terminer_etat_invalide():
    oid = operations.demarrer("app", "reset")
    with pytest.raises(ValueError):
        operations.terminer("app", oid, "bidon")


def test_etape_terminer_sans_op_ou_mauvais_id():
    with pytest.raises(operations.OperationInconnue):
        operations.etape("app", "x", "n")
    with pytest.raises(operations.OperationInconnue):
        operations.terminer("app", "x", "echec")
    oid = operations.demarrer("app", "reset")
    with pytest.raises(operations.OperationInconnue):
        operations.terminer("app", "autre", "echec")
    operations.terminer("app", oid, "echec")
    with pytest.raises(operations.OperationInconnue):
        operations.etape("app", oid, "n")  # terminée : ne ressuscite pas
    assert operations.lire("app")["op"]["etat"] == "echec"


def test_message_tronque_et_nettoye():
    oid = operations.demarrer("app", "reset")
    operations.terminer("app", oid, "echec", "a\x00b\x1b[31m" + "x" * 500)
    m = operations.lire("app")["op"]["message"]
    assert len(m) <= 300 and "\x00" not in m and "\x1b" not in m


def test_emplacements_et_bascule():
    operations.enregistrer_emplacements(
        "app", {"app_id": "a1", "domaine_id": "d1"}, {"app_id": "b1", "domaine_id": "d2"},
        "A", "temoin")
    d = operations.lire("app")
    assert d["emplacements"]["B"]["app_id"] == "b1" and d["actif"] == "A"
    assert d["base_active"] == "temoin" and d["base_precedente"] is None
    operations.basculer_etat("app", "B", "neuve", "temoin")
    d = operations.lire("app")
    assert (d["actif"], d["base_active"], d["base_precedente"]) == ("B", "neuve", "temoin")


def test_lire_copie_profonde():
    operations.demarrer("app", "reset")
    operations.lire("app")["op"]["etat"] = "pirate"
    assert operations.lire("app")["op"]["etat"] == "en_cours"


def test_marquer_interrompues():
    operations.demarrer("a", "reset")
    oid = operations.demarrer("b", "reset")
    operations.terminer("b", oid, "reussie")
    assert operations.marquer_interrompues() == ["a"]
    op = operations.lire("a")["op"]
    assert op["etat"] == "interrompue" and op["fin"]
    assert op["message"] == "la brique a redémarré pendant l'opération"
    assert operations.lire("b")["op"]["etat"] == "reussie"
    assert operations.marquer_interrompues() == []


def test_tmp_orphelin_jamais_lu(data):
    (data / "operations.json.tmp").write_text('{"app": {"op": {"etat": "en_cours"}}}')
    assert operations.lire("app") is None


def test_oserror_propage_etat_intact(data, monkeypatch):
    oid = operations.demarrer("app", "reset")
    avant = json.loads((data / "operations.json").read_text())
    def boom(*a, **k):
        raise OSError("disque plein")
    with monkeypatch.context() as m:
        m.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            operations.etape("app", oid, "clonage")
    assert json.loads((data / "operations.json").read_text()) == avant


def test_fsync_oserror_propage_etat_intact(data, monkeypatch):
    oid = operations.demarrer("app", "reset")
    avant = json.loads((data / "operations.json").read_text())
    def boom(*a, **k):
        raise OSError("fsync")
    with monkeypatch.context() as m:
        m.setattr(os, "fsync", boom)
        with pytest.raises(OSError):
            operations.etape("app", oid, "clonage")
    assert json.loads((data / "operations.json").read_text()) == avant


def test_demarrer_oserror_ne_demarre_pas(monkeypatch):
    def boom(*a, **k):
        raise OSError("x")
    with monkeypatch.context() as m:
        m.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            operations.demarrer("app", "reset")
    assert operations.lire("app") is None


@pytest.mark.parametrize("contenu", ["{pas du json", "[1, 2]", ""])
def test_fichier_corrompu(data, contenu):
    (data / "operations.json").write_text(contenu)
    assert operations.lire("app") is None
    oid = operations.demarrer("app", "reset")
    assert operations.lire("app")["op"]["id"] == oid
    assert isinstance(json.loads((data / "operations.json").read_text()), dict)


def test_erreur_lecture_propage_fichier_intact(data, monkeypatch):
    operations.demarrer("app", "reset")
    brut = (data / "operations.json").read_text()
    def boom(self, *a, **k):
        raise PermissionError("refusé")
    with monkeypatch.context() as m:
        m.setattr(Path, "read_text", boom)
        with pytest.raises(PermissionError):
            operations.lire("app")
        with pytest.raises(PermissionError):
            operations.demarrer("autre", "reset")
    assert (data / "operations.json").read_text() == brut


@pytest.mark.parametrize("contenu", ["{pas du json", "[1, 2]"])
def test_corrompu_renomme(data, contenu):
    (data / "operations.json").write_text(contenu)
    operations.demarrer("app", "reset")
    assert (data / "operations.json.corrompu").read_text() == contenu
    assert "app" in json.loads((data / "operations.json").read_text())


@pytest.mark.parametrize("cle", ["id", "etat", "type", "debut", "fin", "message"])
def test_etape_cles_reservees(cle):
    oid = operations.demarrer("app", "reset")
    with pytest.raises(ValueError, match=cle):
        operations.etape("app", oid, "x", **{cle: "pirate"})
    assert operations.lire("app")["op"]["id"] == oid


def test_emplacements_preservent_base_precedente():
    operations.basculer_etat("app", "A", "db1", "db0")
    operations.enregistrer_emplacements("app", {"x": 1}, {"y": 2}, "A", "db1")
    assert operations.lire("app")["base_precedente"] == "db0"


def test_invalider_retour_puis_bascule_le_retablit():
    operations.basculer_etat("app", "B", "g1", "temoin")
    assert not operations.lire("app").get("retour_invalide")
    operations.invalider_retour("app")
    d = operations.lire("app")
    assert d["retour_invalide"] is True and d["base_precedente"] == "temoin"
    operations.basculer_etat("app", "A", "g2", "g1")
    assert operations.lire("app")["retour_invalide"] is False


def test_invalider_retour_oserror_propage_etat_intact(data, monkeypatch):
    operations.basculer_etat("app", "B", "g1", "temoin")
    avant = json.loads((data / "operations.json").read_text())
    def boom(*a, **k):
        raise OSError("disque plein")
    with monkeypatch.context() as m:
        m.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            operations.invalider_retour("app")
    assert json.loads((data / "operations.json").read_text()) == avant


def test_precedente_protegee_posee_par_retour_effacee_par_reset():
    operations.basculer_etat("app", "B", "g1", "temoin")
    assert operations.precedente_protegee(operations.lire("app")) is False
    operations.basculer_etat("app", "A", "temoin", "g1", precedente_protegee=True)
    d = operations.lire("app")
    assert d["precedente_protegee"] is True and operations.precedente_protegee(d)
    operations.basculer_etat("app", "B", "g2", "temoin")      # reset réussi : effacé
    assert operations.precedente_protegee(operations.lire("app")) is False
    assert operations.precedente_protegee(None) is False


def test_precedente_protegee_oserror_propage_etat_intact(data, monkeypatch):
    operations.basculer_etat("app", "B", "g1", "temoin")
    avant = json.loads((data / "operations.json").read_text())

    def boom(*a, **k):
        raise OSError("fsync")
    with monkeypatch.context() as m:
        m.setattr(os, "fsync", boom)
        with pytest.raises(OSError):
            operations.basculer_etat("app", "A", "temoin", "g1", precedente_protegee=True)
    assert json.loads((data / "operations.json").read_text()) == avant


def test_marquer_interrompues_nomme_la_base_neuve_orpheline():
    operations.basculer_etat("a", "A", "temoin", None)
    oid = operations.demarrer("a", "reset")
    operations.etape("a", oid, "clonage", base_neuve="temoin_v0a1b2c3d")
    operations.marquer_interrompues()
    assert operations.lire("a")["op"]["message"] == (
        "la brique a redémarré pendant l'opération ; base neuve temoin_v0a1b2c3d peut-être "
        "orpheline (à vérifier)")


def test_marquer_interrompues_ne_nomme_pas_la_base_devenue_active():
    operations.basculer_etat("a", "B", "temoin_v0a1b2c3d", "temoin")
    oid = operations.demarrer("a", "reset")
    operations.etape("a", oid, "nettoyage", base_neuve="temoin_v0a1b2c3d")
    operations.marquer_interrompues()
    assert operations.lire("a")["op"]["message"] == "la brique a redémarré pendant l'opération"


def test_marquer_interrompues_pendant_la_bascule_ne_parle_pas_d_orpheline(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVRAISON_DATA", str(tmp_path))
    import operations
    oid = operations.demarrer("app1", "reset")
    operations.enregistrer_emplacements("app1", {"app_id": "A", "domaine_id": "d1"},
                                        {"app_id": "B", "domaine_id": "d2"}, "A", "temoin")
    operations.etape("app1", oid, "bascule", base_neuve="temoin_v0a1b2c3d")
    assert operations.marquer_interrompues() == ["app1"]
    msg = operations.lire("app1")["op"]["message"]
    assert "EN SERVICE" in msg and "orpheline" not in msg and "temoin_v0a1b2c3d" in msg
