"""Tests de la logique PURE : MAC/WoL, parsing du parc, sonde (mock) et réveil (injecté).

Tout est hors-ligne : la sonde utilise un transport httpx simulé, le réveil reçoit des
fonctions injectées (aucun paquet UDP réel, aucune requête réelle)."""
import asyncio

import httpx
import pytest

import noeud as N


def _run(coro):
    return asyncio.run(coro)


# ── MAC / magic packet ───────────────────────────────────────────────────────
def test_normaliser_mac_formats():
    assert N.normaliser_mac("AA:BB:CC:DD:EE:FF") == "aabbccddeeff"
    assert N.normaliser_mac("aa-bb-cc-dd-ee-ff") == "aabbccddeeff"
    assert N.normaliser_mac("AABBCCDDEEFF") == "aabbccddeeff"


def test_normaliser_mac_invalide():
    for mauvais in ("", "AA:BB:CC", "ZZ:BB:CC:DD:EE:FF", "aabbccddeef"):
        with pytest.raises(ValueError):
            N.normaliser_mac(mauvais)


def test_paquet_wol_structure():
    p = N.paquet_wol("AA:BB:CC:DD:EE:FF")
    assert len(p) == 102                          # 6 octets 0xFF + 16 × 6 octets MAC
    assert p[:6] == b"\xff" * 6
    mac = bytes.fromhex("aabbccddeeff")
    assert p[6:] == mac * 16


# ── Parsing du parc (CALCUL_NOEUDS) ───────────────────────────────────────────
def test_charger_noeuds_valide():
    parc = N.charger_noeuds('[{"id":"m","endpoint":"http://x:1234","mac_wol":"AA:BB:CC:DD:EE:FF"}]')
    assert set(parc) == {"m"}
    assert parc["m"].endpoint == "http://x:1234"
    assert parc["m"].methode_reveil == ("wol", "wakeping")   # défaut


def test_charger_noeuds_ignore_incomplets():
    # Sans id ou sans endpoint → ignoré (pas de nœud bancal).
    parc = N.charger_noeuds('[{"endpoint":"http://x:1"},{"id":"ok","endpoint":"http://y:2"},{"id":"sans"}]')
    assert set(parc) == {"ok"}


def test_charger_noeuds_vide_et_illisible():
    assert N.charger_noeuds("") == {}
    assert N.charger_noeuds("   ") == {}
    assert N.charger_noeuds("{pas du json") == {}


def test_charger_noeuds_normalisations():
    # dict unique accepté ; methode en string ; slash final retiré ; sonde en string.
    parc = N.charger_noeuds('{"id":"m","endpoint":"http://x:1/","methode_reveil":"wol","sondes":"/v1/models"}')
    n = parc["m"]
    assert n.endpoint == "http://x:1"
    assert n.methode_reveil == ("wol",)
    assert n.sondes == ("/v1/models",)


def test_reveillable():
    assert N.Noeud("a", "http://x", mac_wol="AA:BB:CC:DD:EE:FF", methode_reveil=("wol",)).reveillable
    assert not N.Noeud("a", "http://x", methode_reveil=("wol",)).reveillable   # wol sans MAC
    assert N.Noeud("a", "http://x", methode_reveil=("wakeping",)).reveillable
    assert not N.Noeud("a", "http://x", methode_reveil=("aucun",)).reveillable


# ── Sonde (transport httpx simulé) ────────────────────────────────────────────
def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_sonder_joignable():
    n = N.Noeud("m", "http://x", methode_reveil=("wakeping",))

    async def go():
        async with _client(lambda req: httpx.Response(200, json={"data": []})) as c:
            return await N.sonder(n, c)
    assert _run(go()) is True
    assert n.etat == "eveille" and n.derniere_vue and n.derniere_erreur is None


def test_sonder_401_compte_comme_vivant():
    # Un 401 prouve que le serveur répond → prêt (< 500).
    n = N.Noeud("m", "http://x")

    async def go():
        async with _client(lambda req: httpx.Response(401)) as c:
            return await N.sonder(n, c)
    assert _run(go()) is True and n.etat == "eveille"


