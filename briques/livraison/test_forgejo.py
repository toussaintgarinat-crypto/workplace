import asyncio
import httpx
import pytest
from forgejo import Forgejo, ForgejoErreur

JETON = "jeton-ultra-secret-123"
SHA = "f48c5ffaff8ce9cabf02daf1d108c9abb536bd03"


def faux(depots, branches, statut=200):
    appels = []

    def h(req: httpx.Request):
        appels.append((req.method, req.url.path, req.headers.get("authorization")))
        if statut != 200:
            return httpx.Response(statut, text=f"corps brut avec {JETON}")
        if req.url.path == "/api/v1/user/repos":
            return httpx.Response(200, json=depots)
        for cle, rep in branches.items():
            if req.url.path == f"/api/v1/repos/{cle}":
                return httpx.Response(200, json=rep) if rep else httpx.Response(404, json={})
        return httpx.Response(404, json={})
    return httpx.MockTransport(h), appels


def cli(t):
    return Forgejo("http://f.test", JETON, transport=t)


def run(c):
    return asyncio.run(c)


DEPOTS = [
    {"name": "cal", "full_name": "wp-admin/cal", "mirror": True, "default_branch": "main",
     "empty": False, "clone_url": "http://secret", "owner": {"login": "wp-admin"}},
    {"name": "vide", "full_name": "wp-admin/vide", "mirror": False, "default_branch": "main",
     "empty": True},
]


def test_depots_liste_blanche_commit_court_et_jeton_envoye():
    t, appels = faux(DEPOTS, {"wp-admin/cal/branches/main": {"commit": {"id": SHA, "message": "x"}}})
    r = run(cli(t).depots())
    assert r[0] == {"nom": "wp-admin/cal", "branche": "main", "miroir": True,
                    "dernier_commit": SHA[:7]}
    assert appels[0] == ("GET", "/api/v1/user/repos", f"token {JETON}")


def test_depot_vide_sans_branche_dernier_commit_none():
    t, appels = faux(DEPOTS, {"wp-admin/cal/branches/main": {"commit": {"id": SHA}}})
    r = run(cli(t).depots())
    assert r[1] == {"nom": "wp-admin/vide", "branche": "main", "miroir": False,
                    "dernier_commit": None}
    assert all("vide" not in a[1] for a in appels)  # pas d'appel inutile


def test_branche_introuvable_dernier_commit_none():
    t, _ = faux([DEPOTS[0]], {"wp-admin/cal/branches/main": None})
    assert run(cli(t).depots())[0]["dernier_commit"] is None


def test_401_message_honnete_sans_jeton():
    t, _ = faux([], {}, statut=401)
    with pytest.raises(ForgejoErreur) as e:
        run(cli(t).depots())
    assert e.value.statut == 401 and JETON not in e.value.message and "refusé" in e.value.message


def test_500_ne_relaie_pas_le_corps():
    t, _ = faux([], {}, statut=500)
    with pytest.raises(ForgejoErreur) as e:
        run(cli(t).depots())
    assert JETON not in e.value.message and "corps brut" not in e.value.message


def test_reseau_coupe():
    def boom(req):
        raise httpx.ConnectError(f"boom {JETON}")
    with pytest.raises(ForgejoErreur) as e:
        run(cli(httpx.MockTransport(boom)).depots())
    assert "injoignable" in e.value.message and JETON not in e.value.message


def test_timeout():
    def lent(req):
        raise httpx.ReadTimeout(f"lent {JETON}")
    with pytest.raises(ForgejoErreur) as e:
        run(cli(httpx.MockTransport(lent)).depots())
    assert "Délai" in e.value.message and JETON not in e.value.message


def test_json_invalide():
    t = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>"))
    with pytest.raises(ForgejoErreur) as e:
        run(cli(t).depots())
    assert "illisible" in e.value.message and "html" not in e.value.message


def test_reponse_non_liste():
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"a": 1}))
    with pytest.raises(ForgejoErreur):
        run(cli(t).depots())
