"""Vague finale S248 3b : journaux d'accès, messages de délai, orphelin S3, robustesse de la restitution."""
import asyncio
import base64
import os
import re
from pathlib import Path

import pytest

import donnees_utilisateur as D
import paquets as P
from contrats import ContratErreur
from test_donnees_reset import (AppAEtat, FauxExecuteur, Lent, _H, _brancher, _cl, _id, _verifie,
                                _import_appele, run)

ICI = Path(__file__).parent


@pytest.fixture(autouse=True)
def cle(monkeypatch):
    monkeypatch.setenv("LIVRAISON_CHIFFREMENT_CLE", base64.b64encode(os.urandom(32)).decode())


# 1 ─ pas d'identité dans les journaux d'accès uvicorn
def test_dockerfile_sans_journal_d_acces():
    cmd = next(l for l in (ICI / "Dockerfile").read_text().splitlines() if l.startswith("CMD"))
    assert "--no-access-log" in cmd and '"--host", "0.0.0.0"' in cmd and '"--port", "6240"' in cmd
    t = (ICI / "docker-compose.yml").read_text() + (ICI / "README.md").read_text()
    assert "access.log" not in t


# 2 ─ message du délai global de la remise à zéro : vrai dans les deux cas
@pytest.mark.parametrize("lent", [{"exporter"}, {"reinitialiser"}])
def test_reset_504_global_donne_l_id_et_ne_pretend_pas_que_le_paquet_est_consomme(monkeypatch, lent):
    app, ex = AppAEtat(), FauxExecuteur()
    pid = _verifie(app, ex)["paquet_id"]
    cible = Lent(app, lent)
    if lent == {"exporter"}:
        vrai, etat = app.exporter, {"n": 0}

        async def un_seul_lent(u):          # 1er export (pré-contrôle) lent : AVANT l'effacement
            etat["n"] += 1
            return await Lent(app, {"exporter"}).exporter(u)
        app.exporter = un_seul_lent
        cible = app
    _brancher(monkeypatch, cible, ex)
    r = _cl.post("/contrats/studio/reinitialiser", json={"utilisateur": "claire"}, headers=_H)
    d = r.json()["detail"]
    assert r.status_code == 504
    assert "a peut-être été effectuée" in d and "livraison_donnees_verifier" in d
    assert f"le paquet {pid} reste restituable avec livraison_donnees_restituer (paquet_id)" in d
    assert "consommé" not in d and "claire" not in r.text
    assert not D._EN_COURS


def test_delai_reset_sans_paquet_choisi_rien_touche():
    assert "rien n'a été modifié" in D.message_delai_reset(None)
    m = D.message_delai_reset("a" * 32)
    assert "a" * 32 in m and "rien n'a été modifié" not in m


# 4 ─ objet S3 orphelin si la tâche est annulée / échoue entre dépôt et registre
@pytest.mark.parametrize("exc", [asyncio.CancelledError, OSError, ])
def test_export_annule_ou_echoue_avant_registre_purge_l_objet(monkeypatch, exc):
    app, ex = AppAEtat(), FauxExecuteur()

    def enregistrer(*a, **k):
        raise exc()
    monkeypatch.setattr(D.paquets, "enregistrer", enregistrer)
    with pytest.raises(exc):
        run(D.exporter_et_stocker(app, ex, "claire"))
    assert ex.objets == {}


def test_export_annule_suppression_en_echec_n_masque_pas_l_annulation(monkeypatch):
    app, ex = AppAEtat(), FauxExecuteur()

    async def casse(cle):
        raise RuntimeError("s3")
    ex.supprimer = casse
    monkeypatch.setattr(D.paquets, "enregistrer", lambda *a, **k: (_ for _ in ()).throw(asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        run(D.exporter_et_stocker(app, ex, "claire"))


# 5 ─ restitution
def test_restitution_relit_le_paquet_avant_le_controle_d_etat():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))
    n = len(app.appels)
    vrai = ex.lire

    async def lire(c):
        app.appels.append("lire")
        return await vrai(c)
    ex.lire = lire
    run(D.restituer_donnees(app, ex, "claire"))
    assert app.appels[n:n + 2] == ["lire", "exporter"]


def test_restitution_paquet_illisible_ne_conseille_pas_de_reverifier():
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))
    o = P.lire(_id(v))["objet"]
    ex.objets[o] = ex.objets[o][:-1] + b"\x00"
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
    m = e.value.message
    assert "refais" not in m and "illisible" in m and "impossible" in m and _id(v) in m
    assert not _import_appele(app)


def test_restitution_504_et_409_portent_l_id_et_le_409_dit_applique():
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    pid = _id(v)
    vrai = app.importer

    async def importer_ambigu(u, p):
        raise ContratErreur("x", None, "delai")
    app.importer = importer_ambigu
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire", paquet_id=pid))
    assert e.value.statut == 504 and pid in e.value.message and "peut-être" in e.value.message

    async def importer_partiel(u, p):
        await vrai(u, p)
        app.donnees = {"series": 9, "profils": 9}
    app.importer = importer_partiel
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire", paquet_id=pid))
    assert e.value.statut == 409 and pid in e.value.message and "importé" in e.value.message


def test_restitution_implicite_refusee_si_cle_de_comptage_en_plus_a_zero():
    """Mutation v-c : l'état actuel a une clé de plus (à 0) que le paquet : pas « vide » au sens du
    paquet, donc refus 409 et rien d'importé."""
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))
    app.donnees = {"series": 0, "profils": 0, "extra": 0}
    app.appels.clear()
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
    assert e.value.statut == 409 and not _import_appele(app)
