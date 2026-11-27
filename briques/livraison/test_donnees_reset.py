import asyncio
import base64
import os

import pytest

import chiffrement
import donnees_utilisateur as D
import paquets as P
from contrats import ContratErreur


@pytest.fixture(autouse=True)
def cle(monkeypatch):
    monkeypatch.setenv("LIVRAISON_CHIFFREMENT_CLE", base64.b64encode(os.urandom(32)).decode())


class FauxExecuteur:
    def __init__(self):
        self.objets = {}

    async def deposer(self, cle, octets):
        self.objets[cle] = octets

    async def lire(self, cle):
        return self.objets[cle]

    async def supprimer(self, cle):
        self.objets.pop(cle, None)


class AppAEtat:
    """App en mémoire : `donnees` = comptages courants ; l'empreinte en dépend."""
    nom, version_schema = "studio", "1"

    def __init__(self, donnees=None, resurrection=False):
        self.donnees = dict(donnees or {"series": 2, "profils": 1})
        self.resurrection, self.appels = resurrection, []

    def _emp(self):
        return "emp:" + ",".join(f"{k}={v}" for k, v in sorted(self.donnees.items()))

    async def exporter(self, u):
        self.appels.append("exporter")
        return b"PAQUET:" + self._emp().encode(), {"empreinte": self._emp(), "comptages": dict(self.donnees)}

    async def verifier(self, u, paquet):
        return {"ok": True, "empreinte": paquet.decode().removeprefix("PAQUET:")}

    async def reinitialiser(self, u, empreinte):
        self.appels.append("reinitialiser")
        if empreinte != self._emp():
            raise ContratErreur("x", 409, "empreinte")
        suppr, self.donnees = dict(self.donnees), {k: 0 for k in self.donnees}
        if self.resurrection:                       # un handler async re-sauvegarde une série
            self.donnees["series"] = 1
        return {"ok": True, "supprimes": suppr}

    async def importer(self, u, paquet):
        self.appels.append("importer")
        emp = paquet.decode().removeprefix("PAQUET:emp:")
        self.donnees = {k: int(v) for k, v in (p.split("=") for p in emp.split(","))}
        return {"ok": True, "comptages": dict(self.donnees)}


def run(c):
    return asyncio.run(c)


def _verifie(app, ex, u="claire"):
    r = run(D.verifier_paquet(app, ex, u))
    assert r["verdict"] == "valide"
    return r


def test_reset_nominal_puis_restitution_redonne_l_etat_initial():
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    r = run(D.reinitialiser_donnees(app, ex, "claire"))
    assert r["etat"] == "reinitialise" and r["supprimes"] == {"series": 2, "profils": 1}
    assert app.donnees == {"series": 0, "profils": 0}
    assert P.lire(v["paquet_id"])["consomme_a"] is not None
    back = run(D.restituer_donnees(app, ex, "claire"))
    assert back["etat"] == "restitue" and app.donnees == {"series": 2, "profils": 1}
    assert back["paquet_id"] == v["paquet_id"]


def test_reset_sans_paquet_verifie_refuse_et_ne_touche_pas_l_app():
    app = AppAEtat()
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, FauxExecuteur(), "claire"))
    assert e.value.statut == 409 and "reinitialiser" not in app.appels


def test_reset_refuse_si_les_donnees_ont_change_depuis_la_verification():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)
    app.donnees["series"] = 3                        # Claire a écrit depuis
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert "changé" in e.value.message and "reinitialiser" not in app.appels


def test_reset_refuse_si_paquet_stocke_illisible():
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    cle_obj = P.lire(v["paquet_id"])["objet"]
    ex.objets[cle_obj] = ex.objets[cle_obj][:-1] + b"\x00"
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert "illisible" in e.value.message and "reinitialiser" not in app.appels


