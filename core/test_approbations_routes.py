"""S245 — routes /approbations du Cœur (clé partagée fail-closed, session pour la liste).

$ cd core && python3 -m pytest test_approbations_routes.py -v
"""
import json
import os
import tempfile
import time

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import approbations  # noqa: E402
import approbations_canal  # noqa: E402
import auth  # noqa: E402
import main  # noqa: E402
import session_registre  # noqa: E402

CLE = "cle-test-approbations"
ENT = {"X-Approbations-Cle": CLE}
BEARER = {"Authorization": f"Bearer {CLE}"}
INCONNU = "0" * 32
U = "marina"   # sub de la fixture `session` : les demandes de test lui appartiennent


@pytest.fixture(autouse=True)
def _isoler(monkeypatch, tmp_path):
    monkeypatch.setattr(approbations, "DB", str(tmp_path / "a.db"))
    approbations.init_db()
    monkeypatch.setattr(session_registre, "DB", os.path.join(tempfile.mkdtemp(), "sr.db"))
    auth._cache_access_token.clear()
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv("APPROBATIONS_CLE", CLE)
    # TTL longs : les tests de relance fabriquent des demandes vieilles de quelques heures.
    monkeypatch.setenv("APPROBATION_TTL_REVERSIBLE_MIN", "1440")
    monkeypatch.setenv("APPROBATION_TTL_DESTRUCTIF_MIN", "1440")
    monkeypatch.delenv("APPROBATION_RELANCE_MIN", raising=False)
    monkeypatch.delenv("APPROBATION_RELANCE_MAX", raising=False)
    appels = {"notifier": [], "maj": []}

    async def _notifier(registre, demande, relance=False):
        appels["notifier"].append((dict(demande), relance))

    async def _maj(registre, demande):
        appels["maj"].append(dict(demande))

    monkeypatch.setattr(approbations_canal, "notifier", _notifier)
    monkeypatch.setattr(approbations_canal, "mettre_a_jour", _maj)
    # La reprise (Task 6) est testée à part : ici le registre n'a pas la capacité, la reprise
    # réelle abandonnerait les demandes de test.
    import approbations_reprise
    monkeypatch.setattr(approbations_reprise, "lancer", lambda registre, id_: None)
    yield appels
    auth._cache_access_token.clear()


@pytest.fixture
def appels(_isoler):
    return _isoler


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def client_sans_cle(monkeypatch):
    monkeypatch.delenv("APPROBATIONS_CLE", raising=False)
    return TestClient(main.app)


@pytest.fixture
def client_sans_session():
    return TestClient(main.app)


@pytest.fixture
def session():
    auth._cache_access_token["marina"] = ("at-cache", time.time() + 60)
    return {auth.COOKIE_SESSION: auth.chiffrer_cookie({"sub": "marina", "refresh_token": "rt-1"})}


@pytest.fixture
def demande():
    return approbations.creer("app_redemarrer", {"app": "crm"}, "r", "reversible",
                             utilisateur=U)


@pytest.fixture
def demande_destructive():
    return approbations.creer("app_supprimer", {"app": "crm"}, "d", "destructif",
                             utilisateur=U)


def _decision(client, id_, decision="ok", headers=ENT, par="tg:42"):
    return client.post(f"/approbations/{id_}/decision", headers=headers,
                       json={"decision": decision, "par": par, "canal": "telegram", "utilisateur": U})


# ── Décision ────────────────────────────────────────────────────────────────

def test_decision_sans_cle_ou_mauvaise_cle_401(client, demande):
    corps = {"decision": "ok", "par": "tg:42", "canal": "telegram", "utilisateur": U}
    assert client.post(f"/approbations/{demande['id']}/decision", json=corps).status_code == 401
    assert client.post(f"/approbations/{demande['id']}/decision",
                       headers={"X-Approbations-Cle": "x"}, json=corps).status_code == 401
    assert approbations.lire(demande["id"])["statut"] == "en_attente"


def test_decision_fail_closed_si_cle_non_configuree(client_sans_cle, demande):
    r = client_sans_cle.post(f"/approbations/{demande['id']}/decision", headers=ENT,
                             json={"decision": "ok", "par": "tg:42", "canal": "telegram", "utilisateur": U})
    assert r.status_code == 503
    assert approbations.lire(demande["id"])["statut"] == "en_attente"


