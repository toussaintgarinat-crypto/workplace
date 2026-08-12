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


def _mock_config_de(monkeypatch, config: dict):
    def _faux_config_de(tenant, source_id):
        return "source-harvest", config, ["time_entries"]
    monkeypatch.setattr(mappeurs.stockage, "config_de", _faux_config_de)


def _mock_forge_get_venture_audit(monkeypatch, audit_id: str):
    async def _faux_get(self, url, **kw):
        return _ReponseHttpx(200, {"id": "vt-a", "auditId": audit_id, "profilEntreprise": {}})
    monkeypatch.setattr(httpx.AsyncClient, "get", _faux_get)


async def test_mapper_compta_calcule_un_cout_horaire_par_pole(monkeypatch):
    _mock_pont_extraire(monkeypatch, {
        "time_entries": [
            {"id": 1, "hours": 4.0, "billable_rate": 40.0,
             "project": {"name": "Vente terrain"}, "task": {"name": "Prospection"}},
            {"id": 2, "hours": 2.0, "billable_rate": 60.0,
             "project": {"name": "Vente terrain"}, "task": {"name": "Prospection"}},
            {"id": 3, "hours": 8.0, "billable_rate": 25.0,
             "project": {"name": "Compta interne"}, "task": {"name": "Facturation"}},
        ],
    })
    _mock_config_de(monkeypatch, {
        "mapping_poles": {"Vente terrain": "commercial", "Compta interne": "administratif"}})
    _mock_forge_get_venture_audit(monkeypatch, "audit-1")

    captures = []
    async def _faux_post(self, url, **kw):
        captures.append((url, kw.get("json")))
        return _ReponseHttpx(200, {"id": "audit-1", "statut_roi": "termine"})
    monkeypatch.setattr(httpx.AsyncClient, "post", _faux_post)

    await mappeurs._mapper_compta("alice", 2, "vt-a", "schema2")

    url, corps = captures[0]
    assert url.endswith("/audits/audit-1/chiffrer")
    # commercial : (4*40 + 2*60) / 6 = 46.666...
    assert corps["cout_horaire"]["commercial"] == pytest.approx(46.666, rel=1e-3)
    assert corps["cout_horaire"]["administratif"] == 25.0
    assert "production" not in corps["cout_horaire"]  # aucune entrée mappée à ce pôle


async def test_mapper_compta_ignore_les_entrees_sans_mapping_de_pole(monkeypatch):
    _mock_pont_extraire(monkeypatch, {
        "time_entries": [{"id": 1, "hours": 3.0, "billable_rate": 50.0,
                          "project": {"name": "Projet inconnu"}, "task": {"name": "?"}}]})
    _mock_config_de(monkeypatch, {"mapping_poles": {"Vente terrain": "commercial"}})
    _mock_forge_get_venture_audit(monkeypatch, "audit-1")
    captures = []
    async def _faux_post(self, url, **kw):
        captures.append(kw.get("json"))
        return _ReponseHttpx(200, {})
    monkeypatch.setattr(httpx.AsyncClient, "post", _faux_post)

    await mappeurs._mapper_compta("alice", 2, "vt-a", "schema2")
    assert captures[0]["cout_horaire"] == {}  # rien de mappable ⇒ dict vide, jamais bloquant


async def test_mapper_compta_sans_audit_id_leve(monkeypatch):
    _mock_pont_extraire(monkeypatch, {"time_entries": []})
    _mock_config_de(monkeypatch, {"mapping_poles": {}})
    _mock_forge_get_venture_audit(monkeypatch, None)
    with pytest.raises(mappeurs.MappingEchoue, match="audit_id"):
        await mappeurs._mapper_compta("alice", 2, "vt-a", "schema2")


async def test_mapper_apres_sync_dispatch_vers_crm(monkeypatch):
    appele = []
    async def _faux_crm(tenant, source_id, venture_id, schema):
        appele.append(("crm", tenant, source_id, venture_id, schema))
    monkeypatch.setattr(mappeurs, "_mapper_crm", _faux_crm)
    monkeypatch.setattr(mappeurs.stockage, "venture_id_de", lambda sid: "vt-a")
    enregistres = []
    monkeypatch.setattr(mappeurs.stockage, "enregistrer_mapping",
                        lambda sid, statut, erreur=None: enregistres.append((sid, statut, erreur)))

    await mappeurs.mapper_apres_sync("alice", 1, "source-hubspot", 99, "schema1")
    assert appele == [("crm", "alice", 1, "vt-a", "schema1")]
    assert enregistres == [(99, "ok", None)]


