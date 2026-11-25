"""S246 (revue finale) — plomberie du dispatch dynamique exercée par la brique `livraison`.

- I1 : `relayer_erreurs` (opt-in par capacité) relaie le `detail` court d'une erreur métier.
- I2c : les routes de mutation (`/redemarrer`, `/rollback`, `/deployer`) ont un délai long,
  supérieur à celui que la brique s'accorde (60 s vers Dokploy).
- I5 : les valeurs substituées dans le chemin sont encodées (pas de changement de route).

    $ cd core && python3 -m pytest -q test_appel_dynamique_livraison.py
"""
import asyncio
import json

import pytest

import catalogue
import outils
import outils_communs


class _Registre:
    def __init__(self, briques):
        self.briques = briques


def _caps(relayer=True):
    cap = {"nom": "livraison_rollback", "description": "r", "methode": "POST",
           "chemin": "/apps/{app}/rollback", "params": {"app": {"type": "string"}},
           "action": True, "sensibilite": "reversible"}
    lecture = {"nom": "livraison_etat", "description": "e", "methode": "GET",
               "chemin": "/apps/{app}/etat", "params": {"app": {"type": "string"}},
               "action": False}
    if relayer:
        cap["relayer_erreurs"] = True
        lecture["relayer_erreurs"] = True
    sans = {"nom": "calcul_noeuds", "description": "n", "methode": "GET", "chemin": "/noeuds",
            "params": {}, "action": False}
    reg = _Registre({"livraison": {"nom": "livraison", "port": 6240, "capacites": [cap, lecture]},
                     "calcul": {"nom": "calcul", "port": 5990, "capacites": [sans]}})
    return outils._capacites_dynamiques(reg)


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


class _Client:
    def __init__(self, resp=None):
        self.resp = resp or _Resp()
        self.appels = []

    async def request(self, methode, url, json=None, params=None, headers=None, **kw):
        self.appels.append({"methode": methode, "url": url, "kw": kw})
        return self.resp


def _appel(cap, args, resp):
    cli = _Client(resp)
    out = asyncio.run(outils_communs._appel_dynamique(cli, cap, {**args, "confirme": True}))
    return cli, out


# ── I1 : relais du détail d'erreur ──
def test_catalogue_propage_relayer_erreurs():
    caps = _caps()
    assert caps["livraison_rollback"]["relayer_erreurs"] is True
    assert caps["calcul_noeuds"]["relayer_erreurs"] is False


def test_detail_court_relaye_si_opt_in():
    detail = "version ambiguë : précise l'id du déploiement"
    _, out = _appel(_caps()["livraison_rollback"], {"app": "cal"}, _Resp(409, {"detail": detail}))
    d = json.loads(out)
    assert d == {"ok": False, "brique": "livraison",
                 "message": f"Brique « livraison » a refusé (409) : {detail}"}


def test_detail_non_relaye_sans_le_flag():
    _, out = _appel(_caps()["calcul_noeuds"], {}, _Resp(409, {"detail": "secret interne"}))
    d = json.loads(out)
    assert d["message"] == "Brique « calcul » a refusé (409)." and "secret" not in out


def test_detail_non_relaye_si_flag_absent_sur_livraison():
    _, out = _appel(_caps(relayer=False)["livraison_rollback"], {"app": "cal"},
                    _Resp(409, {"detail": "x"}))
    assert json.loads(out)["message"] == "Brique « livraison » a refusé (409)."


@pytest.mark.parametrize("payload", [{"detail": "x" * 301},
                                     {"detail": [{"loc": ["body"], "msg": "bad"}]},
                                     {"detail": None}, {"message": "pas detail"}, ["liste"]])
def test_detail_trop_long_ou_non_chaine_non_relaye(payload):
    _, out = _appel(_caps()["livraison_rollback"], {"app": "cal"}, _Resp(422, payload))
    assert json.loads(out)["message"] == "Brique « livraison » a refusé (422)."


def test_detail_de_300_caracteres_relaye():
    _, out = _appel(_caps()["livraison_rollback"], {"app": "cal"}, _Resp(409, {"detail": "y" * 300}))
    assert json.loads(out)["message"].endswith(" : " + "y" * 300)


def test_corps_non_json_non_relaye():
    class _PasJson(_Resp):
        def json(self):
            raise ValueError("pas json")
    _, out = _appel(_caps()["livraison_rollback"], {"app": "cal"}, _PasJson(502))
    assert json.loads(out)["message"] == "Brique « livraison » a refusé (502)."


# ── I2c : délai long sur les mutations ──
@pytest.mark.parametrize("suffixe", ["redemarrer", "rollback", "deployer"])
def test_timeout_long_pour_les_mutations(suffixe):
    cap = dict(_caps()["livraison_rollback"])
    cap["chemin"] = f"/apps/{{app}}/{suffixe}"
    cap["url"] = f"http://host.docker.internal:6240/apps/{{app}}/{suffixe}"
    cli, _ = _appel(cap, {"app": "cal"}, _Resp(200, {"ok": True}))
    t = cli.appels[0]["kw"]["timeout"]
    assert t == outils_communs.TIMEOUT_MUTATION_LONGUE
    assert t > 60 + 2 * 20      # > délai mutation (60 s) + deux lectures Dokploy (20 s) côté brique


def test_timeout_par_defaut_inchange_pour_les_autres_routes():
    cli, _ = _appel(_caps()["livraison_etat"], {"app": "cal"}, _Resp(200, {}))
    assert "timeout" not in cli.appels[0]["kw"]      # timeout du client (30 s) conservé


# ── I5 : encodage des paramètres de chemin ──
@pytest.mark.parametrize("valeur,attendu", [
    ("x/deployer?", "x%2Fdeployer%3F"),
    ("a#b", "a%23b"),
    ("100%", "100%25"),
    ("mon app", "mon%20app"),
    ("../../sante", "..%2F..%2Fsante"),
    ("calendrier", "calendrier"),
    ("..", "%2E%2E"),          # sinon httpx normalise `/apps/../rollback` en `/rollback`
    (".", "%2E"),
])
def test_valeur_de_chemin_encodee(valeur, attendu):
    cap = _caps()["livraison_rollback"]
    url = outils_communs._url_dynamique(cap, {"app": valeur})
    assert url == f"http://host.docker.internal:6240/apps/{attendu}/rollback"


def test_valeur_hostile_ne_change_pas_la_route():
    cli, _ = _appel(_caps()["livraison_etat"], {"app": "x/deployer?a=1#"}, _Resp(200, {}))
    url = cli.appels[0]["url"]
    assert url.endswith("/etat") and url.count("/") == 5 and "?" not in url and "#" not in url
    assert cli.appels[0]["methode"] == "GET"