def test_decision_cle_vide_envoyee_avec_cle_non_configuree_503(client_sans_cle, demande):
    r = client_sans_cle.post(f"/approbations/{demande['id']}/decision",
                             headers={"X-Approbations-Cle": ""},
                             json={"decision": "ok", "par": "tg:42", "canal": "telegram", "utilisateur": U})
    assert r.status_code == 503


def test_decision_ok_approuve(client, demande, appels):
    r = _decision(client, demande["id"], "ok")
    assert r.json() == {"ok": True, "raison": "ok", "statut": "approuvee",
                        "sensibilite": "reversible"}
    assert approbations.lire(demande["id"])["statut"] == "approuvee"
    assert len(appels["maj"]) == 1 and appels["maj"][0]["id"] == demande["id"]


def test_decision_ko_refuse(client, demande):
    r = _decision(client, demande["id"], "ko")
    assert r.json() == {"ok": True, "raison": "ok", "statut": "refusee",
                        "sensibilite": "reversible"}
    assert approbations.lire(demande["id"])["statut"] == "refusee"


def test_decision_valeur_invalide_422(client, demande):
    r = _decision(client, demande["id"], "peut-etre")
    assert r.status_code == 422
    assert approbations.lire(demande["id"])["statut"] == "en_attente"


def test_decision_id_forge_422_et_inconnu_introuvable(client):
    for mauvais in ("abc", "../etc", "Z" * 32, "A" * 32, "0" * 31, "0" * 33):
        assert _decision(client, mauvais).status_code in (404, 422), mauvais
    assert _decision(client, "abc").status_code == 422
    assert _decision(client, "G" * 32).status_code == 422
    assert _decision(client, "0" * 31).status_code == 422
    r = _decision(client, INCONNU)
    assert r.status_code == 200
    assert r.json() == {"ok": False, "raison": "introuvable", "statut": None,
                        "sensibilite": None}


def test_id_invalide_rejete_422_sur_toutes_les_routes_a_id(client):
    r = client.post("/approbations/pas-un-id/code/armer", headers=ENT, json={"par": "tg:42", "utilisateur": U})
    assert r.status_code == 422


def test_decision_deja_decidee(client, demande):
    assert _decision(client, demande["id"], "ok").json()["ok"] is True
    r = _decision(client, demande["id"], "ko")
    assert r.json()["ok"] is False and r.json()["raison"] == "deja_decidee"
    assert approbations.lire(demande["id"])["statut"] == "approuvee"


def test_decision_destructif_renvoie_code_requis(client, demande_destructive):
    r = _decision(client, demande_destructive["id"], "ok")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "raison": "code_requis", "statut": "en_attente",
                        "sensibilite": "destructif"}
    assert approbations.lire(demande_destructive["id"])["statut"] == "en_attente"


def test_decision_destructif_ko_par_bouton_refuse(client, demande_destructive):
    r = _decision(client, demande_destructive["id"], "ko")
    assert r.json()["ok"] is True and r.json()["statut"] == "refusee"


def test_reponses_des_routes_a_cle_ne_contiennent_jamais_le_code(client, demande_destructive):
    code = demande_destructive["code"]
    assert code and len(code) == 6
    id_ = demande_destructive["id"]
    brut = [
        _decision(client, id_, "ok").text,
        client.post(f"/approbations/{id_}/code/armer", headers=ENT, json={"par": "tg:42", "utilisateur": U}).text,
        client.post("/approbations/code", headers=ENT, json={"par": "tg:42", "code": "000000", "utilisateur": U}).text,
        client.post("/approbations/relancer", headers=ENT).text,
    ]
    for texte in brut:
        assert code not in texte


# ── Code destructif ─────────────────────────────────────────────────────────

def test_code_armer_puis_code_valide_approuve(client, demande_destructive, appels):
    id_ = demande_destructive["id"]
    r = client.post(f"/approbations/{id_}/code/armer", headers=ENT, json={"par": "tg:42", "utilisateur": U})
    assert r.json() == {"ok": True, "raison": "ok"}
    r = client.post("/approbations/code", headers=ENT,
                    json={"par": "tg:42", "code": demande_destructive["code"], "utilisateur": U})
    assert r.json() == {"pris_en_charge": True, "ok": True, "raison": "ok",
                        "approbation_id": id_, "restants": 0}
    assert approbations.lire(id_)["statut"] == "approuvee"
    assert len(appels["maj"]) == 1