def test_reset_refuse_si_preuve_de_plus_de_6h():
    ex, app = FauxExecuteur(), AppAEtat()
    v = run(D.verifier_paquet(app, ex, "claire", maintenant=1000.0))
    assert v["verdict"] == "valide"
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire", maintenant=1000.0 + 6 * 3600 + 1))
    assert e.value.statut == 409 and e.value.message.startswith("aucun paquet vérifié")
    assert "reinitialiser" not in app.appels


def test_un_paquet_ne_sert_qu_a_un_reset():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))
    app.donnees = {"series": 2, "profils": 1}          # même état : l'empreinte ne refuse pas
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert e.value.statut == 409 and e.value.message.startswith("aucun paquet vérifié")


def test_resurrection_detectee_reset_jamais_declare_reussi():
    ex, app = FauxExecuteur(), AppAEtat(resurrection=True)
    _verifie(app, ex)
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert e.value.statut == 409 and "incomplet" in e.value.message


def test_cible_differente_ne_voit_pas_le_paquet():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex, "claire")
    with pytest.raises(D.RefusDonnees):
        run(D.reinitialiser_donnees(app, ex, "paul"))


def test_operation_concurrente_sur_la_meme_cible_refusee():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)

    async def deux():
        h = P.empreinte_utilisateur("claire")
        D._EN_COURS.add(("studio", h))
        try:
            await D.reinitialiser_donnees(app, ex, "claire")
        finally:
            D._EN_COURS.discard(("studio", h))
    with pytest.raises(D.RefusDonnees) as e:
        run(deux())
    assert "en cours" in e.value.message


def test_restituer_sans_paquet_404_et_paquet_id_explicite():
    ex, app = FauxExecuteur(), AppAEtat()
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
    assert e.value.statut == 404
    v = _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))
    assert run(D.restituer_donnees(app, ex, "claire", paquet_id=v["paquet_id"]))["etat"] == "restitue"
    with pytest.raises(D.RefusDonnees):             # paquet d'un autre utilisateur
        run(D.restituer_donnees(app, ex, "paul", paquet_id=v["paquet_id"]))


def test_restitution_conflit_de_l_app_remonte_en_409():
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)

    async def conflit(u, p):
        raise ContratErreur("x", 409, "conflit")
    app.importer = conflit
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire", paquet_id=v["paquet_id"]))
    assert e.value.statut == 409 and "conflit" in e.value.message


def test_restitution_dont_l_empreinte_diverge_est_signalee():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))

    async def importe_mal(u, p):
        app.donnees = {"series": 1, "profils": 0}
        return {"ok": True}
    app.importer = importe_mal
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
    assert "incomplète" in e.value.message


# --- hazards post-effacement (H1) / ambigu (H3) / verrou (H4) / messages (H5) ---

def _ctl_en_echec(app):
    """Le 2e export (contrôle final, après effacement) échoue ; le 1er passe."""
    reel = app.exporter
    app._exporter_reel = reel
    n = {"i": 0}

    async def exporter(u):
        n["i"] += 1
        if n["i"] >= 2:
            raise ContratErreur("x", 500, "erreur")
        return await reel(u)
    app.exporter = exporter


def test_controle_final_en_echec_apres_effacement_502_et_paquet_reste_restituable():
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    _ctl_en_echec(app)
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert e.value.statut == 502
    assert e.value.message == ("remise à zéro effectuée mais le contrôle final a échoué : vérifie "
                               f"l'état de l'application ; le paquet {v['paquet_id']} reste "
                               "restituable avec livraison_donnees_restituer (paquet_id)")
    assert app.donnees == {"series": 0, "profils": 0}
    assert P.lire(v["paquet_id"])["consomme_a"] is not None          # marqué AVANT le contrôle
    app.exporter = app._exporter_reel
    assert run(D.restituer_donnees(app, ex, "claire"))["etat"] == "restitue"


def test_marquer_consomme_en_oserror_apres_effacement_ne_change_pas_le_succes(monkeypatch):
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)

    def casse(*a, **k):
        raise OSError("registre illisible")
    monkeypatch.setattr(P, "marquer_consomme", casse)
    r = run(D.reinitialiser_donnees(app, ex, "claire"))
    assert r["etat"] == "reinitialise" and app.donnees == {"series": 0, "profils": 0}


