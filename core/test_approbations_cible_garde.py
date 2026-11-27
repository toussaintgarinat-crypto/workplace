"""Câblage S248 3b : la preuve par cible vient du RÉSULTAT de la brique, la clé des arguments."""
import asyncio
import json
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("GATEWAY_KEY", "sk-test-local")
sys.path.insert(0, os.path.dirname(__file__))

import pytest  # noqa: E402

import approbations  # noqa: E402
import outils  # noqa: E402


class _Reg:
    def __init__(self, briques):
        self.briques = briques


PARAMS = {"app": {"type": "string", "requis": True}, "utilisateur": {"type": "string", "requis": True}}
REGISTRE = _Reg({"livraison": {"nom": "livraison", "port": 6240, "capacites": [
    {"nom": "livraison_donnees_verifier", "chemin": "/v", "methode": "POST", "action": False,
     "fournit_preuve": "paquet_verifie", "description": "Vérifie.", "params": PARAMS},
    {"nom": "livraison_donnees_reinitialiser", "chemin": "/r", "methode": "POST", "action": True,
     "sensibilite": "donnees", "prerequis": ["paquet_verifie"], "description": "Reset.",
     "params": PARAMS},
]}})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()
    etat = {"notifs": [], "resultat_verif": None, "executes": []}

    async def faux_notifier(registre, demande):
        etat["notifs"].append((demande["id"], dict(demande["prerequis"])))

    async def faux_executer(nom, args, registre):
        if nom == "livraison_donnees_verifier":
            return etat["resultat_verif"]
        etat["executes"].append((nom, args.get("utilisateur")))
        return '{"ok": true}'

    monkeypatch.setattr(outils, "_notifier_approbation", faux_notifier)
    monkeypatch.setattr(outils, "_executer", faux_executer)
    return etat


def _run(nom, args):
    return asyncio.run(outils.executer(nom, args, REGISTRE))


def _verdict(**kw):
    d = {"ok": True, "verdict": "valide", "preuve_id": "P1", "paquet_id": "P1",
         "expire_a": 4_000_000_000.0}
    d.update(kw)
    return json.dumps(d)


def test_verdict_valide_pour_claire_libere_la_demande_de_claire_seulement(env):
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "claire"})
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "paul"})
    env["resultat_verif"] = _verdict()
    _run("livraison_donnees_verifier", {"app": "studio", "utilisateur": "claire"})
    derniers = {n[0]: n[1] for n in env["notifs"]}
    assert list(derniers.values()).count({"paquet_verifie": True}) == 1
    assert env["notifs"][-1][1] == {"paquet_verifie": True}


def test_verdict_qui_pretend_viser_une_autre_app_ou_cible_est_ignore(env):
    """Un résultat portant `app`/`app_id` ne peut pas déplacer la preuve ailleurs que les ARGUMENTS."""
    env["resultat_verif"] = _verdict(app="calendrier", app_id="A9", utilisateur="paul")
    _run("livraison_donnees_verifier", {"app": "studio", "utilisateur": "claire"})
    _run("livraison_donnees_reinitialiser", {"app": "calendrier", "utilisateur": "claire"})
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "paul"})
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "claire"})
    assert [n[1] for n in env["notifs"]] == [{"paquet_verifie": False}, {"paquet_verifie": False},
                                             {"paquet_verifie": True}]


def test_verdict_invalide_revoque_la_preuve_de_la_cible(env):
    env["resultat_verif"] = _verdict()
    _run("livraison_donnees_verifier", {"app": "studio", "utilisateur": "claire"})
    env["resultat_verif"] = _verdict(verdict="invalide", preuve_id="P2")
    _run("livraison_donnees_verifier", {"app": "studio", "utilisateur": "claire"})
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "claire"})
    assert env["notifs"][-1][1] == {"paquet_verifie": False}


def test_args_sans_utilisateur_n_enregistre_aucune_preuve(env):
    env["resultat_verif"] = _verdict()
    _run("livraison_donnees_verifier", {"app": "studio"})
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "claire"})
    assert env["notifs"][-1][1] == {"paquet_verifie": False}


