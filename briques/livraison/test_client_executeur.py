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