async def test_mapper_apres_sync_dispatch_vers_compta(monkeypatch):
    appele = []
    async def _faux_compta(tenant, source_id, venture_id, schema):
        appele.append("compta")
    monkeypatch.setattr(mappeurs, "_mapper_compta", _faux_compta)
    monkeypatch.setattr(mappeurs.stockage, "venture_id_de", lambda sid: "vt-a")
    monkeypatch.setattr(mappeurs.stockage, "enregistrer_mapping", lambda *a, **k: None)

    await mappeurs.mapper_apres_sync("alice", 2, "source-harvest", 100, "schema2")
    assert appele == ["compta"]


async def test_mapper_apres_sync_connecteur_non_mappable_ne_fait_rien(monkeypatch):
    """source-faker, source-github... : hors des deux listes blanches, jamais mappé."""
    appele = []
    monkeypatch.setattr(mappeurs, "_mapper_crm", lambda *a: appele.append("crm"))
    monkeypatch.setattr(mappeurs, "_mapper_compta", lambda *a: appele.append("compta"))
    enregistres = []
    monkeypatch.setattr(mappeurs.stockage, "enregistrer_mapping",
                        lambda *a, **k: enregistres.append(a))

    await mappeurs.mapper_apres_sync("alice", 3, "source-faker", 101, "schema3")
    assert appele == []
    assert enregistres == []  # rien à journaliser : ce n'est même pas une tentative


async def test_mapper_apres_sync_sans_venture_id_journalise_echec(monkeypatch):
    monkeypatch.setattr(mappeurs.stockage, "venture_id_de", lambda sid: None)
    enregistres = []
    monkeypatch.setattr(mappeurs.stockage, "enregistrer_mapping",
                        lambda sid, statut, erreur=None: enregistres.append((sid, statut, erreur)))

    await mappeurs.mapper_apres_sync("alice", 1, "source-hubspot", 99, "schema1")
    assert enregistres[0][1] == "echec"
    assert "venture_id" in enregistres[0][2]


async def test_mapper_apres_sync_capture_une_exception_du_mappeur(monkeypatch):
    """Le principe best-effort central du sprint : le mappeur explose, la sync ne le
    sait jamais (déjà `ok` avant cet appel, cf. Task 10 Step 4 côté main.py)."""
    async def _casse(*a):
        raise mappeurs.MappingEchoue("table contacts absente")
    monkeypatch.setattr(mappeurs, "_mapper_crm", _casse)
    monkeypatch.setattr(mappeurs.stockage, "venture_id_de", lambda sid: "vt-a")
    enregistres = []
    monkeypatch.setattr(mappeurs.stockage, "enregistrer_mapping",
                        lambda sid, statut, erreur=None: enregistres.append((sid, statut, erreur)))

    await mappeurs.mapper_apres_sync("alice", 1, "source-hubspot", 99, "schema1")
    assert enregistres == [(99, "echec", "table contacts absente")]


async def test_mapper_apres_sync_capture_une_exception_totalement_inattendue(monkeypatch):
    """Pas seulement MappingEchoue : n'importe quelle exception (bug, panne réseau
    imprévue) doit rester best-effort, jamais remonter à `_syncer`."""
    async def _casse(*a):
        raise ValueError("boom inattendu")
    monkeypatch.setattr(mappeurs, "_mapper_crm", _casse)
    monkeypatch.setattr(mappeurs.stockage, "venture_id_de", lambda sid: "vt-a")
    enregistres = []
    monkeypatch.setattr(mappeurs.stockage, "enregistrer_mapping",
                        lambda sid, statut, erreur=None: enregistres.append((sid, statut, erreur)))

    await mappeurs.mapper_apres_sync("alice", 1, "source-hubspot", 99, "schema1")
    assert enregistres[0][1] == "echec"
    assert "boom inattendu" in enregistres[0][2]