def test_execution_apres_approbation_pour_la_bonne_cible_seulement(env):
    env["resultat_verif"] = _verdict()
    _run("livraison_donnees_verifier", {"app": "studio", "utilisateur": "claire"})
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "claire"})
    id_ = env["notifs"][-1][0]
    assert approbations.approuver(id_, "perso", "app", utilisateur="perso") == (True, "ok")
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "claire"})
    assert env["executes"] == [("livraison_donnees_reinitialiser", "claire")]


def test_verdict_plus_recent_avec_autre_app_id_ne_donne_pas_de_preuve_a_paul(env):
    """L'app_id du résultat ne doit jamais devenir l'alias partagé par tous les utilisateurs."""
    env["resultat_verif"] = _verdict(app_id="A1")
    _run("livraison_donnees_verifier", {"app": "studio", "utilisateur": "claire"})
    env["resultat_verif"] = _verdict(app_id="A2", preuve_id="P2", expire_a=4_100_000_000.0)
    _run("livraison_donnees_verifier", {"app": "studio", "utilisateur": "claire"})
    _run("livraison_donnees_reinitialiser", {"app": "A1", "utilisateur": "paul"})
    _run("livraison_donnees_reinitialiser", {"app": "A2", "utilisateur": "paul"})
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "paul"})
    assert [n[1] for n in env["notifs"]] == [{"paquet_verifie": False}] * 3
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "claire"})
    assert env["notifs"][-1][1] == {"paquet_verifie": True}


def test_alias_app_id_du_resultat_ne_partage_pas_la_preuve_entre_utilisateurs(env):
    """Un verdict `app_id` identique pour deux utilisateurs ne doit pas mélanger leurs preuves."""
    env["resultat_verif"] = _verdict(verdict="invalide", preuve_id="P0", app_id="A1")
    _run("livraison_donnees_verifier", {"app": "studio", "utilisateur": "paul"})
    env["resultat_verif"] = _verdict(verdict="valide", app_id="A1")
    _run("livraison_donnees_verifier", {"app": "studio", "utilisateur": "claire"})
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "paul"})
    assert env["notifs"][-1][1] == {"paquet_verifie": False}
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "claire"})
    assert env["notifs"][-1][1] == {"paquet_verifie": True}


def test_verdict_forgeant_la_cle_composite_d_un_autre_est_ignore(env):
    """Un verdict dont `app`/`app_id` valent la clé composite de Paul ne lui donne aucune preuve."""
    cle_paul = approbations.cle_preuve("paquet_verifie", {"app": "studio", "utilisateur": "paul"})
    env["resultat_verif"] = _verdict(app=cle_paul, app_id=cle_paul)
    _run("livraison_donnees_verifier", {"app": "studio", "utilisateur": "claire"})
    _run("livraison_donnees_reinitialiser", {"app": "studio", "utilisateur": "paul"})
    assert env["notifs"][-1][1] == {"paquet_verifie": False}


# --- Vérificateur LUI-MÊME soumis à approbation (sensibilite reversible + fournit_preuve) ---------
import approbations_canal  # noqa: E402
import approbations_reprise  # noqa: E402
import contexte_tenant  # noqa: E402

REGISTRE_VERIF_GARDE = _Reg({"livraison": {"nom": "livraison", "port": 6240, "capacites": [
    {"nom": "livraison_donnees_verifier", "chemin": "/v", "methode": "POST", "action": True,
     "sensibilite": "reversible", "fournit_preuve": "paquet_verifie", "description": "Vérifie.",
     "params": PARAMS},
    REGISTRE.briques["livraison"]["capacites"][1],
]}})
ARGS_CLAIRE = {"app": "studio", "utilisateur": "claire"}
ARGS_PAUL = {"app": "studio", "utilisateur": "paul"}


@pytest.fixture
def env_garde(env, monkeypatch):
    """Comme `env`, mais le vérificateur passe par la garde ; trace aussi l'identité du contexte."""
    env["verifs"] = []                      # (utilisateur de ARGS, utilisateur du CONTEXTE)

    async def faux_executer(nom, args, registre):
        if nom == "livraison_donnees_verifier":
            env["verifs"].append((args.get("utilisateur"), contexte_tenant.contexte_actuel().utilisateur))
            return env["resultat_verif"]
        env["executes"].append((nom, args.get("utilisateur")))
        return '{"ok": true}'

    async def faux_maj(registre, demande):
        return None

    monkeypatch.setattr(outils, "_executer", faux_executer)
    monkeypatch.setattr(approbations_canal, "mettre_a_jour", faux_maj)
    return env