def test_journal_en_oserror_apres_effacement_ne_change_pas_le_succes(monkeypatch):
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)

    def casse(*a, **k):
        raise OSError("disque plein")
    monkeypatch.setattr(P, "journaliser", casse)
    assert run(D.reinitialiser_donnees(app, ex, "claire"))["etat"] == "reinitialise"


def test_journal_en_oserror_sur_resurrection_laisse_le_refus_incomplet(monkeypatch):
    ex, app = FauxExecuteur(), AppAEtat(resurrection=True)
    _verifie(app, ex)
    monkeypatch.setattr(P, "journaliser", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert e.value.statut == 409 and "incomplet" in e.value.message


@pytest.mark.parametrize("exc", [ContratErreur("x", None, "delai")])
def test_reseau_pendant_reinitialiser_est_ambigu_504(exc):
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)

    async def coupe(u, emp):
        raise exc
    app.reinitialiser = coupe
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert e.value.statut == 504
    assert e.value.message.startswith(
        "l'application n'a pas répondu : la remise à zéro a peut-être été effectuée, vérifie avec "
        "livraison_donnees_verifier avant de réessayer ; le paquet ")
    assert e.value.message.endswith(" reste restituable avec livraison_donnees_restituer")


def test_empreinte_refusee_par_l_app_au_reset_est_409_donnees_changees():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)

    async def refuse(u, emp):
        raise ContratErreur("x", 409, "empreinte")
    app.reinitialiser = refuse
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert e.value.statut == 409 and "changé" in e.value.message


def test_refus_avant_effacement_dit_que_rien_n_a_ete_touche():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)

    async def casse(u):
        raise ContratErreur("x", None, "injoignable")
    app.exporter = casse
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert "intactes" in e.value.message and "reinitialiser" not in app.appels


def test_annulation_pendant_l_export_libere_le_verrou():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)
    h = P.empreinte_utilisateur("claire")

    async def scenario():
        bloque = asyncio.Event()

        async def lent(u):
            bloque.set()
            await asyncio.sleep(3600)
        app.exporter = lent
        t = asyncio.ensure_future(D.reinitialiser_donnees(app, ex, "claire"))
        await bloque.wait()
        assert ("studio", h) in D._EN_COURS
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
    run(scenario())
    assert ("studio", h) not in D._EN_COURS
    assert "reinitialiser" not in app.appels


def test_messages_ne_contiennent_ni_identite_ni_cle_ni_corps():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex, "claire.secret@exemple.fr")

    async def casse(u, emp):
        raise ContratErreur("corps={'token': 'SUPERSECRET'}", 500, "erreur")
    app.reinitialiser = casse
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire.secret@exemple.fr"))
    for interdit in ("claire", "SUPERSECRET", "token"):
        assert interdit not in e.value.message and interdit not in str(e.value)


