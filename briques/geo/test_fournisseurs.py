"""Fournisseurs : mock déterministe, normalisation Sirene (payload figé), bascule env."""
import fournisseurs
import domaine

ZONE = {"id": "zone-test-0001", "nom": "Castres", "type": "entreprise",
        "lat_min": 43.55, "lon_min": 2.10, "lat_max": 43.70, "lon_max": 2.35,
        "derniere_ingestion": None}

# Payload RÉEL (figé) de recherche-entreprises.api.gouv.fr — coordonnées en chaînes.
PAYLOAD_SIRENE = {
    "siren": "923456789",
    "nom_complet": "SOBAC DISTRIBUTION",
    "date_creation": "2026-05-12",
    "activite_principale": "46.75Z",
    "siege": {
        "latitude": "43.606",
        "longitude": "2.241",
        "activite_principale": "46.75Z",
        "adresse": "12 RUE DU MARCHE 81100 CASTRES",
        "date_creation": "2026-05-12",
    },
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


def test_normaliser_entreprise_payload_reel():
    objet = domaine.normaliser_entreprise(PAYLOAD_SIRENE)
    assert objet == {
        "type": "entreprise", "latitude": 43.606, "longitude": 2.241,
        "date_reference": "2026-05-12", "ref_externe": "923456789",
        "source": "recherche-entreprises",
        "metadata": {"nom": "SOBAC DISTRIBUTION", "naf": "46.75Z",
                     "adresse": "12 RUE DU MARCHE 81100 CASTRES"},
    }


def test_normaliser_entreprise_sans_geolocalisation_rend_none():
    assert domaine.normaliser_entreprise({"siren": "1", "siege": {}}) is None
    assert domaine.normaliser_entreprise({"siren": "1"}) is None
    hors_bornes = {"siren": "1", "siege": {"latitude": "95.0", "longitude": "2.0"}}
    assert domaine.normaliser_entreprise(hors_bornes) is None


def test_bascule_fournisseur_par_env(monkeypatch):
    monkeypatch.delenv("GEO_FOURNISSEUR", raising=False)
    assert fournisseurs.etat_config()["fournisseur"] == "mock"
    assert isinstance(fournisseurs.fournisseur(), fournisseurs.Mock)
    monkeypatch.setenv("GEO_FOURNISSEUR", "reel")
    etat = fournisseurs.etat_config()
    assert etat["fournisseur"] == "recherche-entreprises" and etat["configure"]
    assert isinstance(fournisseurs.fournisseur(), fournisseurs.RechercheEntreprises)