def test_code_armer_sur_non_destructif(client, demande):
    r = client.post(f"/approbations/{demande['id']}/code/armer", headers=ENT, json={"par": "tg:42", "utilisateur": U})
    assert r.json() == {"ok": False, "raison": "pas_destructif"}


def test_code_armer_et_code_exigent_la_cle(client, demande_destructive):
    id_ = demande_destructive["id"]
    assert client.post(f"/approbations/{id_}/code/armer", json={"par": "tg:42", "utilisateur": U}).status_code == 401
    assert client.post("/approbations/code", json={"par": "tg:42", "code": "1", "utilisateur": U}).status_code == 401


def test_code_armer_et_code_fail_closed_si_cle_non_configuree(client_sans_cle, demande_destructive):
    id_ = demande_destructive["id"]
    assert client_sans_cle.post(f"/approbations/{id_}/code/armer", headers=ENT,
                                json={"par": "tg:42", "utilisateur": U}).status_code == 503
    assert client_sans_cle.post("/approbations/code", headers=ENT,
                                json={"par": "tg:42", "code": "1", "utilisateur": U}).status_code == 503


def test_code_sans_saisie_armee_pris_en_charge_false(client):
    r = client.post("/approbations/code", headers=ENT, json={"par": "tg:42", "code": "123456", "utilisateur": U})
    assert r.status_code == 200 and r.json() == {"pris_en_charge": False}


def test_code_faux_decremente_restants(client, demande_destructive):
    id_ = demande_destructive["id"]
    client.post(f"/approbations/{id_}/code/armer", headers=ENT, json={"par": "tg:42", "utilisateur": U})
    faux = "000000" if demande_destructive["code"] != "000000" else "111111"
    r = client.post("/approbations/code", headers=ENT, json={"par": "tg:42", "code": faux, "utilisateur": U})
    j = r.json()
    assert j["pris_en_charge"] is True and j["ok"] is False
    assert j["approbation_id"] == id_
    assert j["restants"] == approbations.ESSAIS_CODE_MAX - 1
    assert approbations.lire(id_)["statut"] == "en_attente"
    assert approbations.lire(id_)["essais"] == 1


def test_code_non_ascii_ne_plante_pas(client, demande_destructive):
    id_ = demande_destructive["id"]
    client.post(f"/approbations/{id_}/code/armer", headers=ENT, json={"par": "tg:42", "utilisateur": U})
    r = client.post("/approbations/code", headers=ENT, json={"par": "tg:42", "code": "١٢٣٤٥٦", "utilisateur": U})
    assert r.status_code == 200 and r.json()["ok"] is False


# ── Liste (session) ─────────────────────────────────────────────────────────

def test_en_attente_sans_session_401(client_sans_session, demande_destructive):
    r = client_sans_session.get("/approbations/en_attente")
    assert r.status_code == 401
    assert demande_destructive["code"] not in r.text


def test_en_attente_avec_la_cle_mais_sans_session_refuse(client_sans_session, demande_destructive):
    r = client_sans_session.get("/approbations/en_attente", headers=ENT)
    assert r.status_code == 401


def test_en_attente_exige_session_et_expose_le_code_destructif(
        client, client_sans_session, demande_destructive, demande, session):
    assert client_sans_session.get("/approbations/en_attente").status_code == 401
    r = client.get("/approbations/en_attente", cookies=session)
    assert r.status_code == 200
    par_id = {a["id"]: a for a in r.json()["approbations"]}
    assert set(par_id) == {demande["id"], demande_destructive["id"]}
    assert par_id[demande_destructive["id"]]["code"] == demande_destructive["code"]
    assert par_id[demande["id"]]["code"] is None


def test_en_attente_ne_liste_pas_les_decidees(client, demande, session):
    _decision(client, demande["id"], "ko")
    r = client.get("/approbations/en_attente", cookies=session)
    assert r.status_code == 200 and r.json() == {"approbations": []}


# ── Relance ─────────────────────────────────────────────────────────────────

def test_relancer_sans_cle_ou_mauvaise_cle_401(client):
    assert client.post("/approbations/relancer").status_code == 401
    assert client.post("/approbations/relancer", headers={"X-Approbations-Cle": "x"}).status_code == 401
    assert client.post("/approbations/relancer", headers={"Authorization": "Bearer x"}).status_code == 401


def test_relancer_fail_closed_si_cle_non_configuree_503(client_sans_cle):
    assert client_sans_cle.post("/approbations/relancer", headers=ENT).status_code == 503
    assert client_sans_cle.post("/approbations/relancer", headers=BEARER).status_code == 503
    assert client_sans_cle.post("/approbations/relancer").status_code == 503