def test_restitution_journal_en_oserror_ne_change_pas_le_succes(monkeypatch):
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))
    monkeypatch.setattr(P, "journaliser", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert run(D.restituer_donnees(app, ex, "claire"))["etat"] == "restitue"


# --- S248 3b fix : C2 (choix implicite), C1 (ambigu reset), I2 (ambigu restitution), M3, M4, M5 ---

def test_c2_resurrection_puis_reverification_restitution_implicite_refusee_explicite_redonne_l_original():
    ex, app = FauxExecuteur(), AppAEtat(resurrection=True)
    orig = _verifie(app, ex)
    with pytest.raises(D.RefusDonnees):
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert app.donnees == {"series": 1, "profils": 0}
    _verifie(app, ex)                                   # « relance la vérification »
    avant = app.appels.count("importer")
    with pytest.raises(D.RefusDonnees) as e:            # état partiel : ni vide ni identique
        run(D.restituer_donnees(app, ex, "claire"))
    assert e.value.statut == 409 and "ni vide ni identique" in e.value.message
    assert app.appels.count("importer") == avant
    back = run(D.restituer_donnees(app, ex, "claire", paquet_id=orig["paquet_id"]))
    assert back["paquet_id"] == orig["paquet_id"]
    assert back["comptages"] == {"series": 2, "profils": 1}
    assert P.lire(orig["paquet_id"])["restitue_a"] is not None


def test_c2_app_500_apres_effacement_reverification_puis_restitution_redonne_l_original():
    ex, app = FauxExecuteur(), AppAEtat()
    orig = _verifie(app, ex)
    vrai = app.reinitialiser

    async def efface_puis_500(u, emp):
        await vrai(u, emp)
        raise ContratErreur("x", 500, "erreur")
    app.reinitialiser = efface_puis_500
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert e.value.statut == 504 and orig["paquet_id"] in e.value.message
    assert app.donnees == {"series": 0, "profils": 0}
    _verifie(app, ex)                                   # paquet de l'état vide
    back = run(D.restituer_donnees(app, ex, "claire"))
    assert back["paquet_id"] == orig["paquet_id"] and app.donnees == {"series": 2, "profils": 1}


def test_c2_une_restitution_marque_le_paquet_et_la_seconde_ne_reimporte_pas_le_meme():
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))
    run(D.restituer_donnees(app, ex, "claire"))
    assert P.lire(v["paquet_id"])["restitue_a"] is not None
    app.donnees = {"series": 9, "profils": 9}           # données plus récentes
    avant = app.appels.count("importer")
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
    assert e.value.statut == 404 and app.appels.count("importer") == avant
    assert app.donnees == {"series": 9, "profils": 9}


def test_c2_marquer_restitue_en_oserror_ne_change_pas_le_succes(monkeypatch):
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    monkeypatch.setattr(P, "marquer_restitue", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert run(D.restituer_donnees(app, ex, "claire", paquet_id=v["paquet_id"]))["etat"] == "restitue"


def _reset_avec_erreur(exc, efface=True):
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    vrai = app.reinitialiser

    async def casse(u, emp):
        if efface:
            await vrai(u, emp)
        raise exc
    app.reinitialiser = casse
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    return ex, app, v, e.value


@pytest.mark.parametrize("exc", [ContratErreur("x", 500, "erreur"), ContratErreur("x", 502, "erreur"),
                                 ContratErreur("x", 503, "erreur"), ContratErreur("x", 200, "reponse"),
                                 ContratErreur("x", None, "erreur")])
def test_c1_reset_ambigu_5xx_ou_200_illisible_504_et_paquet_consomme(exc):
    ex, app, v, e = _reset_avec_erreur(exc)
    assert e.statut == 504
    assert e.message == ("l'application n'a pas répondu : la remise à zéro a peut-être été "
                         f"effectuée, vérifie avec livraison_donnees_verifier avant de réessayer ; "
                         f"le paquet {v['paquet_id']} reste restituable avec "
                         "livraison_donnees_restituer")
    assert P.lire(v["paquet_id"])["consomme_a"] is not None


@pytest.mark.parametrize("exc,statut", [(ContratErreur("x", 401, "cle_refusee"), 502),
                                        (ContratErreur("x", 404, "erreur"), 502),
                                        (ContratErreur("x", 413, "trop_gros"), 502),
                                        (ContratErreur("x", 503, "desactive"), 502),
                                        (ContratErreur("x", 422, "refus"), 409)])
def test_c1_refus_certain_avant_effet_reste_un_refus_non_consomme(exc, statut):
    ex, app, v, e = _reset_avec_erreur(exc, efface=False)
    assert e.statut == statut and "l'application refuse" in e.message
    assert P.lire(v["paquet_id"])["consomme_a"] is None


def test_c1_annulation_pendant_reinitialiser_marque_consomme_et_relance():
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)

    async def scenario():
        bloque = asyncio.Event()

        async def lent(u, emp):
            bloque.set()
            await asyncio.sleep(3600)
        app.reinitialiser = lent
        t = asyncio.ensure_future(D.reinitialiser_donnees(app, ex, "claire"))
        await bloque.wait()
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
    run(scenario())
    assert P.lire(v["paquet_id"])["consomme_a"] is not None
    assert ("studio", P.empreinte_utilisateur("claire")) not in D._EN_COURS


