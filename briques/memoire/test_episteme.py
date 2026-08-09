"""Métadonnées épistémiques des souvenirs (S224).

La garantie à prouver n'est pas « les compteurs montent » — c'est que **l'appelant ne peut
pas les écrire** : il n'émet qu'un signal, le service compte, et la confiance est une
fonction déterministe des compteurs.
"""

import os

import httpx
import pytest
import respx

os.environ.setdefault("MEMORY_API", "http://memoire-backend:8000")

import main  # noqa: E402

API = main.MEMORY_API
ESPACE_ID = "11111111-1111-1111-1111-111111111111"
NOEUD_ID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def _reset_session():
    main._session["token"] = None
    main._espaces.clear()
    main._verrous_signal.clear()
    yield
    main._session["token"] = None
    main._espaces.clear()


def _mock_auth_et_espace(rsx: respx.MockRouter):
    rsx.post(f"{API}/api/v1/auth/register").mock(return_value=httpx.Response(200, json={}))
    rsx.post(f"{API}/api/v1/auth/login").mock(
        return_value=httpx.Response(200, json={"access_token": "jwt-de-service"}))
    rsx.get(f"{API}/api/v1/spaces").mock(
        return_value=httpx.Response(200, json=[{"id": ESPACE_ID, "name": "Workplace"}]))


async def _appel(method: str, url: str, **kw):
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://brique") as c:
        return await c.request(method, url, **kw)


# ── La confiance est DÉRIVÉE, jamais déclarée ────────────────────────────────

@pytest.mark.parametrize("preuves,contradictions,attendu", [
    (0, 0, "moyenne"),   # souvenir neuf = hypothèse, ni confirmée ni réfutée
    (1, 0, "moyenne"),
    (2, 0, "haute"),
    (5, 1, "haute"),
    (0, 1, "faible"),
    (1, 1, "faible"),    # contredit autant qu'appuyé → on sous-pondère, sens protecteur
    (3, 3, "faible"),
    (3, 2, "moyenne"),
])
def test_confiance_derivee_des_compteurs(preuves, contradictions, attendu):
    assert main._confiance(preuves, contradictions) == attendu


def test_deux_contradictions_font_baisser_la_confiance():
    """Le critère de sortie du sprint, énoncé tel quel."""
    fm = {}
    for _ in range(2):
        e = main._episteme(fm)
        fm["contradictions"] = e["contradictions"] + 1
    assert main._episteme(fm)["confiance"] == "faible"


def test_une_confiance_ecrite_a_la_main_dans_le_frontmatter_est_ignoree():
    """Le point CENTRAL de S224 : même si quelqu'un (ou un LLM) glisse une confiance
    flatteuse dans le frontmatter, elle est recalculée depuis les compteurs."""
    fm = {"confiance": "haute", "preuves": 0, "contradictions": 3}
    assert main._episteme(fm)["confiance"] == "faible"


def test_compteur_negatif_ou_illisible_retombe_sur_le_neutre():
    """Un frontmatter trafiqué ou corrompu ne doit jamais lever ni fabriquer de certitude."""
    assert main._episteme({"preuves": -5, "contradictions": "beaucoup"}) == {
        "preuves": 0, "contradictions": 0, "confiance": "moyenne"}
    assert main._episteme({"preuves": None}) ["confiance"] == "moyenne"


def test_souvenir_d_avant_s224_reste_lisible():
    """Migration additive : pas de champ = défaut neutre, aucune erreur."""
    assert main._episteme({"wing": "input", "room": "general"}) == {
        "preuves": 0, "contradictions": 0, "confiance": "moyenne"}
    assert main._episteme(None)["confiance"] == "moyenne"


def test_les_signaux_admis_sont_fermes():
    assert main.SIGNAUX == ("preuve", "contradiction")


