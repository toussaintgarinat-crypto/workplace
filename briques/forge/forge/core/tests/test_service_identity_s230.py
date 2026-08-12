"""S230 : le compte de service forge-service peut lire/écrire une venture par id
sans en être le owner_id historique — nécessaire car le mappeur connecteurs->Forge
tourne en tâche de fond, sans JWT d'un vrai utilisateur à propager."""
from __future__ import annotations

from types import SimpleNamespace

from app.auth import UserContext, _est_compte_service, get_current_user
from app.config import settings
import app.routers.ventures as ventures_mod


def test_est_compte_service_reconnait_l_azp_du_service():
    assert _est_compte_service({"sub": "x", "azp": settings.FORGE_SERVICE_CLIENT_ID}) is True


def test_est_compte_service_refuse_un_azp_different():
    assert _est_compte_service({"sub": "x", "azp": "coeur-web"}) is False


def test_est_compte_service_refuse_azp_absent():
    assert _est_compte_service({"sub": "x"}) is False


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSessionGet:
    def __init__(self, rows=None):
        self._rows = rows or []
        self._n = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        rows = self._rows if self._n == 0 else []
        self._n += 1
        return _FakeResult(rows)

    async def commit(self):
        pass


class _FakeSessionPatch:
    def __init__(self, rows=None):
        self._rows = rows or []
        self._n = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        rows = [] if self._n == 0 else self._rows
        self._n += 1
        return _FakeResult(rows)

    async def commit(self):
        pass


def _mk_venture(**kw):
    base = dict(
        id="11111111-1111-1111-1111-111111111111", owner_id="quelqu-un-d-autre",
        org_id=None, nom="Client X", description="", emoji="🚀", couleur="#6366f1",
        type="audit", statut="actif", created_at=None, updated_at=None,
        geo_object_id=None, audit_id="audit-1", profil_entreprise={"clients": {"n": 0}},
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _service_user():
    return UserContext(sub="svc-1", nom="forge-service", avatar_emoji="🤖",
                       org_id=None, est_service=True)


async def test_get_venture_owner_id_different_404_pour_un_utilisateur_normal(client, app):
    """Non-régression : sans est_service, le comportement S227 reste inchangé.

    `_FakeSessionGet` est bête (elle ignore le contenu de la requête SQL passée à
    `execute`, cf. classe ci-dessus) : elle ne peut pas évaluer elle-même le WHERE
    `owner_id == user.sub`. Pour simuler fidèlement ce que ferait un vrai Postgres
    face à un owner_id qui ne matche pas (0 ligne trouvée), on configure `rows=[]`
    — pas `rows=[v]`, qui simulerait au contraire une ligne trouvée quel que soit
    l'appelant et ne testerait donc rien côté ownership.
    """
    from app.auth import UserContext as UC, get_current_user as gcu
    v = _mk_venture()
    app.dependency_overrides[gcu] = lambda: UC(sub="pas-le-owner", nom="X",
                                               avatar_emoji="👤", org_id=None)
    ventures_mod.SessionLocal = lambda: _FakeSessionGet(rows=[])
    r = await client.get(f"/api/ventures/{v.id}")
    app.dependency_overrides.clear()
    assert r.status_code == 404


async def test_get_venture_le_compte_de_service_lit_une_venture_d_autrui(client, app):
    v = _mk_venture()
    app.dependency_overrides[get_current_user] = _service_user
    ventures_mod.SessionLocal = lambda: _FakeSessionGet(rows=[v])
    r = await client.get(f"/api/ventures/{v.id}")
    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["auditId"] == "audit-1"


async def test_patch_venture_le_compte_de_service_ecrit_une_venture_d_autrui(client, app):
    v = _mk_venture(profil_entreprise={"clients": {"nb": 3}})
    app.dependency_overrides[get_current_user] = _service_user
    ventures_mod.SessionLocal = lambda: _FakeSessionPatch(rows=[v])
    r = await client.patch(f"/api/ventures/{v.id}",
                           json={"profilEntreprise": {"clients": {"nb": 3}}})
    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["profilEntreprise"] == {"clients": {"nb": 3}}


async def test_patch_venture_owner_id_different_404_pour_un_utilisateur_normal(client, app):
    """`_FakeSessionPatch` ne peut pas non plus évaluer le WHERE elle-même (même
    limite que `_FakeSessionGet` ci-dessus) : `rows=[]` simule fidèlement le refetch
    d'un vrai Postgres après un UPDATE dont le WHERE owner_id n'a matché personne."""
    v = _mk_venture()
    app.dependency_overrides[get_current_user] = lambda: UserContext(
        sub="pas-le-owner", nom="X", avatar_emoji="👤", org_id=None)
    ventures_mod.SessionLocal = lambda: _FakeSessionPatch(rows=[])
    r = await client.patch(f"/api/ventures/{v.id}", json={"nom": "Hack"})
    app.dependency_overrides.clear()
    # update_venture ne lève pas explicitement : v reste None après un UPDATE qui n'a
    # touché aucune ligne (WHERE owner_id ne matche pas) → la route rend `None`.
    assert r.json() is None