def test_relancer_accepte_la_cle_en_bearer_pour_l_horloge(client):
    # L'horloge ne sait poser que `Authorization: Bearer <env>` (entete_token_env).
    r = client.post("/approbations/relancer", headers=BEARER)
    assert r.status_code == 200 and r.json() == {"expirees": [], "relancees": [], "reprises": []}


def test_relancer_expire_les_perimees_et_relance_les_anciennes(client, monkeypatch, appels):
    vieille = approbations.creer("app_redemarrer", {"app": "vieille"}, "v", "reversible",
                                 maintenant=time.time() - 2 * 3600)
    perimee = approbations.creer("app_redemarrer", {"app": "perimee"}, "p", "reversible",
                                 maintenant=time.time() - 10 * 86400)
    fraiche = approbations.creer("app_redemarrer", {"app": "fraiche"}, "f", "reversible")
    r = client.post("/approbations/relancer", headers=ENT)
    assert r.status_code == 200
    j = r.json()
    assert j["expirees"] == [perimee["id"]]
    assert j["relancees"] == [vieille["id"]]
    assert approbations.lire(perimee["id"])["statut"] == "expiree"
    assert approbations.lire(vieille["id"])["nb_relances"] == 1
    assert approbations.lire(fraiche["id"])["nb_relances"] == 0
    assert [(d["id"], rel) for d, rel in appels["notifier"]] == [(vieille["id"], True)]
    assert [d["id"] for d in appels["maj"]] == [perimee["id"]]
    assert appels["maj"][0]["statut"] == "expiree"


def test_relancer_respecte_le_maximum(client, monkeypatch, appels):
    monkeypatch.setenv("APPROBATION_RELANCE_MAX", "1")
    monkeypatch.setenv("APPROBATION_RELANCE_MIN", "1")
    d = approbations.creer("app_redemarrer", {"app": "x"}, "x", "reversible",
                           maintenant=time.time() - 3600)
    assert client.post("/approbations/relancer", headers=ENT).json()["relancees"] == [d["id"]]
    # la 2e relance dépasse le maximum de 1
    approbations.marquer_relancee(d["id"], maintenant=time.time() - 3600)
    assert client.post("/approbations/relancer", headers=ENT).json()["relancees"] == []


def test_notification_envoyee_au_canal_ne_contient_jamais_le_code(
        client, appels, demande_destructive):
    d = approbations.creer("app_supprimer", {"app": "vieux"}, "v", "destructif",
                           maintenant=time.time() - 2 * 3600)
    assert d["code"]
    r = client.post("/approbations/relancer", headers=ENT)
    assert d["id"] in r.json()["relancees"]
    assert d["code"] not in r.text and demande_destructive["code"] not in r.text
    assert appels["notifier"], "la relance doit être transmise au canal"
    for demande, relance in appels["notifier"]:
        assert relance is True
        assert "code" not in demande
        assert d["code"] not in json.dumps(demande, default=str)


def test_mise_a_jour_envoyee_au_canal_ne_contient_jamais_le_code(
        client, appels, demande_destructive):
    id_ = demande_destructive["id"]
    _decision(client, id_, "ko")
    client.post(f"/approbations/{id_}/code/armer", headers=ENT, json={"par": "tg:42", "utilisateur": U})
    client.post("/approbations/code", headers=ENT, json={"par": "tg:42", "code": "000000", "utilisateur": U})
    assert appels["maj"]
    for demande in appels["maj"]:
        assert "code" not in demande
        assert demande_destructive["code"] not in json.dumps(demande, default=str)


# ── Canal best-effort / relance / env tolérant ─────────────────────────────

@pytest.fixture
def canal_en_panne(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("connexion down")
    monkeypatch.setattr(approbations_canal, "notifier", _boom)
    monkeypatch.setattr(approbations_canal, "mettre_a_jour", _boom)


def test_decision_survit_a_une_panne_du_canal(client, demande, canal_en_panne):
    r = _decision(client, demande["id"], "ok")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "raison": "ok", "statut": "approuvee",
                        "sensibilite": "reversible"}
    assert approbations.lire(demande["id"])["statut"] == "approuvee"