def _app_import(app, exc=None, avant=None):
    vrai = app.importer

    async def importer(u, p):
        r = await vrai(u, p) if avant else None
        if exc:
            raise exc
        return r
    app.importer = importer


@pytest.mark.parametrize("exc", [ContratErreur("x", 500, "erreur"), ContratErreur("x", 200, "reponse"),
                                 ContratErreur("x", None, "delai"), ContratErreur("x", 502, "erreur")])
def test_i2_import_ambigu_504(exc):
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    _app_import(app, exc)
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire", paquet_id=v["paquet_id"]))
    assert e.value.statut == 504
    assert e.value.message == ("l'application n'a pas répondu : la restitution a peut-être "
                               "été appliquée, vérifie l'état avant de réessayer")


def test_i2_import_ok_puis_controle_en_echec_502_applique():
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))

    async def exporter(u):
        raise ContratErreur("x", 500, "erreur")
    app.exporter = exporter
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire", paquet_id=v["paquet_id"]))
    assert e.value.statut == 502
    assert e.value.message == ("restitution appliquée mais le contrôle final a échoué : vérifie "
                               f"l'état de l'application ; le paquet {v['paquet_id']} reste "
                               "restituable avec livraison_donnees_restituer (paquet_id)")
    assert app.donnees == {"series": 2, "profils": 1}
    assert P.lire(v['paquet_id'])['restitue_a'] is None    # pas marqué : contrôle non concluant


def test_m3_restitution_504_reseau():
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    _app_import(app, ContratErreur("x", None, "delai"))
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire", paquet_id=v["paquet_id"]))
    assert e.value.statut == 504 and "peut-être" in e.value.message


def test_restitution_refus_certain_avant_effet_reste_un_refus():
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    _app_import(app, ContratErreur("x", 409, "conflit"))
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire", paquet_id=v["paquet_id"]))
    assert e.value.statut == 409 and "l'application refuse" in e.value.message


@pytest.mark.parametrize("val,attendu", [({}, False), (False, False), ({"a": 0}, True),
                                         ({"a": 0, "b": 0}, True), ({"a": False}, False),
                                         ({"a": 0, "b": 1}, False), ({"a": 0.0}, False),
                                         ({"a": None}, False)])
def test_m4_tout_a_zero_strict(val, attendu):
    assert D._tout_a_zero(val) is attendu


def test_m4_comptages_vides_apres_reset_ne_sont_pas_un_succes():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)
    reel = app.exporter
    n = {"i": 0}

    async def exporter(u):
        n["i"] += 1
        if n["i"] >= 2:
            return b"x", {"empreinte": "e", "comptages": {}}
        return await reel(u)
    app.exporter = exporter
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert e.value.statut == 409 and "incomplet" in e.value.message


# --- S248 3b fix 2 : restitution implicite non ambiguë, jamais d'écrasement silencieux ---

def _id(v):
    return v["paquet_id"]


def _import_appele(app):
    return "importer" in app.appels


def test_scen_a_resurrection_puis_verif_partielle_puis_reset_implicite_refuse_liste_a_et_b():
    ex, app = FauxExecuteur(), AppAEtat(resurrection=True)
    a = _verifie(app, ex)
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert e.value.statut == 409 and _id(a) in e.value.message      # (4) l'id du paquet est donné
    app.resurrection = False
    b = _verifie(app, ex)                                           # instantané partiel
    run(D.reinitialiser_donnees(app, ex, "claire"))
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
    assert e.value.statut == 409
    m = e.value.message
    assert m.startswith("plusieurs paquets sont candidats (") and m.endswith(") : précise paquet_id")
    assert set(m[len("plusieurs paquets sont candidats ("):-len(") : précise paquet_id")].split(", ")) \
        == {_id(a), _id(b)}
    assert not _import_appele(app)
    back = run(D.restituer_donnees(app, ex, "claire", paquet_id=_id(a)))
    assert back["paquet_id"] == _id(a) and app.donnees == {"series": 2, "profils": 1}