# ── La route de signal ───────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_un_signal_incremente_le_bon_compteur_et_recalcule_la_confiance():
    _mock_auth_et_espace(respx.mock)
    noeud = f"{API}/api/v1/spaces/{ESPACE_ID}/nodes/{NOEUD_ID}"
    respx.mock.get(noeud).mock(return_value=httpx.Response(
        200, json={"id": NOEUD_ID, "frontmatter": {"wing": "input", "preuves": 1}}))
    ecriture = respx.mock.put(noeud).mock(return_value=httpx.Response(200, json={}))

    r = await _appel("POST", f"/souvenir/{NOEUD_ID}/signal", json={"signal": "preuve"})

    assert r.status_code == 200
    assert r.json() == {"id": NOEUD_ID, "signal": "preuve", "avant": "moyenne",
                        "preuves": 2, "contradictions": 0, "confiance": "haute"}
    envoye = ecriture.calls[0].request
    import json as _json
    fm = _json.loads(envoye.content)["frontmatter"]
    assert fm["preuves"] == 2 and fm["confiance"] == "haute"
    assert fm["wing"] == "input", "le reste du frontmatter doit survivre à l'incrément"


@pytest.mark.asyncio
@respx.mock
async def test_un_signal_ne_peut_pas_transporter_de_compteur():
    """Même en tentant de glisser `preuves` dans le corps, seul `signal` est lu :
    le modèle Pydantic n'a pas d'autre champ."""
    _mock_auth_et_espace(respx.mock)
    noeud = f"{API}/api/v1/spaces/{ESPACE_ID}/nodes/{NOEUD_ID}"
    respx.mock.get(noeud).mock(return_value=httpx.Response(
        200, json={"id": NOEUD_ID, "frontmatter": {}}))
    ecriture = respx.mock.put(noeud).mock(return_value=httpx.Response(200, json={}))

    r = await _appel("POST", f"/souvenir/{NOEUD_ID}/signal",
                     json={"signal": "preuve", "preuves": 99, "confiance": "haute"})

    assert r.status_code == 200
    import json as _json
    fm = _json.loads(ecriture.calls[0].request.content)["frontmatter"]
    assert fm["preuves"] == 1 and fm["confiance"] == "moyenne"


@pytest.mark.asyncio
@respx.mock
async def test_signal_invalide_refuse():
    _mock_auth_et_espace(respx.mock)
    r = await _appel("POST", f"/souvenir/{NOEUD_ID}/signal", json={"signal": "haute"})
    assert r.status_code == 422


@pytest.mark.asyncio
@respx.mock
async def test_souvenir_inconnu_donne_404_et_n_ecrit_rien():
    _mock_auth_et_espace(respx.mock)
    noeud = f"{API}/api/v1/spaces/{ESPACE_ID}/nodes/{NOEUD_ID}"
    respx.mock.get(noeud).mock(return_value=httpx.Response(404, json={"detail": "no"}))
    ecriture = respx.mock.put(noeud).mock(return_value=httpx.Response(200, json={}))

    r = await _appel("POST", f"/souvenir/{NOEUD_ID}/signal", json={"signal": "preuve"})

    assert r.status_code == 404
    assert not ecriture.called


@pytest.mark.asyncio
@respx.mock
async def test_la_liste_expose_la_confiance():
    _mock_auth_et_espace(respx.mock)
    respx.mock.get(f"{API}/api/v1/spaces/{ESPACE_ID}/nodes").mock(
        return_value=httpx.Response(200, json=[
            {"id": NOEUD_ID, "title": "T", "content_md": "C", "type": "input",
             "frontmatter": {"preuves": 0, "contradictions": 2}}]))

    r = await _appel("GET", "/souvenirs")

    s = r.json()["souvenirs"][0]
    assert s["confiance"] == "faible" and s["contradictions"] == 2


# ── Le manifeste dit la même chose que le code ───────────────────────────────

def test_le_manifest_n_expose_que_le_signal_jamais_les_compteurs():
    """Si un jour `preuves` devenait un paramètre déclaré, le LLM pourrait écrire le
    compteur — toute la garantie tomberait. Ce test le rend impossible en silence."""
    import json
    from pathlib import Path

    manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
    cap = next(c for c in manifest["capacites"] if c["nom"] == "memoire_signaler")
    assert set(cap["params"]) == {"souvenir_id", "signal", "espace"}
    assert cap["params"]["signal"]["enum"] == ["preuve", "contradiction"]
    assert not cap.get("action"), ("signaler n'est pas destructif : le gater exigerait un "
                                   "« oui » de l'utilisateur à chaque signal et tuerait la "
                                   "boucle de rétroaction")
    for c in manifest["capacites"]:
        assert "preuves" not in (c.get("params") or {})
        assert "contradictions" not in (c.get("params") or {})
        assert "confiance" not in (c.get("params") or {})