def test_code_survit_a_une_panne_du_canal(client, demande_destructive, canal_en_panne):
    id_ = demande_destructive["id"]
    client.post(f"/approbations/{id_}/code/armer", headers=ENT, json={"par": "tg:42", "utilisateur": U})
    r = client.post("/approbations/code", headers=ENT,
                    json={"par": "tg:42", "code": demande_destructive["code"], "utilisateur": U})
    assert r.status_code == 200
    assert r.json()["pris_en_charge"] is True and r.json()["ok"] is True
    assert approbations.lire(id_)["statut"] == "approuvee"


def test_relancer_continue_malgre_un_notifier_qui_leve(client, monkeypatch, appels):
    a = approbations.creer("app_redemarrer", {"app": "a"}, "a", "reversible",
                           maintenant=time.time() - 3 * 3600)
    b = approbations.creer("app_redemarrer", {"app": "b"}, "b", "reversible",
                           maintenant=time.time() - 2 * 3600)
    vus = []

    async def _notifier(registre, demande, relance=False):
        vus.append(demande["id"])
        if len(vus) == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(approbations_canal, "notifier", _notifier)
    r = client.post("/approbations/relancer", headers=ENT)
    assert r.status_code == 200
    assert sorted(r.json()["relancees"]) == sorted([a["id"], b["id"]])
    assert len(vus) == 2


def test_relancer_marque_avant_de_notifier(client, monkeypatch, appels):
    d = approbations.creer("app_redemarrer", {"app": "x"}, "x", "reversible",
                           maintenant=time.time() - 2 * 3600)

    async def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(approbations_canal, "notifier", _boom)
    assert client.post("/approbations/relancer", headers=ENT).json()["relancees"] == [d["id"]]
    assert approbations.lire(d["id"])["nb_relances"] == 1
    assert client.post("/approbations/relancer", headers=ENT).json()["relancees"] == []
    assert approbations.lire(d["id"])["nb_relances"] == 1


def test_relancer_env_malforme_retombe_sur_les_defauts(client, monkeypatch, appels):
    monkeypatch.setenv("APPROBATION_RELANCE_MIN", "abc")
    monkeypatch.setenv("APPROBATION_RELANCE_MAX", "")
    d = approbations.creer("app_redemarrer", {"app": "x"}, "x", "reversible",
                           maintenant=time.time() - 2 * 3600)
    r = client.post("/approbations/relancer", headers=ENT)
    assert r.status_code == 200
    assert r.json()["relancees"] == [d["id"]]


# ── Mode attente : tâche d'horloge (Task 7) ──────────────────────────────────

def _tache_relance():
    import pathlib
    m = json.loads((pathlib.Path(__file__).parents[1] / "briques/noyau/manifest.json").read_text())
    return {x["nom"]: x for x in m["taches"]}["approbations-relance"]


def test_le_manifeste_noyau_declare_la_tache_de_relance():
    t = _tache_relance()
    assert t["methode"] == "POST" and t["chemin"] == "/approbations/relancer"
    assert t["cadence_heures"] <= 0.25          # l'horloge bat toutes les 15 min
    # L'horloge ne sait poser que `Authorization: Bearer $<env>` : la clé vient de l'env.
    assert t["entete_token_env"] == "APPROBATIONS_CLE"


def test_l_horloge_construit_un_bearer_accepte_par_la_route(client, monkeypatch):
    import horloge
    tache = {"brique": "noyau", **_tache_relance()}
    taches = horloge.collecter_taches(type("R", (), {"briques": {"noyau": {"taches": [_tache_relance()]}}})())
    assert taches[0]["entete_token_env"] == "APPROBATIONS_CLE"
    # Lue AU MOMENT de l'appel : le secret n'est jamais figé dans la tâche.
    monkeypatch.setenv("APPROBATIONS_CLE", "autre-valeur")
    assert horloge._entetes(taches[0]) == {"Authorization": "Bearer autre-valeur"}
    monkeypatch.setenv("APPROBATIONS_CLE", CLE)
    entetes = horloge._entetes(taches[0])
    assert entetes == BEARER
    r = client.post(tache["chemin"], headers=entetes)
    assert r.status_code == 200, r.text


# ── Revue finale : prérequis non réunis sur un destructif ───────────────────

