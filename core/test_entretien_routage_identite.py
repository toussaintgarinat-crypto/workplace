"""S228 (revue finale, Finding C1b — réouvert) — l'identité réelle traverse aussi le
chemin STRUCTUREL de l'entretien, pas seulement le dispatch dynamique.

Miroir de `test_capacite_dynamique_identite_forge.py` (qui couvre `_appel_dynamique`,
emprunté par `forge_entretien_demarrer`). Ici on couvre l'AUTRE chemin, celui que prend
CHAQUE réponse d'entretien : `routers/assistant.py` → `entretien_routage.repondre()`,
qui court-circuite volontairement le LLM et n'envoyait AUCUN en-tête.

Sans ce fix : « démarre l'entretien » réussit sous la vraie identité, puis la première
réponse part sous le compte de SERVICE de l'adaptateur → `Ventures.owner_id == user.sub`
ne matche plus → 404 → 502 → « Je n'ai pas pu enregistrer ta réponse… ». L'entretien a
l'air de marcher pendant exactement un tour.

Le test bout-en-bout passe par le VRAI serveur ASGI (TestClient + StreamingResponse SSE) :
c'est le seul moyen de prouver que les ContextVars du contexte de tenant (posés par la
dépendance `lire_contexte_tenant`) sont bien lisibles au moment où le client HTTP sortant
est construit — le générateur SSE, lui, s'exécute après le retour de la route.
"""
import json
import os
import sys
import tempfile

os.environ["ASSISTANT_CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "cfg.json")
os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")
os.environ.setdefault("AUTH_SESSION_SECRET", "test-session-secret-0123456789")
sys.path.insert(0, os.path.dirname(__file__))

import accord_action  # noqa: E402
import contexte_tenant  # noqa: E402
import entretien_routage  # noqa: E402
import journal_conversations  # noqa: E402
import outils_communs  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from routers import assistant as routeur_assistant  # noqa: E402

client_http = TestClient(main.app)


# ── 1. Source unique des en-têtes Forge (les deux chemins doivent partager le même jeu) ──

def _entetes_avec_jeton(token):
    jetons = contexte_tenant.definir_contexte(user_token=token) if token else None
    try:
        return outils_communs.entetes_forge_sortants()
    finally:
        if jetons is not None:
            contexte_tenant.reinitialiser(jetons)


def test_entetes_sortants_portent_le_jeton_utilisateur():
    entetes = _entetes_avec_jeton("USER-JWT-123")
    assert entetes.get("X-Forge-User-Token") == "Bearer USER-JWT-123", entetes


def test_entetes_sortants_conservent_les_entetes_de_service():
    """La propagation d'identité s'AJOUTE aux en-têtes de service, elle ne les remplace pas."""
    assert _entetes_avec_jeton("USER-JWT-123").get("X-Compte-Id"), "en-tête de service perdu"


def test_entetes_sortants_sans_jeton_ne_posent_rien():
    """Mono-user : aucun jeton → l'adaptateur retombe sur son token de service (S17/S24)."""
    assert "X-Forge-User-Token" not in _entetes_avec_jeton(None)


def test_les_deux_chemins_partagent_la_meme_resolution():
    """Garde-fou anti-divergence : si un jour `_appel_dynamique` cesse d'utiliser la source
    unique, le chemin structurel repartirait en silence sous le compte de service."""
    import inspect
    src = inspect.getsource(outils_communs._appel_dynamique)
    assert "entetes_forge_sortants()" in src, src


# ── 2. Bout-en-bout : le client HTTP du chemin structurel porte bien l'en-tête ──────────

class _FauxReponse:
    status_code = 200

    def json(self):
        return {"question": "Et vos fournisseurs ?", "statut": "en_cours"}


class _FauxClientHTTP:
    """Remplace `httpx.AsyncClient` le temps d'un tour de chat et capture les en-têtes
    posés à la CONSTRUCTION (c'est là que le fix les injecte)."""

    dernier = None

    def __init__(self, *a, headers=None, **kw):
        self.headers = dict(headers or {})
        _FauxClientHTTP.dernier = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        return _FauxReponse()


def _tour_de_chat(entetes_requete: dict) -> dict:
    """Joue un tour de chat sur un entretien ACTIF et rend les en-têtes du client sortant."""
    fil = journal_conversations.fil("web", "dashboard")
    fil_accord = accord_action.cle(fil, "alice")
    entretien_routage.REGISTRE.activer(fil_accord, "venture-1")

    base_origine = routeur_assistant.catalogue.base_brique
    httpx_origine = routeur_assistant.httpx.AsyncClient
    routeur_assistant.catalogue.base_brique = lambda registre, nom: (
        "http://forge.test" if nom == "forge" else base_origine(registre, nom))
    routeur_assistant.httpx.AsyncClient = _FauxClientHTTP
    _FauxClientHTTP.dernier = None
    try:
        r = client_http.post("/assistant/chat",
                             json={"messages": [{"role": "user", "content": "On a 5 clients."}],
                                   "utilisateur": "alice"},
                             headers=entetes_requete)
        assert r.status_code == 200, r.text
        # On consomme le flux SSE : le générateur (donc la construction du client) ne
        # s'exécute QU'À la lecture du corps.
        assert "Et vos fournisseurs ?" in r.text, r.text
    finally:
        routeur_assistant.catalogue.base_brique = base_origine
        routeur_assistant.httpx.AsyncClient = httpx_origine
        entretien_routage.REGISTRE.desactiver(fil_accord)
    assert _FauxClientHTTP.dernier is not None, "le chemin structurel n'a pas été emprunté"
    return _FauxClientHTTP.dernier.headers


def test_chemin_structurel_propage_le_jeton_utilisateur():
    """LE test du Finding C1b réouvert : la réponse d'entretien part avec l'identité réelle.

    Prouve aussi, sur le vrai serveur ASGI, que le ContextVar posé par
    `lire_contexte_tenant` est encore lisible à la construction du client sortant."""
    entetes = _tour_de_chat({"X-User-Token": "Bearer USER-JWT-123"})
    assert entetes.get("X-Forge-User-Token") == "Bearer USER-JWT-123", entetes


def test_chemin_structurel_conserve_les_entetes_de_service():
    entetes = _tour_de_chat({"X-User-Token": "Bearer USER-JWT-123"})
    assert entetes.get("X-Compte-Id"), entetes


def test_chemin_structurel_sans_jeton_reste_en_mono_user():
    """Sans jeton, rien n'est posé : repli sur le token de service de l'adaptateur."""
    entetes = _tour_de_chat({})
    assert "X-Forge-User-Token" not in entetes, entetes


def test_le_client_par_defaut_transporte_bien_les_entetes_au_post():
    """`entretien_routage.repondre()` poste sans `headers=` : la propagation ne tient que
    parce que les en-têtes sont posés sur le CLIENT. Preuve avec un vrai `httpx.AsyncClient`
    (transport bouchonné, aucun réseau)."""
    import asyncio
    import httpx

    vus = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        vus.update(dict(request.headers))
        return httpx.Response(200, json={"question": "suite ?", "statut": "en_cours"})

    async def _run():
        transport = httpx.MockTransport(_handler)
        async with httpx.AsyncClient(transport=transport,
                                     headers={"X-Forge-User-Token": "Bearer USER-JWT-123"}) as c:
            return await entretien_routage.repondre(
                registre=None, fil_accord="fil-x", venture_id="venture-1", message="ok",
                client=c, base_forge="http://forge.test")

    data = asyncio.run(_run())
    assert data["statut"] == "en_cours"
    assert vus.get("x-forge-user-token") == "Bearer USER-JWT-123", vus
