"""Fournisseurs de logements : mock déterministe, normalisation DPE (payload figé),
bascule env — même motif que test_fournisseurs.py (B2B)."""
import httpx
import pytest

import domaine
import fournisseurs_logements as fl

ZONE = {"id": "zone-test-logements", "nom": "Carcassonne", "type": "logement",
        "communes": [{"code": "11069", "nom": "Carcassonne"}],
        "parametres": {"grades_dpe": ["E", "F", "G"]},
        "lat_min": 43.15, "lon_min": 2.30, "lat_max": 43.25, "lon_max": 2.40,
        "derniere_ingestion": None}


# Payload RÉEL (figé, vérifié LIVE 2026-08-05, dataset dpe03existant, 2 résultats).
PAGE_1_ADEME = {
    "total": 422,
    "next": "https://data.ademe.fr/data-fair/api/v1/datasets/meg-83tjwtg8dyz4vv7h1dqe/"
            "lines?size=1&after=CURSEUR-FICTIF",
    "results": [{
        "numero_dpe": "2611E0206181R", "etiquette_dpe": "E",
        "adresse_ban": "1 Rue Fictive 11000 Carcassonne", "nom_commune_ban": "Carcassonne",
        "code_postal_ban": "11000", "coordonnee_cartographique_x_ban": 648048.69,
        "coordonnee_cartographique_y_ban": 6234349.45,
        "date_etablissement_dpe": "2025-01-01", "periode_construction": "avant 1948",
        "surface_habitable_logement": 88.7,
    }],
}
PAGE_2_ADEME_DERNIERE = {"total": 422, "results": [{
    "numero_dpe": "2111E0136972P", "etiquette_dpe": "F",
    "adresse_ban": "2 Rue Fictive 11000 Carcassonne", "nom_commune_ban": "Carcassonne",
    "code_postal_ban": "11000", "coordonnee_cartographique_x_ban": 648048.69,
    "coordonnee_cartographique_y_ban": 6234349.45,
    "date_etablissement_dpe": "2025-01-02", "periode_construction": "avant 1948",
    "surface_habitable_logement": 60.0,
}]}   # pas de clé "next" = dernière page


class _FauxClientAdeme:
    """Simule httpx.Client : 1er GET → PAGE_1 (a un `next`), 2e GET (sur l'URL `next`
    reçue) → PAGE_2 (sans `next`, la boucle s'arrête). Vérifie que la pagination utilise
    le bon URL (celui dans PAGE_1["next"])."""
    def __init__(self, *a, **k):
        self.appels = 0
        self.appels_enregistres = []  # Liste de tuples (url, params) pour chaque appel

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        self.appels += 1
        self.appels_enregistres.append((url, params))  # Enregistre l'URL et params
        # 1er appel : retourne PAGE_1 (qui contient un "next" URL)
        if self.appels == 1:
            return httpx.Response(200, json=PAGE_1_ADEME, request=httpx.Request("GET", url))
        # 2e+ appels : vérifie que c'est le bon URL (le "next" de PAGE_1)
        # Si on reçoit l'URL original une 2e fois, c'est une pagination cassée - retour PAGE_1 encore
        if url == PAGE_1_ADEME["next"]:
            # Pagination correcte : retourne la dernière page
            return httpx.Response(200, json=PAGE_2_ADEME_DERNIERE, request=httpx.Request("GET", url))
        else:
            # Pagination cassée : l'appel ne respecte pas le "next" URL, on retourne PAGE_1 à nouveau
            # (simulant un appel à l'URL original)
            return httpx.Response(200, json=PAGE_1_ADEME, request=httpx.Request("GET", url))


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


def test_mock_traite_zones_avec_communes():
    assert fl.MockLogements().peut_traiter(ZONE) is None
    # zones without communes are rejected (like DpeAdeme, for consistency)
    assert "commune" in fl.MockLogements().peut_traiter({**ZONE, "communes": []}).lower()


def test_dpe_ademe_pagine_par_curseur_jusqua_next_absent(monkeypatch):
    # Capture le client mocké pour vérifier qu'il a reçu 2 appels GET avec les bons params
    client_instance = None

    class _FauxClientAdemeCapture(_FauxClientAdeme):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            nonlocal client_instance
            client_instance = self

    monkeypatch.setattr(fl.httpx, "Client", _FauxClientAdemeCapture)
    objets = fl.DpeAdeme().logements_recents(ZONE)
    assert len(objets) == 2
    assert {o["ref_externe"] for o in objets} == {"2611E0206181R", "2111E0136972P"}
    assert all(o["type"] == "logement" for o in objets)
    # Vérifie que le client a effectué DEUX appels (première page + seconde page)
    assert client_instance.appels == 2
    # Vérifie que le DEUXIÈME appel utilise l'URL `next` de la première page avec params=None
    # (la page `next` embarque déjà tous les paramètres de requête)
    second_url, second_params = client_instance.appels_enregistres[1]
    assert second_url == PAGE_1_ADEME["next"], \
        f"Deuxième appel doit utiliser l'URL 'next' : attendu {PAGE_1_ADEME['next']}, got {second_url}"
    assert second_params is None, \
        f"Deuxième appel doit avoir params=None (next embarque les params) : got {second_params}"


def test_dpe_ademe_peut_traiter_exige_des_communes():
    sans_communes = {**ZONE, "communes": []}
    assert "commune" in fl.DpeAdeme().peut_traiter(sans_communes).lower()
    assert fl.DpeAdeme().peut_traiter(ZONE) is None


def test_bascule_fournisseur_logements_par_env(monkeypatch):
    monkeypatch.delenv("GEO_FOURNISSEUR_LOGEMENTS", raising=False)
    assert fl.etat_config_logements()["fournisseur"] == "mock-logements"
    assert isinstance(fl.fournisseur_logements(), fl.MockLogements)
    monkeypatch.setenv("GEO_FOURNISSEUR_LOGEMENTS", "reel")
    etat = fl.etat_config_logements()
    assert etat["fournisseur"] == "dpe-ademe" and etat["configure"]
    assert isinstance(fl.fournisseur_logements(), fl.DpeAdeme)