def test_destructif_prerequis_non_reunis_armer_refuse_sans_fuite(client):
    d = approbations.creer("app_supprimer", {"app": "x"}, "d", "destructif",
                           prerequis=("sauvegarde_verifiee",), utilisateur=U)
    r = client.post(f"/approbations/{d['id']}/code/armer", headers=ENT, json={"par": "tg:42", "utilisateur": U})
    assert r.status_code == 200 and r.json() == {"ok": False, "raison": "prerequis"}
    r2 = client.post("/approbations/code", headers=ENT, json={"par": "tg:42", "code": d["code"], "utilisateur": U})
    assert r2.status_code == 200 and r2.json() == {"pris_en_charge": False}
    assert d["code"] not in r.text + r2.text
    assert approbations.lire(d["id"])["statut"] == "en_attente"


# ── S245b : approbation liée à l'utilisateur ────────────────────────────────

def test_decision_exige_le_champ_utilisateur(client, demande):
    r = client.post(f"/approbations/{demande['id']}/decision", headers=ENT,
                    json={"decision": "ok", "par": "tg:42"})
    assert r.status_code == 422


def test_decision_d_un_autre_utilisateur_est_introuvable(client, demande):
    r = client.post(f"/approbations/{demande['id']}/decision", headers=ENT,
                    json={"decision": "ok", "par": "tg:42", "utilisateur": "intrus"})
    assert r.json()["ok"] is False and r.json()["raison"] == "introuvable"
    assert approbations.lire(demande["id"])["statut"] == "en_attente"


def test_decision_du_demandeur_passe(client, demande):
    r = client.post(f"/approbations/{demande['id']}/decision", headers=ENT,
                    json={"decision": "ok", "par": "tg:42",
                          "utilisateur": demande["utilisateur"]})
    assert r.json()["ok"] is True


def test_en_attente_ne_liste_que_les_demandes_de_la_session(client, demande, session):
    autre = approbations.creer("app_redemarrer", {"app": "autre"}, "o", "reversible",
                               utilisateur="intrus")
    ids = {a["id"] for a in client.get("/approbations/en_attente", cookies=session)
           .json()["approbations"]}
    assert demande["id"] in ids and autre["id"] not in ids


# ── Reprise après approbation (Task 6) ──────────────────────────────────────

@pytest.fixture
def reprises(monkeypatch):
    import approbations_reprise
    vues = []
    monkeypatch.setattr(approbations_reprise, "lancer", lambda registre, id_: vues.append(id_))
    return vues


def test_approuver_declenche_la_reprise(client, demande, reprises):
    client.post(f"/approbations/{demande['id']}/decision", headers=ENT,
                json={"decision": "ok", "par": "tg:42", "utilisateur": demande["utilisateur"]})
    assert reprises == [demande["id"]]


def test_refuser_ne_declenche_pas_de_reprise(client, demande, reprises):
    client.post(f"/approbations/{demande['id']}/decision", headers=ENT,
                json={"decision": "ko", "par": "tg:42", "utilisateur": demande["utilisateur"]})
    assert reprises == []


def test_decision_en_echec_ne_declenche_pas_de_reprise(client, demande, reprises):
    client.post(f"/approbations/{demande['id']}/decision", headers=ENT,
                json={"decision": "ok", "par": "tg:42", "utilisateur": "intrus"})
    assert reprises == []


def test_code_bon_declenche_la_reprise(client, demande_destructive, reprises):
    id_ = demande_destructive["id"]
    u = demande_destructive["utilisateur"]
    client.post(f"/approbations/{id_}/code/armer", headers=ENT, json={"par": "tg:42",
                                                                      "utilisateur": u})
    code = approbations.lire(id_)["code"]
    client.post("/approbations/code", headers=ENT,
                json={"par": "tg:42", "code": code, "utilisateur": u})
    assert reprises == [id_]


def test_code_faux_ne_declenche_pas_de_reprise(client, demande_destructive, reprises):
    id_ = demande_destructive["id"]
    u = demande_destructive["utilisateur"]
    client.post(f"/approbations/{id_}/code/armer", headers=ENT, json={"par": "tg:42",
                                                                      "utilisateur": u})
    client.post("/approbations/code", headers=ENT,
                json={"par": "tg:42", "code": "000000", "utilisateur": u})
    assert reprises == []


def test_relancer_reprend_les_approuvees_orphelines(client, demande, reprises):
    approbations.approuver(demande["id"], "tg:42", "telegram", time.time() - 3600,
                           utilisateur=demande["utilisateur"])
    r = client.post("/approbations/relancer", headers=ENT)
    assert reprises == [demande["id"]]
    assert r.json()["reprises"] == [demande["id"]]
