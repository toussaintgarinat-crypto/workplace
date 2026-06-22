"""Tests hors-ligne du composeur de bundles (S97) — catalogue cochable + liste des bundles.

Pures opérations disque sur des répertoires temporaires → aucun docker, aucun réseau.
Vérifie le filtrage (plateforme / sans port écartées) et la lecture des bundles existants.
"""
import json
import os

import tempfile

# `main` tire la chaîne LLM (GATEWAY_KEY requis) et un ledger SQLite (DB_PATH) à l'import ;
# valeurs factices/temporaires pour un import 100 % offline et hors conteneur.
os.environ.setdefault("GATEWAY_KEY", "test-offline")
os.environ.setdefault("DB_PATH", os.path.join(tempfile.gettempdir(), "test_generateur.db"))
os.environ.setdefault("LEDGER_PATH", os.path.join(tempfile.gettempdir(), "test_ledger.db"))

import main


def _ecrire_manifest(racine, nom, **champs):
    d = os.path.join(racine, nom)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"nom": nom, **champs}, f)


def test_catalogue_garde_metier_ecarte_plateforme(tmp_path):
    racine = str(tmp_path)
    _ecrire_manifest(racine, "restaurant", port=6010, version="0.11.0", description="Resto")
    _ecrire_manifest(racine, "paiements", port=6020, description="Argent")
    _ecrire_manifest(racine, "gateway", port=4001)      # plateforme → écartée
    _ecrire_manifest(racine, "generateur", port=5400)   # usine → écartée
    _ecrire_manifest(racine, "app-builder", port=None)   # plateforme + sans port

    cochables = main._lister_briques_cochables(racine)
    noms = [b["nom"] for b in cochables]

    assert noms == ["paiements", "restaurant"]  # trié, métier seulement
    resto = next(b for b in cochables if b["nom"] == "restaurant")
    assert resto["port"] == 6010 and resto["version"] == "0.11.0"


def test_brique_sans_port_ecartee(tmp_path):
    racine = str(tmp_path)
    _ecrire_manifest(racine, "front-pur", description="frontend sans service")  # pas de port
    _ecrire_manifest(racine, "mail", port=6030)

    noms = [b["nom"] for b in main._lister_briques_cochables(racine)]
    assert noms == ["mail"]


def test_lister_bundles_lit_les_bundle_json(tmp_path):
    export = str(tmp_path)
    for slug, client, briques in [("le-port", "Le Port", ["restaurant"]),
                                  ("vincept", "Vincept", ["restaurant", "paiements"])]:
        d = os.path.join(export, f"{slug}-bundle")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "bundle.json"), "w", encoding="utf-8") as f:
            json.dump({"client": client, "slug": slug, "briques": briques}, f)
    # Un dossier bruité (sans bundle.json) ne doit pas casser la lecture.
    os.makedirs(os.path.join(export, "apps_exportees"), exist_ok=True)

    bundles = main._lister_bundles(export)
    clients = sorted(b["client"] for b in bundles)
    assert clients == ["Le Port", "Vincept"]


def test_lister_bundles_repertoire_absent(tmp_path):
    assert main._lister_bundles(os.path.join(str(tmp_path), "nexiste-pas")) == []