def test_scen_e_deux_resets_ambigus_restitution_implicite_refusee():
    ex, app = FauxExecuteur(), AppAEtat()
    a = _verifie(app, ex)
    vrai = app.reinitialiser

    async def efface_puis_500(u, emp):
        await vrai(u, emp)
        raise ContratErreur("x", 500, "erreur")
    app.reinitialiser = efface_puis_500
    with pytest.raises(D.RefusDonnees):
        run(D.reinitialiser_donnees(app, ex, "claire"))
    b = _verifie(app, ex)                                           # état vide
    with pytest.raises(D.RefusDonnees):
        run(D.reinitialiser_donnees(app, ex, "claire"))
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
    assert e.value.statut == 409 and _id(a) in e.value.message and _id(b) in e.value.message
    assert not _import_appele(app)
    assert run(D.restituer_donnees(app, ex, "claire", paquet_id=_id(a)))["etat"] == "restitue"
    assert app.donnees == {"series": 2, "profils": 1}


def test_scen6_donnees_nouvelles_apres_reset_restitution_implicite_refusee_explicite_ecrase():
    ex, app = FauxExecuteur(), AppAEtat()
    a = _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))
    app.donnees = {"series": 5, "profils": 3}                       # Claire a recréé des données
    _verifie(app, ex)
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
    assert e.value.statut == 409
    assert e.value.message == (f"l'état actuel de l'utilisateur n'est ni vide ni identique au paquet "
                               f"{_id(a)} : rien n'a été restitué ; précise paquet_id pour écraser "
                               "volontairement")
    assert not _import_appele(app) and app.donnees == {"series": 5, "profils": 3}
    back = run(D.restituer_donnees(app, ex, "claire", paquet_id=_id(a)))
    assert back["etat"] == "restitue" and app.donnees == {"series": 2, "profils": 1}


def test_restitution_implicite_apres_reset_normal_puis_seconde_404():
    ex, app = FauxExecuteur(), AppAEtat()
    a = _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))
    assert run(D.restituer_donnees(app, ex, "claire"))["paquet_id"] == _id(a)
    assert P.lire(_id(a))["restitue_a"] is not None
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
    assert e.value.statut == 404


def test_restitution_implicite_sans_candidat_message_fixe_meme_avec_un_verifie():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)                                               # vérifié mais jamais consommé
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
    assert e.value.statut == 404
    assert e.value.message == ("aucun paquet à restituer : aucune remise à zéro n'a consommé de "
                               "paquet pour cet utilisateur (précise paquet_id pour un paquet "
                               "vérifié)")
    assert not _import_appele(app)


def test_restitution_implicite_etat_identique_au_paquet_est_accepte():
    ex, app = FauxExecuteur(), AppAEtat()
    a = _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))
    app.donnees = {"series": 2, "profils": 1}                       # revenu à l'identique
    assert run(D.restituer_donnees(app, ex, "claire"))["paquet_id"] == _id(a)


def test_restitution_implicite_pre_export_en_echec_refus_avant_effet():
    ex, app = FauxExecuteur(), AppAEtat()
    a = _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))

    async def casse(u):
        raise ContratErreur("x", None, "delai")
    app.exporter = casse
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
    assert e.value.statut == 502 and "intactes" in e.value.message
    assert not _import_appele(app) and P.lire(_id(a))["restitue_a"] is None


def test_restitution_explicite_ne_fait_pas_de_pre_export():
    ex, app = FauxExecuteur(), AppAEtat()
    a = _verifie(app, ex)
    n = app.appels.count("exporter")
    run(D.restituer_donnees(app, ex, "claire", paquet_id=_id(a)))
    assert app.appels.count("exporter") == n + 1                    # seulement le contrôle final


