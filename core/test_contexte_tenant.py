"""S121 — contexte de tenant du Cœur + propagation S2S (prépa multi-tenant).

Couvre : défauts mono-user, definir_contexte/reinitialiser, en-têtes sortants, capture
depuis les en-têtes entrants, et la propagation effective vers agenda (X-User-Id) et
l'adaptateur Forge (X-Forge-User-Token). Sans réseau (FakeClient capture les en-têtes).

Lancer : `VAULT_SECRET=test GATEWAY_KEY=test python3 -m pytest test_contexte_tenant.py`.
"""
import asyncio

import contexte_tenant as ct


def _reset_complet():
    """Repart des défauts (les ContextVars sont process-globaux entre tests)."""
    ct.definir_contexte(utilisateur=ct.UTILISATEUR_DEFAUT, org_id=None, user_token=None)
    # org_id/user_token ne peuvent pas être remis à None par definir_contexte (None = ne
    # touche pas) → on force via les ContextVars internes pour un état propre.
    ct._org_id.set(None)
    ct._user_token.set(None)
    ct._utilisateur.set(ct.UTILISATEUR_DEFAUT)


def test_defauts_mono_user():
    _reset_complet()
    c = ct.contexte_actuel()
    assert c.utilisateur == "perso"
    assert c.org_id is None
    assert c.user_token is None
    assert ct.entetes_agenda() == {"X-User-Id": "perso"}
    assert ct.entetes_donnees() == {"X-Org-ID": "defaut"}
    assert ct.entetes_forge() == {}


def test_definir_et_reinitialiser():
    _reset_complet()
    jetons = ct.definir_contexte(utilisateur="alice", org_id="acme", user_token="JWT-1")
    c = ct.contexte_actuel()
    assert (c.utilisateur, c.org_id, c.user_token) == ("alice", "acme", "JWT-1")
    assert ct.entetes_agenda() == {"X-User-Id": "alice"}
    assert ct.entetes_donnees() == {"X-Org-ID": "acme"}
    assert ct.entetes_forge() == {"X-Forge-User-Token": "Bearer JWT-1"}
    ct.reinitialiser(jetons)
    assert ct.contexte_actuel().utilisateur == "perso"


def test_valeurs_vides_ignorees():
    """Un en-tête présent mais vide ne doit pas écraser le défaut."""
    _reset_complet()
    ct.definir_contexte(utilisateur="", org_id="", user_token="")
    c = ct.contexte_actuel()
    assert c.utilisateur == "perso" and c.org_id is None and c.user_token is None


class _FakeRequest:
    def __init__(self, headers):
        self.headers = headers


async def _capter(req, **kw):
    """Pose le contexte puis le relit DANS le même contexte d'exécution.

    (Lire après `asyncio.run` échouerait : asyncio.run copie le contexte, donc les
    `set` faits dans la coroutine n'en sortent pas. En vrai FastAPI, dépendance et
    handler partagent le contexte du même task → la propagation fonctionne.)
    """
    await ct.lire_contexte_tenant(req, **kw)
    return ct.contexte_actuel()


def test_capture_depuis_entetes():
    _reset_complet()
    req = _FakeRequest({"X-User-Token": "Bearer ABC"})
    c = asyncio.run(_capter(req, x_org_id="acme", x_user_id="bob"))
    assert c.utilisateur == "bob"
    assert c.org_id == "acme"
    assert c.user_token == "ABC"  # préfixe Bearer retiré


def test_capture_token_via_authorization():
    _reset_complet()
    req = _FakeRequest({"Authorization": "Bearer XYZ"})
    c = asyncio.run(_capter(req, x_org_id=None, x_user_id=None))
    assert c.user_token == "XYZ"
    # Sans X-User-Id/X-Org-ID → défauts conservés.
    assert c.utilisateur == "perso" and c.org_id is None


def test_capture_sans_entete_garde_defauts():
    _reset_complet()
    c = asyncio.run(_capter(_FakeRequest({}), x_org_id=None, x_user_id=None))
    assert (c.org_id or ct.ORG_DEFAUT) == "defaut"
    assert c.utilisateur == "perso"


# ── Propagation effective vers les clients S2S ───────────────────────────────────

def test_agenda_entetes_reflete_le_contexte():
    _reset_complet()
    import agenda
    assert agenda._entetes()["X-User-Id"] == "perso"
    ct.definir_contexte(utilisateur="claire")
    assert agenda._entetes()["X-User-Id"] == "claire"


class _FakeResponse:
    status_code = 200

    def json(self):
        return {"ok": True}


class _FakeClient:
    """Capture les en-têtes du dernier appel ; ne touche pas le réseau."""
    def __init__(self):
        self.dernier_headers = None

    async def request(self, methode, url, headers=None, **kw):
        self.dernier_headers = headers
        return _FakeResponse()


def test_forge_appel_propage_le_token_utilisateur(monkeypatch):
    _reset_complet()
    import outils_communs
    monkeypatch.setattr(outils_communs, "_base", lambda registre, brique: "http://forge")

    # Avec un token → X-Forge-User-Token part.
    ct.definir_contexte(user_token="JWT-USER")
    client = _FakeClient()
    asyncio.run(outils_communs._forge_appel(client, {}, "GET", "/crm"))
    assert client.dernier_headers == {"X-Forge-User-Token": "Bearer JWT-USER"}


def test_forge_appel_sans_token_naffecte_rien(monkeypatch):
    _reset_complet()
    import outils_communs
    monkeypatch.setattr(outils_communs, "_base", lambda registre, brique: "http://forge")

    client = _FakeClient()
    asyncio.run(outils_communs._forge_appel(client, {}, "GET", "/crm"))
    # Pas de token → headers None → l'adaptateur Forge retombe sur son token de service.
    assert client.dernier_headers is None
