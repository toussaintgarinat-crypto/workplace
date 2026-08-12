"""Mappeurs best-effort post-sync (S230) : CRM (HubSpot → Forge) et compta (Harvest →
audit ROI). Aucun réseau réel : `pont.executer` et les appels httpx sortants sont mockés.
"""
import httpx
import pytest

import mappeurs


class _ReponseHttpx:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erreur", request=None, response=self)


@pytest.fixture(autouse=True)
def _sans_reseau_reel(monkeypatch):
    """Filet : si un test oublie de mocker un point de sortie, on le sait immédiatement
    plutôt que de laisser une requête réelle partir en silence."""
    async def _interdit(*a, **k):
        raise AssertionError("appel réseau non mocké dans un test de mappeurs.py")
    monkeypatch.setattr(httpx.AsyncClient, "post", _interdit)
    monkeypatch.setattr(httpx.AsyncClient, "get", _interdit)


def _mock_pont_extraire(monkeypatch, par_flux: dict[str, list[dict]]):
    async def _faux_executer(job, timeout=None):
        assert job["action"] == "extraire"
        flux = job["flux_extrait"]
        if flux not in par_flux:
            return {"ok": False, "erreur": f"flux « {flux} » absent du cache"}
        return {"ok": True, "flux": flux, "lignes": par_flux[flux]}
    monkeypatch.setattr(mappeurs.pont, "executer", _faux_executer)


def _mock_forge_post(monkeypatch, capture: list):
    async def _faux_post(self, url, **kw):
        capture.append((url, kw.get("json")))
        return _ReponseHttpx(200, {"ok": True, "crees": len(kw["json"]["prospects"]),
                                   "doublons": 0, "ignores": 0})
    monkeypatch.setattr(httpx.AsyncClient, "post", _faux_post)


def _mock_forge_get_venture(monkeypatch, profil: dict):
    async def _faux_get(self, url, **kw):
        return _ReponseHttpx(200, {"id": "vt-a", "auditId": "audit-1", "profilEntreprise": profil})
    monkeypatch.setattr(httpx.AsyncClient, "get", _faux_get)


async def test_mapper_crm_transforme_contacts_et_deals_en_prospects(monkeypatch):
    _mock_pont_extraire(monkeypatch, {
        "contacts": [{"id": "1", "properties": {"firstname": "Alice", "lastname": "Durand",
                                                "email": "alice@x.fr", "phone": "0600000000",
                                                "company": "Acme"}}],
        "deals": [{"id": "d1", "properties": {"dealname": "Contrat annuel", "amount": "5000"}}],
    })
    captures = []
    _mock_forge_post(monkeypatch, captures)
    _mock_forge_get_venture(monkeypatch, {"clients": {"nb": 0}})

    patchs = []
    async def _faux_patch(self, url, **kw):
        patchs.append((url, kw.get("json")))
        return _ReponseHttpx(200, {"id": "vt-a"})
    monkeypatch.setattr(httpx.AsyncClient, "patch", _faux_patch)

    await mappeurs._mapper_crm("alice", 1, "vt-a", "schema1")

    url, corps = captures[0]
    assert url.endswith("/crm/import-lot")
    assert corps["venture_id"] == "vt-a"
    assert len(corps["prospects"]) == 2
    contact = next(p for p in corps["prospects"] if p["email"] == "alice@x.fr")
    assert contact["nom"] == "Alice Durand"
    assert contact["entreprise"] == "Acme"
    deal = next(p for p in corps["prospects"] if p is not contact)
    assert "Contrat annuel" in deal["notes"]

    # profil_entreprise.clients fusionné, pas écrasé (les autres clés survivent).
    assert patchs[0][1]["profilEntreprise"]["clients"]["nb"] == 2


async def test_mapper_crm_incremente_le_compteur_existant_et_conserve_les_autres_categories(monkeypatch):
    """Fusion non destructive (motif S227/S228, `_fusionner_qualitatif`) + comptage
    CUMULATIF : une sync incrémentale HubSpot ne rapporte qu'un DELTA de contacts, pas
    le total connu chez le tiers — écraser `clients.nb` avec ce delta ferait régresser
    le profil à chaque sync calme."""
    _mock_pont_extraire(monkeypatch, {
        "contacts": [{"id": "1", "properties": {"firstname": "Bob", "lastname": "X",
                                                "email": "bob@x.fr"}}],
        "deals": [],
    })
    captures = []
    _mock_forge_post(monkeypatch, captures)
    _mock_forge_get_venture(monkeypatch, {"organisation": ["SARL"], "clients": {"nb": 5}})

    patchs = []
    async def _faux_patch(self, url, **kw):
        patchs.append(kw.get("json"))
        return _ReponseHttpx(200, {})
    monkeypatch.setattr(httpx.AsyncClient, "patch", _faux_patch)

    await mappeurs._mapper_crm("alice", 1, "vt-a", "schema1")
    assert patchs[0]["profilEntreprise"]["organisation"] == ["SARL"]
    assert patchs[0]["profilEntreprise"]["clients"]["nb"] == 6  # 5 existants + 1 nouveau


async def test_mapper_crm_sans_nouveau_prospect_ne_touche_pas_a_forge(monkeypatch):
    """Aucun contact/deal neuf ce tour (sync incrémentale calme) : ni lead factice créé
    dans le CRM pour satisfaire la validation « liste non vide » de crm/import-lot, ni
    écrasement du compteur `clients.nb` avec un delta de zéro."""
    _mock_pont_extraire(monkeypatch, {"contacts": [], "deals": []})
    appels = []

    async def _traqueur(self, url, **kw):
        appels.append(url)
        return _ReponseHttpx(200, {})
    monkeypatch.setattr(httpx.AsyncClient, "post", _traqueur)
    monkeypatch.setattr(httpx.AsyncClient, "get", _traqueur)
    monkeypatch.setattr(httpx.AsyncClient, "patch", _traqueur)

    await mappeurs._mapper_crm("alice", 1, "vt-a", "schema1")
    assert appels == []


async def test_mapper_crm_flux_absent_du_cache_leve(monkeypatch):
    """Le dispatcher (Task 10) attrape ceci et journalise `mapping_echoue` — le mappeur
    lui-même reste honnête et lève plutôt que d'avaler l'erreur."""
    _mock_pont_extraire(monkeypatch, {})  # ni contacts ni deals synchronisés
    with pytest.raises(mappeurs.MappingEchoue, match="contacts"):
        await mappeurs._mapper_crm("alice", 1, "vt-a", "schema1")