def _run_g(nom, args, ctx="claire"):
    jetons = contexte_tenant.definir_contexte(utilisateur=ctx)
    try:
        return asyncio.run(outils.executer(nom, args, REGISTRE_VERIF_GARDE))
    finally:
        contexte_tenant.reinitialiser(jetons)


def _etat_resets(env):
    """Dernière preuve notifiée du reset de chaque cible : {}"""
    return [n[1] for n in env["notifs"]]


def test_verificateur_gate_n_execute_ni_ne_prouve_avant_approbation(env_garde):
    _run_g("livraison_donnees_reinitialiser", ARGS_CLAIRE)
    _run_g("livraison_donnees_reinitialiser", ARGS_PAUL, ctx="paul")
    env_garde["resultat_verif"] = _verdict()
    _run_g("livraison_donnees_verifier", ARGS_CLAIRE)
    assert env_garde["verifs"] == []                              # pas exécuté
    # une demande par reset + une pour le vérificateur ; aucune libération de reset
    assert _etat_resets(env_garde) == [{"paquet_verifie": False}, {"paquet_verifie": False}, {}]
    id_verif = env_garde["notifs"][-1][0]
    assert approbations.lire(id_verif)["statut"] == "en_attente"
    _run_g("livraison_donnees_reinitialiser", ARGS_CLAIRE)        # redemande : toujours sans preuve
    assert env_garde["executes"] == []


def _verifier_approuve(env, args, ctx):
    """Demande, approuve, puis rejoue par le VRAI chemin `approbations_reprise.reprendre`."""
    n0 = len(env["notifs"])
    _run_g("livraison_donnees_verifier", args, ctx=ctx)
    id_ = env["notifs"][n0][0]                     # la demande du vérificateur lui-même
    assert approbations.approuver(id_, ctx, "app", utilisateur=ctx) == (True, "ok")
    res = asyncio.run(approbations_reprise.reprendre(REGISTRE_VERIF_GARDE, id_))
    return id_, res


def test_verificateur_approuve_enregistre_la_preuve_du_demandeur_seulement(env_garde):
    _run_g("livraison_donnees_reinitialiser", ARGS_CLAIRE)
    _run_g("livraison_donnees_reinitialiser", ARGS_PAUL, ctx="paul")
    ids_reset = [n[0] for n in env_garde["notifs"]]
    env_garde["resultat_verif"] = _verdict()
    _id, res = _verifier_approuve(env_garde, ARGS_CLAIRE, "claire")
    assert res == "executee"
    # le vérificateur a tourné UNE fois, dans le contexte du demandeur
    assert env_garde["verifs"] == [("claire", "claire")]
    # la demande de reset de Claire est libérée (renotifiée avec la preuve), pas celle de Paul
    assert (ids_reset[0], {"paquet_verifie": True}) in [(n[0], n[1]) for n in env_garde["notifs"]]
    assert not any(n[0] == ids_reset[1] and n[1] == {"paquet_verifie": True}
                   for n in env_garde["notifs"])
    assert approbations.lire(ids_reset[1])["prerequis"] == {"paquet_verifie": False}
    assert approbations.lire(ids_reset[0])["prerequis"] == {"paquet_verifie": True}


def test_verificateur_approuve_verdict_invalide_revoque_la_preuve(env_garde, monkeypatch):
    monkeypatch.setattr(approbations, "DELAI_APRES_EXECUTION_S", 0)   # 2e cycle humain immédiat
    env_garde["resultat_verif"] = _verdict()
    _verifier_approuve(env_garde, ARGS_CLAIRE, "claire")
    _run_g("livraison_donnees_reinitialiser", ARGS_CLAIRE)
    id_reset = env_garde["notifs"][-1][0]
    assert approbations.lire(id_reset)["prerequis"] == {"paquet_verifie": True}   # preuve posée d'abord
    env_garde["resultat_verif"] = _verdict(verdict="invalide", preuve_id="P2")
    _id, res = _verifier_approuve(env_garde, ARGS_CLAIRE, "claire")
    assert res == "executee"
    assert approbations.lire(id_reset)["prerequis"] == {"paquet_verifie": False}   # révoquée
