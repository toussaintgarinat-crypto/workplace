"""S228 — quand un entretien est actif pour (fil, personne), le tour de chat est routé
directement vers Forge au lieu du LLM habituel. Teste la fonction extraite, pas tout le
serveur HTTP/SSE (cf. convention test_assistant_routes.py / test_gate_action_bout_en_bout.py)."""
import asyncio
import os
import sys

os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")
sys.path.insert(0, os.path.dirname(__file__))

import accord_action  # noqa: E402
import entretien_routage  # noqa: E402
from routers.assistant import _flux_entretien  # noqa: E402


def setup_function():
    entretien_routage.REGISTRE._actifs.clear()


def test_flux_entretien_emet_texte_puis_fin():
    class _FakeResp:
        status_code = 200

        def json(self):
            return {"question": "Et les fournisseurs ?", "statut": "en_cours"}

    class _FakeClient:
        async def post(self, url, **kw):
            return _FakeResp()

    async def _run():
        return [evt async for evt in _flux_entretien(
            venture_id="venture-1", fil_accord="fil-1", message="On a 5 clients.",
            client=_FakeClient(), base_forge="http://forge.test/api")]

    evts = asyncio.run(_run())
    types = [e["type"] for e in evts]
    assert types == ["texte", "fin"]
    assert evts[0]["contenu"] == "Et les fournisseurs ?"


def test_flux_entretien_sur_cloture_naturelle():
    class _FakeResp:
        status_code = 200

        def json(self):
            return {"question": None, "statut": "termine"}

    class _FakeClient:
        async def post(self, url, **kw):
            return _FakeResp()

    async def _run():
        return [evt async for evt in _flux_entretien(
            venture_id="venture-1", fil_accord="fil-1", message="Terminé.",
            client=_FakeClient(), base_forge="http://forge.test/api")]

    evts = asyncio.run(_run())
    assert evts[0]["type"] == "texte"
    assert "terminé" in evts[0]["contenu"].lower() or "termine" in evts[0]["contenu"].lower()
    assert evts[-1]["type"] == "fin"


def test_flux_entretien_forge_indisponible_ne_leve_pas():
    """Si Forge est injoignable (timeout/exception réseau), `_flux_entretien` ne doit PAS
    laisser l'exception remonter et casser le flux SSE — elle dégrade proprement."""
    class _FakeClientEnPanne:
        async def post(self, url, **kw):
            raise RuntimeError("connexion refusée")

    async def _run():
        return [evt async for evt in _flux_entretien(
            venture_id="venture-1", fil_accord="fil-1", message="On a 5 clients.",
            client=_FakeClientEnPanne(), base_forge="http://forge.test/api")]

    evts = asyncio.run(_run())
    assert [e["type"] for e in evts] == ["erreur", "fin"]
    assert "connexion refusée" in evts[0]["contenu"]


def test_flux_entretien_forge_reponse_malformee_ne_leve_pas():
    """Un 200 dont le corps n'est pas du JSON valide (`.json()` lève) doit aussi dégrader,
    pas planter le générateur."""
    class _FakeRespMalformee:
        status_code = 200

        def json(self):
            raise ValueError("not json")

    class _FakeClient:
        async def post(self, url, **kw):
            return _FakeRespMalformee()

    async def _run():
        return [evt async for evt in _flux_entretien(
            venture_id="venture-1", fil_accord="fil-1", message="On a 5 clients.",
            client=_FakeClient(), base_forge="http://forge.test/api")]

    evts = asyncio.run(_run())
    assert [e["type"] for e in evts] == ["erreur", "fin"]
    assert "not json" in evts[0]["contenu"]


def test_flux_entretien_erreur_http_desactive_le_registre():
    """Revue finale S228, Finding I1 : `repondre()` ne lisait jamais `status_code`. Sur un
    4xx/5xx de Forge, `statut` restait None (donc pas "termine"), le registre restait
    ACTIF, et le routage structurel court-circuitait le LLM à chaque tour suivant — fil
    confisqué sans autre issue qu'un mot-clé de pause. Ça arrive pour de vrai : entretien
    clôturé hors bande, venture supprimée, Forge redémarré."""
    class _FakeResp404:
        status_code = 404

        def json(self):
            raise AssertionError("le corps ne doit même pas être lu sur une erreur HTTP")

    class _FakeClient:
        async def post(self, url, **kw):
            return _FakeResp404()

    entretien_routage.REGISTRE.activer("fil-404", "venture-1")

    async def _run():
        return [evt async for evt in _flux_entretien(
            venture_id="venture-1", fil_accord="fil-404", message="On a 5 clients.",
            client=_FakeClient(), base_forge="http://forge.test/api")]

    evts = asyncio.run(_run())
    assert entretien_routage.REGISTRE.actif("fil-404") is None, "fil resté confisqué"
    assert [e["type"] for e in evts] == ["texte", "fin"]
    contenu = evts[0]["contenu"]
    assert "404" in contenu
    assert "continuons" not in contenu.lower(), "message trompeur d'entretien qui avance"