def test_sonder_5xx_non_pret():
    n = N.Noeud("m", "http://x", methode_reveil=("wakeping",), sondes=("/v1/models",))

    async def go():
        async with _client(lambda req: httpx.Response(503)) as c:
            return await N.sonder(n, c)
    assert _run(go()) is False and n.etat == "endormi"   # réveillable → endormi


def test_sonder_erreur_reseau_endormi_ou_injoignable():
    def boom(req):
        raise httpx.ConnectError("refused", request=req)

    reveillable = N.Noeud("m", "http://x", methode_reveil=("wakeping",))
    figé = N.Noeud("f", "http://x", methode_reveil=("aucun",))

    async def go(n):
        async with _client(boom) as c:
            return await N.sonder(n, c)
    assert _run(go(reveillable)) is False and reveillable.etat == "endormi"
    assert _run(go(figé)) is False and figé.etat == "injoignable"


# ── Réveil (sonde + WoL injectés) ─────────────────────────────────────────────
def test_reveiller_deja_pret():
    n = N.Noeud("m", "http://x")

    async def go():
        return await N.reveiller(n, sonde_fn=lambda _n: _vrai(), wol_fn=_interdit)
    res = _run(go())
    assert res["reveille"] is True and res["methode"] == "deja"


def test_reveiller_wol_puis_pret():
    n = N.Noeud("m", "http://x", mac_wol="AA:BB:CC:DD:EE:FF", methode_reveil=("wol",),
                reveil_timeout_s=5, intervalle_sonde_s=0.01)
    appels = {"wol": 0, "sonde": 0}

    async def sonde(_n):
        appels["sonde"] += 1
        return appels["sonde"] > 1               # False au pré-check, True ensuite

    def wol(mac, broadcast, port):
        appels["wol"] += 1

    res = _run(N.reveiller(n, sonde_fn=sonde, wol_fn=wol))
    assert res["reveille"] is True and res["methode"] == "wol"
    assert appels["wol"] == 1


def test_reveiller_echec_timeout():
    n = N.Noeud("m", "http://x", methode_reveil=("wakeping",), reveil_timeout_s=0)

    async def sonde(_n):
        return False
    res = _run(N.reveiller(n, sonde_fn=sonde, wol_fn=_interdit))
    assert res["reveille"] is False and res["methode"] == "wakeping"


# ── Pool multi-muscles : élection ─────────────────────────────────────────────
def _parc(*ids_priorites):
    return {i: N.Noeud(i, f"http://{i}", priorite=p, methode_reveil=("wakeping",))
            for i, p in ids_priorites}


def test_elire_prefere_plus_prioritaire_eveille():
    parc = _parc(("a", 50), ("b", 10), ("c", 30))

    async def sonde(n):                               # b et c répondent ; b est prioritaire
        return n.id in ("b", "c")
    elu = _run(N.elire(parc, sonde_fn=sonde, reveiller_fn=_interdit_coro))
    assert elu.id == "b"


def test_elire_aucun_eveille_sans_reveil():
    parc = _parc(("a", 10), ("b", 20))

    async def sonde(n):
        return False
    assert _run(N.elire(parc, sonde_fn=sonde, reveiller_fn=_interdit_coro)) is None


def test_elire_reveille_par_priorite():
    parc = _parc(("a", 30), ("b", 10))
    reveilles = []

    async def sonde(n):
        return False                                  # aucun déjà chaud

    async def reveille(n):
        reveilles.append(n.id)
        return {"reveille": n.id == "b"}              # seul b se réveille
    elu = _run(N.elire(parc, reveiller_si_besoin=True, sonde_fn=sonde, reveiller_fn=reveille))
    assert elu.id == "b"
    assert reveilles[0] == "b"                        # b tenté en premier (priorité 10)


# ── Petits utilitaires de test ────────────────────────────────────────────────
async def _vrai_coro():
    return True


def _vrai():
    return _vrai_coro()


def _interdit(*a, **k):
    raise AssertionError("WoL ne devait pas être déclenché")


async def _interdit_coro(*a, **k):
    raise AssertionError("le réveil ne devait pas être déclenché")
