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
    with pytest.raises(D.RefusDonnees):
        run(D.reinitialiser_donnees(app, ex, "claire", maintenant=1000.0 + 6 * 3600 + 1))


def test_un_paquet_ne_sert_qu_a_un_reset():
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)
    run(D.reinitialiser_donnees(app, ex, "claire"))
    with pytest.raises(D.RefusDonnees):
        run(D.reinitialiser_donnees(app, ex, "claire"))


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
    _verifie(app, ex)

    async def conflit(u, p):
        raise ContratErreur("x", 409, "conflit")
    app.importer = conflit
    with pytest.raises(D.RefusDonnees) as e:
        run(D.restituer_donnees(app, ex, "claire"))
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
                               "l'état de l'application (le paquet reste restituable)")
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


@pytest.mark.parametrize("exc", [ContratErreur("x", None, "injoignable"),
                                 ContratErreur("x", None, "delai")])
def test_reseau_pendant_reinitialiser_est_ambigu_504(exc):
    ex, app = FauxExecuteur(), AppAEtat()
    _verifie(app, ex)

    async def coupe(u, emp):
        raise exc
    app.reinitialiser = coupe
    with pytest.raises(D.RefusDonnees) as e:
        run(D.reinitialiser_donnees(app, ex, "claire"))
    assert e.value.statut == 504
    assert e.value.message == ("l'application n'a pas répondu : la remise à zéro a peut-être été "
                               "effectuée, vérifie avec livraison_donnees_verifier avant de réessayer")


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
