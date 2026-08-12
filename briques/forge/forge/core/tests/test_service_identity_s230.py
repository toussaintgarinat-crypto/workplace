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


def _bound_owner_id(stmt):
    """Inspecte le WHERE réellement construit par la route (compilation SQLAlchemy),
    pas une visibilité précalculée à la main : si la route a lié un paramètre
    `owner_id` dans son WHERE (cas normal, `and_(id==u, owner_id==user.sub)`), on
    renvoie la valeur liée — c'est littéralement `user.sub` tel que la route l'a
    passé. Si aucun paramètre `owner_id` n'apparaît (branche est_service, WHERE
    `id==u` seul), on renvoie None : un vrai Postgres ne filtrerait alors pas du
    tout sur l'owner. Vérifié empiriquement : SQLAlchemy nomme ce bind
    `owner_id_1` pour `Ventures.owner_id == ...` (cf. stmt.compile().params)."""
    try:
        params = stmt.compile().params
    except Exception:
        return None, False
    for k, v in params.items():
        if k == "owner_id" or k.startswith("owner_id_"):
            return v, True
    return None, False


class _FakeSessionGet:
    """Émule le filtre owner_id du VRAI get_venture (cf. app/routers/ventures.py) en
    inspectant, à CHAQUE execute(), le WHERE effectivement compilé par la route —
    contrairement à un mock aveugle qui renvoie `rows` selon le rang d'appel ou une
    visibilité décidée d'avance par le test, celui-ci ne sait rien tant qu'il n'a
    pas vu la requête SQL réelle. Si un paramètre owner_id est lié, la ligne n'est
    visible que si la valeur liée == venture.owner_id (comme le WHERE Postgres) ;
    s'il est absent, la ligne est visible sans condition (branche est_service).
    Indispensable pour qu'un test négatif (owner différent) échoue réellement si la
    route perd, inverse ou casse son filtre owner_id.

    Deux `execute()` sont attendus par get_venture : la SELECT venture (rang 0),
    soumise à la règle ci-dessus ; puis la SELECT members (rang 1), sans rapport
    avec l'ownership — toujours vide ici, aucun test de ce fichier n'inspecte les
    members.
    """
    def __init__(self, venture):
        self._venture = venture
        self._n = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt=None, *a, **k):
        if self._n == 0:
            bound, has_filter = _bound_owner_id(stmt)
            visible = (not has_filter) or bound == self._venture.owner_id
            rows = [self._venture] if visible else []
        else:
            rows = []
        self._n += 1
        return _FakeResult(rows)

    async def commit(self):
        pass


class _FakeSessionPatch:
    """Même émulation « lecture du WHERE réel » que `_FakeSessionGet` ci-dessus,
    adaptée à update_venture (cf. app/routers/ventures.py) qui exécute une UPDATE
    (rang 0, résultat non lu par la route — le mock ignore ses rows) puis un
    refetch SELECT (rang 1) filtré par le MÊME `condition` que l'UPDATE : on
    inspecte donc le WHERE du refetch (rang 1) pour décider la visibilité, avec la
    même règle qu'en GET."""
    def __init__(self, venture):
        self._venture = venture
        self._n = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt=None, *a, **k):
        if self._n == 0:
            rows = []
        else:
            bound, has_filter = _bound_owner_id(stmt)
            visible = (not has_filter) or bound == self._venture.owner_id
            rows = [self._venture] if visible else []
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

    `_FakeSessionGet` ne connaît que `v` — elle lit la valeur d'owner_id réellement
    liée par la route dans son WHERE (voir la classe ci-dessus). Ici la route
    construit `owner_id == "pas-le-owner"` (le `user.sub` de l'override
    dependency_overrides ci-dessous) ; comme `v.owner_id` vaut `quelqu-un-d-autre`
    (`_mk_venture` par défaut), la ligne est structurellement invisible : ce test
    échouerait réellement si la route perdait, inversait ou cassait son filtre
    owner_id — le mock n'a rien décidé à l'avance.
    """
    from app.auth import UserContext as UC, get_current_user as gcu
    v = _mk_venture()
    app.dependency_overrides[gcu] = lambda: UC(sub="pas-le-owner", nom="X",
                                               avatar_emoji="👤", org_id=None)
    ventures_mod.SessionLocal = lambda: _FakeSessionGet(v)
    r = await client.get(f"/api/ventures/{v.id}")
    app.dependency_overrides.clear()
    assert r.status_code == 404


async def test_get_venture_le_compte_de_service_lit_une_venture_d_autrui(client, app):
    v = _mk_venture()
    app.dependency_overrides[get_current_user] = _service_user
    ventures_mod.SessionLocal = lambda: _FakeSessionGet(v)
    r = await client.get(f"/api/ventures/{v.id}")
    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["auditId"] == "audit-1"


async def test_patch_venture_le_compte_de_service_ecrit_une_venture_d_autrui(client, app):
    v = _mk_venture(profil_entreprise={"clients": {"nb": 3}})
    app.dependency_overrides[get_current_user] = _service_user
    ventures_mod.SessionLocal = lambda: _FakeSessionPatch(v)
    r = await client.patch(f"/api/ventures/{v.id}",
                           json={"profilEntreprise": {"clients": {"nb": 3}}})
    app.dependency_overrides.clear()
    assert r.status_code == 200
    assert r.json()["profilEntreprise"] == {"clients": {"nb": 3}}


async def test_patch_venture_owner_id_different_404_pour_un_utilisateur_normal(client, app):
    """`_FakeSessionPatch` lit la même chose que `_FakeSessionGet` ci-dessus : la
    valeur d'owner_id réellement liée par la route dans le WHERE du refetch. Ici
    `pas-le-owner` (le `user.sub` de l'override) ne matche pas `v.owner_id`
    (`quelqu-un-d-autre`), donc le refetch post-UPDATE ne trouve structurellement
    rien — ce test échouerait réellement si la route perdait son filtre owner_id."""
    v = _mk_venture()
    app.dependency_overrides[get_current_user] = lambda: UserContext(
        sub="pas-le-owner", nom="X", avatar_emoji="👤", org_id=None)
    ventures_mod.SessionLocal = lambda: _FakeSessionPatch(v)
    r = await client.patch(f"/api/ventures/{v.id}", json={"nom": "Hack"})
    app.dependency_overrides.clear()
    # update_venture ne lève pas explicitement : v reste None après un UPDATE qui n'a
    # touché aucune ligne (WHERE owner_id ne matche pas) → la route rend `None`.
    assert r.json() is None
