"""Fournisseurs : mock déterministe, normalisation Sirene (payload figé), bascule env."""
import fournisseurs
import domaine

ZONE = {"id": "zone-test-0001", "nom": "Castres", "type": "entreprise", "naf": None,
        "lat_min": 43.55, "lon_min": 2.10, "lat_max": 43.70, "lon_max": 2.35,
        "derniere_ingestion": None}

# Payload RÉEL (figé, vérifié LIVE 2026-07-06 sur recherche-entreprises.api.gouv.fr) :
# l'API apparie les ÉTABLISSEMENTS proches — coordonnées/date/SIRET dans
# `matching_etablissements`, le siège pouvant être à l'autre bout de la France.
PAYLOAD_SIRENE = {
    "siren": "923456789",
    "nom_complet": "SOBAC DISTRIBUTION",
    "date_creation": "1998-03-01",
    "activite_principale": "46.75Z",
    "siege": {"latitude": "48.831", "longitude": "2.278"},   # Paris — PAS lui
    "matching_etablissements": [{
        "siret": "92345678900014",
        "latitude": "43.606",
        "longitude": "2.241",
        "date_creation": "2026-05-12",
        "activite_principale": "46.75Z",
        "adresse": "12 RUE DU MARCHE 81100 CASTRES",
        "libelle_commune": "CASTRES",
        "nom_commercial": "SOBAC CASTRES",
        "etat_administratif": "A",
    }],
}


def test_mock_est_deterministe_et_dans_la_bbox():
    a = fournisseurs.Mock().entreprises_recentes(ZONE)
    b = fournisseurs.Mock().entreprises_recentes(ZONE)
    assert a == b and len(a) >= 5
    for objet in a:
        assert ZONE["lat_min"] <= objet["latitude"] <= ZONE["lat_max"]
        assert ZONE["lon_min"] <= objet["longitude"] <= ZONE["lon_max"]
        assert objet["source"] == "simule" and objet["ref_externe"]


def test_mock_couvre_les_trois_pastilles():
    from datetime import datetime, timezone
    maintenant = datetime.now(timezone.utc)
    pastilles = {domaine.pastille_fraicheur("entreprise", o["date_reference"], maintenant)
                 for o in fournisseurs.Mock().entreprises_recentes(ZONE)}
    assert pastilles == {"rouge", "orange", "bleu"}


def test_normaliser_prend_l_etablissement_local_pas_le_siege():
    objet = domaine.normaliser_entreprise(PAYLOAD_SIRENE)
    assert objet == {
        "type": "entreprise", "latitude": 43.606, "longitude": 2.241,
        "date_reference": "2026-05-12",          # date de L'ÉTABLISSEMENT
        "ref_externe": "92345678900014",         # SIRET (pas le SIREN)
        "source": "recherche-entreprises",
        "metadata": {"nom": "SOBAC CASTRES", "naf": "46.75Z",
                     "adresse": "12 RUE DU MARCHE 81100 CASTRES",
                     "commune": "CASTRES", "siren": "923456789"},
    }


def test_normaliser_ecarte_l_etablissement_ferme():
    ferme = {**PAYLOAD_SIRENE,
             "matching_etablissements": [
                 {**PAYLOAD_SIRENE["matching_etablissements"][0],
                  "etat_administratif": "F"}]}
    assert domaine.normaliser_entreprise(ferme) is None


def test_normaliser_sans_geolocalisation_rend_none():
    assert domaine.normaliser_entreprise({"siren": "1"}) is None
    sans_coords = {"siren": "1", "matching_etablissements": [{"siret": "10001"}]}
    assert domaine.normaliser_entreprise(sans_coords) is None
    hors_bornes = {"siren": "1", "matching_etablissements": [
        {"latitude": "95.0", "longitude": "2.0"}]}
    assert domaine.normaliser_entreprise(hors_bornes) is None


def test_normaliser_replie_sur_le_siege_sans_matching():
    # Certains payloads (ex. /search minimal) n'ont que le siège : repli accepté.
    seul_siege = {"siren": "2", "nom_complet": "AU SIEGE",
                  "siege": {"latitude": "43.60", "longitude": "2.24",
                            "date_creation": "2026-06-01"}}
    objet = domaine.normaliser_entreprise(seul_siege)
    assert objet and objet["latitude"] == 43.60 and objet["ref_externe"] == "2"


def test_bascule_fournisseur_par_env(monkeypatch):
    monkeypatch.delenv("GEO_FOURNISSEUR", raising=False)
    assert fournisseurs.etat_config()["fournisseur"] == "mock"
    assert isinstance(fournisseurs.fournisseur(), fournisseurs.Mock)
    monkeypatch.setenv("GEO_FOURNISSEUR", "reel")
    etat = fournisseurs.etat_config()
    assert etat["fournisseur"] == "recherche-entreprises" and etat["configure"]
    assert isinstance(fournisseurs.fournisseur(), fournisseurs.RechercheEntreprises)


def test_peut_traiter_le_mock_traite_tout_le_reel_est_exigeant():
    reel, mock = fournisseurs.RechercheEntreprises(), fournisseurs.Mock()
    rayon_sans_naf = {**ZONE}
    assert mock.peut_traiter(rayon_sans_naf) is None
    assert "NAF" in reel.peut_traiter(rayon_sans_naf)
    assert reel.peut_traiter({**ZONE, "naf": "56.10A"}) is None
    assert reel.peut_traiter({**ZONE, "communes": [{"code": "81325", "nom": "V"}]}) is None
    # Associations : le filtre n'existe que sur /search → communes obligatoires.
    asso_rayon = {**ZONE, "type": "association", "naf": "94.99Z"}
    assert "associations" in reel.peut_traiter(asso_rayon).lower()
    asso_communes = {**asso_rayon, "communes": [{"code": "81065", "nom": "Castres"}]}
    assert reel.peut_traiter(asso_communes) is None


def test_mock_respecte_le_type_de_la_zone():
    objets = fournisseurs.Mock().entreprises_recentes({**ZONE, "type": "association"})
    assert {o["type"] for o in objets} == {"association"}


def test_normaliser_type_association_et_coordonnees_protegees():
    assert domaine.normaliser_entreprise(PAYLOAD_SIRENE,
                                         type_="association")["type"] == "association"
    # Vu LIVE sur des associations : coordonnées « [NON-DIFFUSIBLE] » → écarté, honnête.
    protege = {**PAYLOAD_SIRENE, "matching_etablissements": [
        {**PAYLOAD_SIRENE["matching_etablissements"][0],
         "latitude": "[NON-DIFFUSIBLE]", "longitude": "[NON-DIFFUSIBLE]"}]}
    assert domaine.normaliser_entreprise(protege) is None
