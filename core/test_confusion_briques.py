"""Confusion de noms entre briques (incident Telegram 2026-11-24).

`synopsis` a role « video » ET une autre brique s'appelle `video` ; sa capacité s'appelle
`video_resumer`. L'assistant a appelé brique_reveiller("atelier-images-video") puis
brique_etat("video") au lieu de « synopsis », et les erreurs d'outil nommaient la CAPACITÉ
comme si c'était la brique. De plus le sondage asynchrone (5 s) tombait sur la fermeture
keep-alive d'uvicorn (5 s) : « Server disconnected without sending a response ».

$ cd core && python3 -m pytest test_confusion_briques.py -v
"""
import asyncio
import json
import os

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")

import httpx  # noqa: E402
import pytest  # noqa: E402

import outils  # noqa: E402
import outils_communs  # noqa: E402
import sommeil  # noqa: E402
from test_sommeil import FauxDocker, Registre  # noqa: E402


def run(c):
    return asyncio.run(c)


def _registre():
    # Reproduction du HP : `video` (ne dort pas) et `synopsis` (dort) partagent role « video ».
    return Registre({
        "video": {"role": "video", "port": 5960, "capacites": [
            {"nom": "video_generer", "description": "x", "methode": "POST", "chemin": "/g"}]},
        "synopsis": {"role": "video", "port": 6090,
                     "sommeil": {"conteneurs": ["workplace-synopsis"], "inactivite_min": 30},
                     "capacites": [{"nom": "video_resumer", "description": "x", "methode": "POST",
                                    "chemin": "/resumer", "async": True}]},
        "connecteurs": {"role": "connecteurs", "sommeil": {"conteneurs": ["workplace_connecteurs"]}},
        "atelier-images-video": {"role": "atelier-images-video", "port": 6160},
    })


@pytest.fixture(autouse=True)
def _docker():
    sommeil.definir_backend(FauxDocker({
        "workplace-synopsis": {"running": False, "sante": None},
        "workplace_connecteurs": {"running": False, "sante": None}}))
    yield
    sommeil.definir_backend(None)


# ── résolution d'un nom de brique ────────────────────────────────────────────

def test_nom_exact_inchange():
    assert sommeil.resoudre(_registre(), "synopsis") == ("synopsis", None)


def test_un_nom_de_capacite_designe_sa_brique():
    brique, note = sommeil.resoudre(_registre(), "video_resumer")
    assert brique == "synopsis" and "video_resumer" in note


def test_un_role_ambigu_choisit_la_seule_brique_qui_dort():
    brique, note = sommeil.resoudre(_registre(), "video")      # `video` ne dort pas, `synopsis` si
    # « video » est un NOM de brique exact : on respecte le nom exact, mais on guide.
    assert brique == "video"
    assert "synopsis" in note and "dort" in note.lower()


def test_brique_inconnue_liste_celles_qui_dorment():
    brique, note = sommeil.resoudre(_registre(), "atelier-images-video")
    assert brique == "atelier-images-video"
    assert "synopsis" in note and "connecteurs" in note        # liste des briques qui dorment


def test_reveiller_par_nom_de_capacite_reveille_la_vraie_brique():
    out = json.loads(run(outils.executer("brique_reveiller", {"brique": "video_resumer"},
                                         _registre())))
    assert out["ok"] and out["brique"] == "synopsis"


def test_reveiller_une_brique_qui_ne_dort_pas_dit_laquelle_dort():
    out = json.loads(run(outils.executer("brique_reveiller", {"brique": "video"}, _registre())))
    assert out["ok"] is False and "synopsis" in out["message"]


def test_brique_etat_inconnue_guide_vers_les_briques_qui_dorment():
    out = json.loads(run(outils.executer("brique_etat", {"brique": "video"}, _registre())))
    assert out["etat"] == "inconnue" and "synopsis" in out["message"]


