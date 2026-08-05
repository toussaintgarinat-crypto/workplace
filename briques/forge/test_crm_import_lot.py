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


def test_prospect_vers_lead_logement_jamais_de_nom_de_personne():
    from main import _prospect_vers_lead
    lead = _prospect_vers_lead({
        "adresse": "12 Rue des Lilas, Castres", "commune": "Castres",
        "code_postal": "81100", "grade_dpe": "F", "surface_m2": 90.0,
        "periode_construction": "avant 1948", "ref_externe": "2611E0067705R",
    }, statut="à contacter")
    assert lead["nom"] == "Occupant — 12 Rue des Lilas, Castres"
    assert lead.get("entreprise") is None
    assert lead.get("email") is None and lead.get("telephone") is None
    assert "Grade DPE : F" in lead["notes"]
    assert "Surface : 90.0 m²" in lead["notes"]
    assert "Période de construction : avant 1948" in lead["notes"]
    assert "DPE : 2611E0067705R" in lead["notes"]
    assert lead["statut"] == "à contacter"


def test_import_lot_dedoublonne_logements_par_adresse(monkeypatch):
    _install_faux_core(monkeypatch, [])
    d = client.post("/crm/import-lot", json={"prospects": [
        {"adresse": "12 Rue des Lilas, Castres", "grade_dpe": "F"},
        {"adresse": "12 Rue des Lilas, Castres", "grade_dpe": "F"},  # même adresse
        {"adresse": "4 Impasse du Moulin, Castres", "grade_dpe": "G"},
    ]}).json()
    assert d["crees"] == 2 and d["doublons"] == 1


def test_prospect_vers_lead_logement_jamais_de_notes_personnelles():
    """Contrainte légale : aucun nom de personne ne doit jamais paraître dans un lead logement,
    y compris via la passthrough du champ 'notes' du prospect. Les notes de lead logement doivent
    rester strictement techniques (adresse, DPE, surface...) et code-authored."""
    from main import _prospect_vers_lead
    lead = _prospect_vers_lead({
        "adresse": "12 Rue des Lilas, Castres",
        "commune": "Castres",
        "code_postal": "81100",
        "grade_dpe": "F",
        "surface_m2": 90.0,
        "periode_construction": "avant 1948",
        "ref_externe": "2611E0067705R",
        "notes": "Propriétaire : Jean Dupont, tél 06 12 34 56 78",  # Tentative d'injection de nom
    }, statut="à contacter")

    # Le nom de personne NE doit JAMAIS apparaître dans les notes du lead
    assert "Jean Dupont" not in lead["notes"]
    assert "06 12 34 56 78" not in lead["notes"]
    assert "Propriétaire" not in lead["notes"]

    # Les notes techniques code-authored doivent rester présentes
    assert "Grade DPE : F" in lead["notes"]
    assert "Surface : 90.0 m²" in lead["notes"]
    assert "Importé depuis la veille geo (logement)" in lead["notes"]


def test_import_lot_accepte_prospects_logement_sans_nom(monkeypatch):
    store = _install_faux_core(monkeypatch, [])
    d = client.post("/crm/import-lot", json={"prospects": [
        {"adresse": "12 Rue des Lilas, Castres", "commune": "Castres",
         "grade_dpe": "F", "surface_m2": 90.0, "ref_externe": "2611E0067705R"},
        {"adresse": "4 Impasse du Moulin, Castres", "grade_dpe": "G"},
    ]}).json()
    assert d["crees"] == 2 and d["ignores"] == 0
    assert all(l["nom"].startswith("Occupant — ") for l in store)
    assert all(l.get("entreprise") in (None, "") for l in store)


def test_import_lot_prospects_lead_id_present_dans_la_reponse(monkeypatch):
    """Contrat requis par le futur moteur postal (mail) : chaque prospect créé doit
    porter son `id` de lead CRM dans la réponse, pour pouvoir qualifier le bon lead à
    la réception d'une réponse. Déjà vrai via `_resume_lead` — ce test le fige en
    non-régression explicite plutôt que de compter sur un effet de bord non testé."""
    _install_faux_core(monkeypatch, [])
    d = client.post("/crm/import-lot", json={"prospects": [
        {"adresse": "9 Rue Haute, Castres", "grade_dpe": "E"},
    ]}).json()
    assert d["prospects"][0]["id"]


def test_import_lot_toujours_ignore_prospect_totalement_vide(monkeypatch):
    _install_faux_core(monkeypatch, [])
    d = client.post("/crm/import-lot", json={"prospects": [
        {"email": "anonyme@x.fr"},   # ni nom, ni entreprise, ni adresse
        {"adresse": "  "},           # adresse vide après trim
    ]}).json()
    assert d["crees"] == 0 and d["ignores"] == 2
