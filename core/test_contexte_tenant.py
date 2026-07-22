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
    assert ct.entetes_par_personne() == {"X-User-Id": "perso"}
    assert ct.entetes_donnees() == {"X-Org-ID": "defaut"}
    assert ct.entetes_forge() == {}


def test_definir_et_reinitialiser():
    _reset_complet()
    jetons = ct.definir_contexte(utilisateur="alice", org_id="acme", user_token="JWT-1")
    c = ct.contexte_actuel()
    assert (c.utilisateur, c.org_id, c.user_token) == ("alice", "acme", "JWT-1")
    assert ct.entetes_par_personne() == {"X-User-Id": "alice"}
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
    def __init__(self, headers, cookies=None):
        self.headers = headers
        self.cookies = cookies or {}


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


# ── S182 « chacun son agenda » : repli sur le sub de session ──────────────────────

def test_repli_sub_session_quand_pas_de_x_user_id(monkeypatch):
    """Le dashboard n'envoie pas X-User-Id (auth par cookie) → on doit résoudre depuis
    la session web. C'est le maillon qui manquait (sinon tous les comptes → perso)."""
    _reset_complet()
    import auth
    monkeypatch.setattr(auth, "sub_session_optionnel", lambda req: "kc-sub-de-marina")
    c = asyncio.run(_capter(_FakeRequest({}), x_org_id=None, x_user_id=None))
    assert c.utilisateur == "kc-sub-de-marina"


def test_session_prioritaire_sur_x_user_id(monkeypatch):
    """S185 : une session valide l'emporte TOUJOURS sur l'en-tête — sinon un utilisateur
    connecté pourrait usurper l'identité d'un autre en posant X-User-Id depuis son
    navigateur (agenda.router / mail_proxy.router sont aussi atteints en direct)."""
    _reset_complet()
    import auth
    monkeypatch.setattr(auth, "sub_session_optionnel", lambda req: "sub-session")
    c = asyncio.run(_capter(_FakeRequest({}), x_org_id=None, x_user_id="sub-usurpe"))
    assert c.utilisateur == "sub-session"


def test_x_user_id_repli_seulement_sans_session(monkeypatch):
    """Sans session valide (S2S/script pur, pas de cookie) l'en-tête X-User-Id reste
    honoré — c'est le seul cas où il sert encore de source d'identité."""
    _reset_complet()
    import auth
    monkeypatch.setattr(auth, "sub_session_optionnel", lambda req: None)
    c = asyncio.run(_capter(_FakeRequest({}), x_org_id=None, x_user_id="sub-entete"))
    assert c.utilisateur == "sub-entete"


def test_sans_session_ni_entete_reste_perso(monkeypatch):
    """Ni en-tête ni session valide → défaut perso (comportement mono-user inchangé)."""
    _reset_complet()
    import auth
    monkeypatch.setattr(auth, "sub_session_optionnel", lambda req: None)
    c = asyncio.run(_capter(_FakeRequest({}), x_org_id=None, x_user_id=None))
    assert c.utilisateur == "perso"


# ── Propagation effective vers les clients S2S ───────────────────────────────────

def test_agenda_entetes_reflete_le_contexte():
    _reset_complet()
    import agenda
    assert agenda._entetes()["X-User-Id"] == "perso"
    ct.definir_contexte(utilisateur="claire")
    assert agenda._entetes()["X-User-Id"] == "claire"


def test_entetes_brique_par_personne_forwarde_identite():
    """S182 (agenda) + S184 (ecoute) + S185 (mail) + S186 (memoire) + S187 (studio) +
    veille-info : la surface /service (outils de l'assistant) doit porter
    X-User-Id = utilisateur connecté pour les briques « cercle privé » ; les autres
    briques ne le portent pas."""
    _reset_complet()
    import outils_communs
    ct.definir_contexte(utilisateur="claire")
    assert outils_communs._entetes_brique("agenda")["X-User-Id"] == "claire"
    assert outils_communs._entetes_brique("ecoute")["X-User-Id"] == "claire"
    assert outils_communs._entetes_brique("mail")["X-User-Id"] == "claire"
    assert outils_communs._entetes_brique("memoire")["X-User-Id"] == "claire"
    assert outils_communs._entetes_brique("studio")["X-User-Id"] == "claire"
    assert outils_communs._entetes_brique("veille-info")["X-User-Id"] == "claire"
    assert outils_communs._entetes_brique("veille-prospection")["X-User-Id"] == "claire"
    # Une autre brique (ex. restaurant) ne reçoit PAS X-User-Id (elle l'ignorerait).
    assert "X-User-Id" not in outils_communs._entetes_brique("restaurant")


def test_entetes_brique_normalise_les_tirets_pour_le_nom_de_variable_env(monkeypatch):
    """`veille-info` est la 1ère brique « cercle privé » au nom composé (tiret) : la clé
    d'env attendue est `VEILLE_INFO_KEY` (convention Python/monorepo, underscore), pas
    `VEILLE-INFO_KEY` (ce que donnerait `brique.upper()` littéral, sans normalisation)."""
    _reset_complet()
    import outils_communs
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-de-service")
    assert outils_communs._entetes_brique("veille-info")["X-API-Key"] == "cle-de-service"


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
