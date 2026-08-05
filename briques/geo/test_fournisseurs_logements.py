"""Fournisseurs de logements : mock déterministe, normalisation DPE (payload figé),
bascule env — même motif que test_fournisseurs.py (B2B)."""
import pytest

import domaine
import fournisseurs_logements as fl

ZONE = {"id": "zone-test-logements", "nom": "Carcassonne", "type": "logement",
        "communes": [{"code": "11069", "nom": "Carcassonne"}],
        "parametres": {"grades_dpe": ["E", "F", "G"]},
        "lat_min": 43.15, "lon_min": 2.30, "lat_max": 43.25, "lon_max": 2.40,
        "derniere_ingestion": None}


def test_mock_est_deterministe_et_couvre_les_grades_demandes():
    a = fl.MockLogements().logements_recents(ZONE)
    b = fl.MockLogements().logements_recents(ZONE)
    assert a == b and len(a) >= 5
    for objet in a:
        assert objet["type"] == "logement"
        assert ZONE["lat_min"] <= objet["latitude"] <= ZONE["lat_max"]
        assert ZONE["lon_min"] <= objet["longitude"] <= ZONE["lon_max"]
        assert objet["source"] == "simule-logement" and objet["ref_externe"]
        assert objet["metadata"]["grade_dpe"] in {"E", "F", "G"}
        assert "nom" not in objet["metadata"] and "proprietaire" not in objet["metadata"]


def test_mock_couvre_les_trois_pastilles():
    from datetime import datetime, timezone
    maintenant = datetime.now(timezone.utc)
    pastilles = {domaine.pastille_fraicheur("logement", o["date_reference"], maintenant)
                 for o in fl.MockLogements().logements_recents(ZONE)}
    assert pastilles == {"rouge", "orange", "bleu"}


def test_mock_traite_toute_zone():
    assert fl.MockLogements().peut_traiter(ZONE) is None
    assert fl.MockLogements().peut_traiter({**ZONE, "communes": []}) is None
