"""Import en lot de prospects dans le CRM (S169) — dé-doublonnage + traduction en lead.

Le core Forge est mocké (aucun réseau, aucun Keycloak) : `_resoudre_pole_crm` et
`_appel_protege` sont remplacés par un faux magasin de leads en mémoire.
"""
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)


class _Resp:
    def __init__(self, corps, status=200):
        self.status_code, self._c, self.text = status, corps, ""

    def json(self):
        return self._c


def _install_faux_core(monkeypatch, existants):
    """Installe un core Forge simulé ; renvoie le magasin de leads (mutable) pour assertions."""
    store = list(existants)

    async def faux_resoudre(_cl):
        return "pole1"

    async def faux_appel(_cl, methode, chemin, **kw):
        if methode == "GET" and chemin.endswith("/crm"):
            return _Resp(list(store))
        if methode == "POST" and chemin.endswith("/crm"):
            lead = dict(kw.get("json") or {})
            lead["id"] = f"lead-{len(store) + 1}"
            store.append(lead)
            return _Resp(lead)
        return _Resp({})

    monkeypatch.setattr(main, "_resoudre_pole_crm", faux_resoudre)
    monkeypatch.setattr(main, "_appel_protege", faux_appel)
    return store


def test_import_lot_cree_et_enrichit_les_notes(monkeypatch):
    store = _install_faux_core(monkeypatch, [])
    r = client.post("/crm/import-lot", json={"prospects": [
        {"nom": "Boulangerie A", "entreprise": "Boulangerie A", "email": "a@a.fr",
         "site": "https://a.fr", "naf": "56.10", "commune": "Castres", "ref_externe": "111"},
        {"entreprise": "Garage B", "telephone": "05 63 00 00 00"},
    ]})
    assert r.status_code == 200
    d = r.json()
    assert d["crees"] == 2 and d["doublons"] == 0 and d["ignores"] == 0
    assert d["statut"] == "à contacter"
    # Les infos de veille sont versées dans les notes du lead + statut de départ appliqué.
    lead_a = next(l for l in store if l["entreprise"] == "Boulangerie A")
    assert "Site : https://a.fr" in lead_a["notes"] and "SIREN : 111" in lead_a["notes"]
    assert lead_a["statut"] == "à contacter"


def test_import_lot_dedoublonne_contre_existant(monkeypatch):
    _install_faux_core(monkeypatch, [
        {"id": "x", "nom": "Boulangerie A", "entreprise": "Boulangerie A", "email": "a@a.fr"}])
    d = client.post("/crm/import-lot", json={"prospects": [
        {"entreprise": "Boulangerie A", "email": "a@a.fr"},   # doublon par email
        {"entreprise": "Boulangerie A"},                       # doublon par entreprise
        {"entreprise": "Nouvelle C", "email": "c@c.fr"},       # neuf
    ]}).json()
    assert d["crees"] == 1 and d["doublons"] == 2


def test_import_lot_dedoublonne_dans_le_lot(monkeypatch):
    _install_faux_core(monkeypatch, [])
    d = client.post("/crm/import-lot", json={"prospects": [
        {"entreprise": "Meme Boite", "email": "x@meme.fr"},
        {"entreprise": "Meme Boite", "email": "x@meme.fr"},   # même email
        {"entreprise": "Meme Boite"},                          # même entreprise
    ]}).json()
    assert d["crees"] == 1 and d["doublons"] == 2


def test_import_lot_ignore_les_prospects_sans_nom(monkeypatch):
    _install_faux_core(monkeypatch, [])
    d = client.post("/crm/import-lot", json={"prospects": [
        {"email": "anonyme@x.fr"},   # ni nom ni entreprise → inexploitable
        {"nom": "Valide"},
    ]}).json()
    assert d["crees"] == 1 and d["ignores"] == 1


def test_import_lot_statut_personnalise(monkeypatch):
    _install_faux_core(monkeypatch, [])
    d = client.post("/crm/import-lot",
                    json={"prospects": [{"nom": "Z"}], "statut": "contacté"}).json()
    assert d["crees"] == 1 and d["statut"] == "contacté"


def test_import_lot_refuse_liste_vide(monkeypatch):
    _install_faux_core(monkeypatch, [])
    assert client.post("/crm/import-lot", json={"prospects": []}).status_code == 422
    assert client.post("/crm/import-lot", json={}).status_code == 422