def test_description_des_outils_ne_donne_plus_video_en_exemple():
    for o in outils.OUTILS:
        if o["function"]["name"] in ("brique_etat", "brique_reveiller", "brique_endormir"):
            d = json.dumps(o, ensure_ascii=False)
            assert "geo, video, images" not in d


# ── messages d'erreur : on nomme la BRIQUE, pas seulement l'outil ─────────────

def test_erreur_reseau_d_un_outil_nomme_la_brique(monkeypatch):
    async def boum(*a, **k):
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
    monkeypatch.setattr(outils, "_appel_dynamique", boum)
    reg = _registre()
    # brique éveillée : pas de réveil
    sommeil.definir_backend(FauxDocker({
        "workplace-synopsis": {"running": True, "sante": "healthy"},
        "workplace_connecteurs": {"running": False, "sante": None}}))
    msg = run(outils.executer("video_resumer", {"url": "https://youtu.be/x"}, reg))
    assert "synopsis" in msg and "video_resumer" in msg


# ── sondage asynchrone : tolère une coupure keep-alive ───────────────────────

def test_sondage_reessaie_apres_une_deconnexion_serveur(monkeypatch):
    monkeypatch.setattr(outils_communs, "ASYNC_POLL", 0.0)
    appels = {"n": 0}

    def handler(request):
        appels["n"] += 1
        if appels["n"] == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        if appels["n"] == 2:
            return httpx.Response(200, json={"statut": "en_cours"})
        return httpx.Response(200, json={"statut": "termine", "resultat": {"ok": True}})

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(outils_communs.httpx, "AsyncClient",
                        lambda **kw: real(transport=transport, **{k: v for k, v in kw.items()
                                                                   if k != "limits"}))
    out = run(outils_communs._poll_async("http://x/jobs/1", None, "synopsis", "1"))
    assert json.loads(out) == {"ok": True} and appels["n"] == 3


def test_sondage_abandonne_apres_trop_de_coupures_et_nomme_la_brique(monkeypatch):
    monkeypatch.setattr(outils_communs, "ASYNC_POLL", 0.0)
    transport = httpx.MockTransport(lambda r: (_ for _ in ()).throw(
        httpx.RemoteProtocolError("Server disconnected")))
    real = httpx.AsyncClient
    monkeypatch.setattr(outils_communs.httpx, "AsyncClient",
                        lambda **kw: real(transport=transport, **{k: v for k, v in kw.items()
                                                                   if k != "limits"}))
    out = json.loads(run(outils_communs._poll_async("http://x/jobs/1", None, "synopsis", "1")))
    assert out["ok"] is False and out["brique"] == "synopsis"


# ── Filet sur les VRAIS manifestes du dépôt ──────────────────────────────────

def _vrais_manifestes():
    import glob
    racine = os.path.join(os.path.dirname(__file__), "..", "briques")
    return {json.load(open(m))["nom"]: json.load(open(m))
            for m in glob.glob(os.path.join(racine, "*", "manifest.json"))}


def test_aucune_capacite_ne_porte_le_nom_d_une_brique():
    briques = _vrais_manifestes()
    collisions = [(c["nom"], b) for b, m in briques.items()
                  for c in m.get("capacites", []) if c["nom"] in briques]
    assert not collisions, collisions


def test_chaque_capacite_se_resout_vers_sa_propre_brique():
    briques = _vrais_manifestes()
    reg = Registre(briques)
    faux = []
    for b, m in briques.items():
        for c in m.get("capacites", []):
            res, _ = sommeil.resoudre(reg, c["nom"])
            if res != b:
                faux.append((c["nom"], b, res))
    assert not faux, faux


def test_une_brique_qui_dort_est_toujours_atteignable_par_son_nom():
    briques = _vrais_manifestes()
    reg = Registre(briques)
    for b in sommeil.briques_endormissables(reg):
        assert sommeil.resoudre(reg, b) == (b, None)