def test_repondre_erreur_http_rend_un_statut_interrompu():
    """Contrat de la charge rendue au flux : ni "termine" (le front annoncerait une
    clôture réussie), ni un dict vide (le flux relancerait « D'accord, continuons. »)."""
    class _FakeResp500:
        status_code = 503

        def json(self):
            raise AssertionError("corps non lu sur erreur HTTP")

    class _FakeClient:
        async def post(self, url, **kw):
            return _FakeResp500()

    entretien_routage.REGISTRE.activer("fil-503", "venture-1")
    data = asyncio.run(entretien_routage.repondre(
        registre=None, fil_accord="fil-503", venture_id="venture-1", message="x",
        client=_FakeClient(), base_forge="http://forge.test/api"))
    assert data["statut"] == "interrompu"
    assert data["erreurHttp"] == 503
    assert entretien_routage.REGISTRE.actif("fil-503") is None


def test_flux_entretien_cloture_avec_sync_erreur_est_honnete():
    """Revue finale S228, Finding I4 : la clôture Forge est best-effort — `statut` vaut
    "termine" même si le push d'ingestion ou le rappel /auditer a échoué. Annoncer
    « L'analyse est relancée » dans ce cas est un mensonge."""
    class _FakeResp:
        status_code = 200

        def json(self):
            return {"question": None, "statut": "termine",
                    "syncErreur": "push ingestion échoué (502)"}

    class _FakeClient:
        async def post(self, url, **kw):
            return _FakeResp()

    async def _run():
        return [evt async for evt in _flux_entretien(
            venture_id="venture-1", fil_accord="fil-sync", message="Terminé.",
            client=_FakeClient(), base_forge="http://forge.test/api")]

    evts = asyncio.run(_run())
    contenu = evts[0]["contenu"]
    assert "push ingestion échoué (502)" in contenu
    assert "L'analyse est relancée" not in contenu, "annonce mensongère de succès"


def test_flux_entretien_cloture_propre_annonce_toujours_le_succes():
    """Non-régression du chemin nominal : sans `syncErreur`, le message de succès reste
    celui d'origine (le fix I4 ne doit pas rendre tous les messages alarmistes)."""
    class _FakeResp:
        status_code = 200

        def json(self):
            return {"question": None, "statut": "termine", "syncErreur": None}

    class _FakeClient:
        async def post(self, url, **kw):
            return _FakeResp()

    async def _run():
        return [evt async for evt in _flux_entretien(
            venture_id="venture-1", fil_accord="fil-ok", message="Terminé.",
            client=_FakeClient(), base_forge="http://forge.test/api")]

    evts = asyncio.run(_run())
    assert "L'analyse est relancée" in evts[0]["contenu"]


def test_deux_personnes_meme_fil_entretiens_isoles():
    """web:dashboard est le fil pour TOUT LE MONDE côté web — seule la clé
    (fil, personne) (accord_action.cle) distingue Alice de Bob."""
    fil = "web:dashboard"
    fil_alice = accord_action.cle(fil, "alice")
    fil_bob = accord_action.cle(fil, "bob")

    entretien_routage.REGISTRE.activer(fil_alice, "venture-alice")
    entretien_routage.REGISTRE.activer(fil_bob, "venture-bob")

    assert entretien_routage.REGISTRE.actif(fil_alice) == "venture-alice"
    assert entretien_routage.REGISTRE.actif(fil_bob) == "venture-bob"

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"question": "Question pour Bob", "statut": "en_cours"}

    calls = []

    class _FakeClient:
        async def post(self, url, **kw):
            calls.append(url)
            return _FakeResp()

    async def _run():
        return [evt async for evt in _flux_entretien(
            venture_id=entretien_routage.REGISTRE.actif(fil_bob), fil_accord=fil_bob,
            message="Réponse de Bob", client=_FakeClient(), base_forge="http://forge.test/api")]

    asyncio.run(_run())
    # Le tour de Bob n'a appelé QUE la venture de Bob — jamais celle d'Alice.
    assert calls == ["http://forge.test/api/ventures/venture-bob/entretien/repondre"]
    # L'entretien d'Alice reste totalement inchangé.
    assert entretien_routage.REGISTRE.actif(fil_alice) == "venture-alice"