@pytest.mark.parametrize("champ,val", [("expire_a", float("inf")), ("expire_a", "abc"),
                                       ("verifie_a", "abc"), ("verifie_a", float("nan")),
                                       ("verifie_a", 10 ** 12), ("verifie_a", None)])
def test_restitution_explicite_dates_illisibles_refusee_404(champ, val):
    import json
    ex, app = FauxExecuteur(), AppAEtat()
    a = _verifie(app, ex)
    f = P._dossier() / "paquets.json"
    tout = json.loads(f.read_text())
    tout[_id(a)][champ] = val
    f.write_text(json.dumps(tout))
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire", paquet_id=_id(a)))
    assert e.value.statut == 404 and not _import_appele(app)


@pytest.mark.parametrize("raison,texte", [("injoignable", "application injoignable : rien n'a été modifié"),
                                          ("identite", "identité non transmissible : rien n'a été modifié")])
def test_reset_injoignable_ou_identite_certain_avant_effet_502_non_consomme(raison, texte):
    ex, app, v, e = _reset_avec_erreur(ContratErreur("x", None, raison), efface=False)
    assert e.statut == 502 and e.message == texte
    assert P.lire(_id(v))["consomme_a"] is None


def test_reset_injoignable_puis_restitution_implicite_404_aucun_candidat():
    ex, app, v, e = _reset_avec_erreur(ContratErreur("x", None, "injoignable"), efface=False)
    app.donnees = {"series": 4, "profils": 4}                       # l'utilisateur continue
    with pytest.raises(D.RefusDonnees) as e2:
        run(D.restituer_donnees(app, ex, "claire"))
    assert e2.value.statut == 404 and not _import_appele(app)
    assert app.donnees == {"series": 4, "profils": 4}


@pytest.mark.parametrize("raison,texte", [("injoignable", "application injoignable : rien n'a été modifié"),
                                          ("identite", "identité non transmissible : rien n'a été modifié")])
def test_restitution_injoignable_ou_identite_certain_avant_effet_502(raison, texte):
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    _app_import(app, ContratErreur("x", None, raison))
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire", paquet_id=_id(v)))
    assert e.value.statut == 502 and e.value.message == texte
    assert P.lire(_id(v))["restitue_a"] is None


def test_reset_delai_reste_ambigu_504_et_consomme():
    ex, app, v, e = _reset_avec_erreur(ContratErreur("x", None, "delai"))
    assert e.statut == 504 and P.lire(_id(v))["consomme_a"] is not None


def test_tout_a_zero_exige_les_memes_cles():
    assert D._tout_a_zero({"a": 0, "b": 0}, {"a": 5, "b": 1}) is True
    assert D._tout_a_zero({"a": 0}, {"a": 5, "b": 1}) is False        # clé disparue
    assert D._tout_a_zero({"a": 0, "b": 0, "c": 0}, {"a": 5, "b": 1}) is False
    assert D._tout_a_zero({"a": 0}) is True                           # sans référence : inchangé


def test_reset_controle_qui_perd_une_cle_n_est_pas_un_succes():
    ex, app = FauxExecuteur(), AppAEtat()
    v = _verifie(app, ex)
    reel = app.exporter
    n = {"i": 0}

    async def exporter(u):
        n["i"] += 1
        if n["i"] >= 2:
            return b"x", {"empreinte": "e", "comptages": {"series": 0}}   # « profils » a disparu
        return await reel(u)
    app.exporter = exporter
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert e.value.statut == 409 and "incomplet" in e.value.message and _id(v) in e.value.message


def test_reset_resurrection_message_donne_l_id_du_paquet():
    ex, app = FauxExecuteur(), AppAEtat(resurrection=True)
    v = _verifie(app, ex)
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert f"le paquet {_id(v)} reste restituable avec livraison_donnees_restituer" in e.value.message
