import asyncio
import json

import httpx
import pytest

from client_executeur import Executeur, ExecuteurErreur


def cli(handler, cle="k"):
    return Executeur("http://x.test", cle, transport=httpx.MockTransport(handler))


def run(c):
    return asyncio.run(c)


def test_verifier_envoie_la_cle_et_le_corps_et_renvoie_le_json():
    vus = []

    def h(req):
        vus.append((req.url.path, req.headers.get("x-api-key"), json.loads(req.content)))
        return httpx.Response(200, json={"ok": True, "verdict": "valide"})
    r = run(cli(h).verifier("postgres-a-b", "u", "b", "p/o"))
    assert r["verdict"] == "valide"
    assert vus == [("/verifier", "k", {"service": "postgres-a-b", "utilisateur": "u",
                                       "base": "b", "objet": "p/o"})]


@pytest.mark.parametrize("code,mot", [(401, "clé"), (409, "déjà en cours"), (404, "404"),
                                      (500, "500")])
def test_erreurs_http_messages_honnetes_sans_secret(code, mot):
    with pytest.raises(ExecuteurErreur) as e:
        run(cli(lambda r: httpx.Response(code, json={"detail": "SECRET-INTERNE"})).verifier(
            "postgres-a-b", "u", "b", "o"))
    assert mot in e.value.message and "SECRET-INTERNE" not in e.value.message


def test_injoignable_et_json_illisible():
    def boom(req):
        raise httpx.ConnectError("x")
    with pytest.raises(ExecuteurErreur) as e:
        run(cli(boom).verifier("postgres-a-b", "u", "b", "o"))
    assert "injoignable" in e.value.message
    with pytest.raises(ExecuteurErreur):
        run(cli(lambda r: httpx.Response(200, content=b"pas du json")).verifier(
            "postgres-a-b", "u", "b", "o"))


def _err(code, corps):
    with pytest.raises(ExecuteurErreur) as e:
        run(cli(lambda r: httpx.Response(code, json=corps)).verifier("postgres-a-b", "u", "b", "o"))
    return e.value.message


def test_message_fixe_de_l_executeur_repris():
    assert "service invalide." in _err(400, {"erreur": "service invalide."})
    assert "400" in _err(400, {"erreur": "service invalide."})


def test_erreur_tronquee_et_nettoyee():
    m = _err(500, {"erreur": "z" * 5000})
    assert m.count("z") == 120
    assert "\x07" not in _err(502, {"erreur": "a\x07b\nc"})


def test_erreur_non_str_ou_autre_cle_ignorees():
    assert _err(400, {"erreur": {"a": 1}}) == "L'exécuteur a répondu 400."
    assert "SECRET-INTERNE" not in _err(400, {"detail": "SECRET-INTERNE", "erreur": "ok"})


# --- S247 2b : cloner / comptages / supprimer_base ---

_CAS = [
    ("cloner", ("pg-a-b", "u", "b", "p/o", "b_neuve"), "/cloner",
     {"service": "pg-a-b", "utilisateur": "u", "base": "b", "objet": "p/o",
      "nouvelle_base": "b_neuve"}),
    ("comptages", ("pg-a-b", "u", "b"), "/comptages",
     {"service": "pg-a-b", "utilisateur": "u", "base": "b"}),
    ("supprimer_base", ("pg-a-b", "u", "b"), "/supprimer-base",
     {"service": "pg-a-b", "utilisateur": "u", "base": "b"}),
]


@pytest.mark.parametrize("nom,args,chemin,corps", _CAS)
def test_nouvelles_methodes_chemin_cle_corps(nom, args, chemin, corps):
    vus = []

    def h(req):
        vus.append((req.method, req.url.path, req.headers.get("x-api-key"),
                    json.loads(req.content)))
        return httpx.Response(200, json={"ok": True})
    assert run(getattr(cli(h), nom)(*args)) == {"ok": True}
    assert vus == [("POST", chemin, "k", corps)]


@pytest.mark.parametrize("nom,args,chemin,corps", _CAS)
def test_nouvelles_methodes_memes_erreurs(nom, args, chemin, corps):
    for code, mot in [(401, "clé"), (409, "opération"), (400, "400")]:
        with pytest.raises(ExecuteurErreur) as e:
            run(getattr(cli(lambda r, c=code: httpx.Response(
                c, json={"erreur": "x.", "detail": "SECRET"})), nom)(*args))
        assert mot in e.value.message and "SECRET" not in e.value.message
        assert e.value.statut == code

    def boom(req):
        raise httpx.ConnectError("x")
    with pytest.raises(ExecuteurErreur) as e:
        run(getattr(cli(boom), nom)(*args))
    assert "injoignable" in e.value.message


def test_cloner_a_un_delai_plus_long_que_verifier():
    delais = {}

    def h(req):
        delais[req.url.path] = req.extensions["timeout"]["read"]
        return httpx.Response(200, json={})
    c = cli(h)
    run(c.verifier("s", "u", "b", "o"))
    run(c.cloner("s", "u", "b", "o", "n"))
    run(c.comptages("s", "u", "b"))
    assert delais["/cloner"] == 960 > delais["/verifier"] == 280
    assert delais["/comptages"] == delais["/verifier"]


CLE_OBJ = "contrat/studio/0123456789abcdef/" + "a" * 32 + ".bin"


def test_deposer_lire_supprimer():
    vu = {}

    def h(req: httpx.Request):
        vu[req.method] = (str(req.url.path), req.headers.get("x-api-key"), req.content)
        return httpx.Response(200, content=b"retour" if req.method == "GET" else b"{}")

    ex = cli(h)
    run(ex.deposer(CLE_OBJ, b"abc"))
    assert run(ex.lire(CLE_OBJ)) == b"retour"
    run(ex.supprimer(CLE_OBJ))
    assert vu["PUT"] == ("/objets/" + CLE_OBJ, "k", b"abc")
    assert set(vu) == {"PUT", "GET", "DELETE"}


@pytest.mark.parametrize("statut,attendu", [(401, "refusé la clé"), (413, "trop gros"),
                                            (502, "502"), (500, "500")])
def test_objets_erreurs_sans_corps_brut(statut, attendu):
    ex = cli(lambda r: httpx.Response(statut, json={"erreur": "SECRET-INTERNE"}))
    with pytest.raises(ExecuteurErreur) as e:
        run(ex.deposer(CLE_OBJ, b"x"))
    assert attendu in e.value.message and "SECRET" not in e.value.message
