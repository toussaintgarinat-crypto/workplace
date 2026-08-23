"""Tests API de world-engine."""
import importlib
import os

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["statut"] == "ok"


def test_auth_rejette_cle_absente_quand_api_keys_configuree(monkeypatch):
    """Teste directement cle_api() pour vérifier le rejet d'une clé manquante/invalide."""
    monkeypatch.setenv("API_KEYS", "vraie-cle")
    importlib.reload(main)
    # Clé absente → rejet
    with pytest.raises(main.HTTPException) as exc:
        main.cle_api(x_api_key=None, authorization=None)
    assert exc.value.status_code == 401
    # Clé invalide → rejet
    with pytest.raises(main.HTTPException) as exc:
        main.cle_api(x_api_key="mauvaise-cle", authorization=None)
    assert exc.value.status_code == 401
    # Clé valide → acceptée
    result = main.cle_api(x_api_key="vraie-cle", authorization=None)
    assert result == "vraie-cle"
    # Bearer token valide → acceptée
    result = main.cle_api(x_api_key=None, authorization="Bearer vraie-cle")
    assert result == "vraie-cle"
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)


def test_sante_jamais_protegee_meme_avec_api_keys(monkeypatch):
    """/sante reste accessible sans clé, même si API_KEYS est configurée."""
    monkeypatch.setenv("API_KEYS", "vraie-cle")
    importlib.reload(main)
    c = TestClient(main.app)
    assert c.get("/sante").status_code == 200
    monkeypatch.delenv("API_KEYS", raising=False)
    importlib.reload(main)


PERSONNAGES_URL = "http://host.docker.internal:5900"

_FICHE_A = {"prenoms": "Théo", "date_naissance": "1985-03-10", "heure_naissance": "08:00",
            "latitude": 48.85, "longitude": 2.35, "utc_offset": 1.0}
_FICHE_B = {"prenoms": "Léa", "date_naissance": "1988-07-22", "heure_naissance": "16:20",
            "latitude": 45.76, "longitude": 4.83, "utc_offset": 2.0}


def _portrait_factice(dominante_planete="Mercure", dominante_signe="Vierge",
                       signe_dix_corps="Vierge") -> dict:
    """`signe_dix_corps` est appliqué IDENTIQUEMENT aux 10 corps (fixture minimale) —
    fait varier ce paramètre entre 2 appels pour tester la comparaison d'hérédité."""
    return {
        "traditions": {"signe_solaire": {"nom": "Vierge"}},
        "portrait": {"archetype": "Le Gardien", "forces": ["Sagesse", "Stabilité", "Émotivité"],
                     "faiblesse": "Combativité"},
        "theme_complet": {
            "dominantes": {"planete": {"dominante": dominante_planete},
                            "signe": {"dominant": dominante_signe}},
            "dix_corps": {c: {"signe": signe_dix_corps} for c in
                          ["Soleil", "Lune", "Mercure", "Vénus", "Mars", "Jupiter",
                           "Saturne", "Uranus", "Neptune", "Pluton"]},
        },
        "empreinte": [], "glossaire": [],
    }


@respx.mock
def test_genome_croiser_chemin_heureux():
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        side_effect=[httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge")),   # parent A
                     httpx.Response(200, json=_portrait_factice("Mars", "Bélier", "Bélier")),        # parent B
                     httpx.Response(200, json=_portrait_factice("Mercure", "Vierge", "Vierge"))])    # enfant
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": [{"signe": "Vierge", "score": 5}]}))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "prenoms_enfant": "Nova", "latitude_enfant": 43.6, "longitude_enfant": 1.44,
        "annee_enfant": 2015, "mutation_rate": 0.0})
    assert r.status_code == 200
    data = r.json()
    assert data["enfant"]["theme_complet"]["dominantes"]["signe"]["dominant"] == "Vierge"
    assert data["heredite"]["resume"] == {"A": 10, "B": 0, "commun": 0, "mutation": 0}
    assert data["mutation_survenue"] is False
    assert "description_genome" in data


@respx.mock
def test_genome_croiser_personnages_injoignable_502():
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(side_effect=httpx.ConnectError("down"))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "latitude_enfant": 43.6, "longitude_enfant": 1.44})
    assert r.status_code == 502


@respx.mock
def test_genome_croiser_fiche_parent_invalide_propage_422():
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(422, json={"detail": "Fiche insuffisante."}))
    r = client.post("/genome/croiser", json={
        "parent_a": {"prenoms": "X"}, "parent_b": _FICHE_B,
        "latitude_enfant": 43.6, "longitude_enfant": 1.44})
    assert r.status_code == 422


@respx.mock
def test_genome_croiser_aucun_signe_reconnu_422():
    respx.post(f"{PERSONNAGES_URL}/holistique/portrait").mock(
        return_value=httpx.Response(200, json=_portrait_factice()))
    respx.post(f"{PERSONNAGES_URL}/holistique/recherche-inverse").mock(
        return_value=httpx.Response(200, json={"signes": []}))
    r = client.post("/genome/croiser", json={
        "parent_a": _FICHE_A, "parent_b": _FICHE_B,
        "latitude_enfant": 43.6, "longitude_enfant": 1.44})
    assert r.status_code == 422
