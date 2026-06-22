"""Tests hors-ligne du moteur de bundle (S95).

Pures données en entrée (manifests + composes en mémoire) → aucun docker, aucun réseau.
Vérifie : composition, remap des ports, réécriture des URLs vers les noms de service,
résolution des dépendances (métier tirées, plateforme ignorées), garde-fous (collision /
brique sans port), idempotence, bundle vivant (ajout préserve l'existant) et écriture disque.
"""
import json

import pytest

import bundle


def _manifests():
    return {
        "restaurant": {"nom": "restaurant", "port": 6010, "depends_on": []},
        "paiements": {"nom": "paiements", "port": 6020, "depends_on": []},
        "vision": {"nom": "vision", "port": 5960, "depends_on": []},
        "mail": {"nom": "mail", "port": 6030, "depends_on": ["vision"]},
    }


def _composes():
    return {
        "restaurant": {"services": {"restaurant": {
            "build": ".", "image": "workplace/restaurant:0.10.0",
            "container_name": "workplace_restaurant",
            "env_file": [{"path": "../../.env", "required": False}],
            "ports": ["6010:6010"],
            "environment": [
                "PORT=6010", "RESTAURANT_DB=/data/restaurant.db",
                "GATEWAY_URL=${GATEWAY_URL:-http://host.docker.internal:4001}",
                "VISION_URL=${VISION_URL:-http://host.docker.internal:5960}",
            ],
            "volumes": ["restaurant_data:/data"],
            "restart": "unless-stopped",
            "depends_on": ["autre"],
            "healthcheck": {"test": ["CMD", "true"]},
        }}},
        "paiements": {"services": {"paiements": {
            "build": ".", "image": "workplace/paiements:0.1.0",
            "container_name": "workplace_paiements",
            "ports": ["6020:6020"],
            "environment": ["PORT=6020", "GATEWAY_URL=${GATEWAY_URL:-http://host.docker.internal:4001}"],
            "volumes": ["paiements_data:/data"],
        }}},
        "vision": {"services": {"vision": {
            "build": ".", "ports": ["5960:5960"],
            "environment": ["PORT=5960"], "volumes": ["vision_data:/data"],
        }}},
        "mail": {"services": {"mail": {
            "build": ".", "ports": ["6030:6030"],
            "environment": ["PORT=6030", "VISION_URL=${VISION_URL:-http://host.docker.internal:5960}"],
            "volumes": ["mail_data:/data"],
        }}},
    }


def test_composition_resto_paiements():
    compose, rapport = bundle.composer("Vincept", ["restaurant", "paiements"], _manifests(), _composes())
    svc = compose["services"]
    assert set(svc) == {"restaurant", "paiements"}

    r = svc["restaurant"]
    assert r["container_name"] == "vincept_restaurant"
    assert r["build"] == "./briques/restaurant"
    assert "image" not in r                       # image épinglée retirée → build local
    assert r["env_file"] == ["./.env"]            # secrets = .env DU bundle
    assert "depends_on" not in r                  # dépendances d'origine purgées
    assert r["ports"] == ["${PORT_RESTAURANT:-6210}:6010"]   # hôte décalé, interne natif
    assert "GATEWAY_URL=http://gateway:4001" in r["environment"]
    assert "PORT=6010" in r["environment"]        # port interne intact
    # healthcheck conservé tel quel
    assert r["healthcheck"] == {"test": ["CMD", "true"]}

    assert svc["paiements"]["ports"] == ["${PORT_PAIEMENTS:-6220}:6020"]
    assert compose["volumes"] == {"restaurant_data": None, "paiements_data": None}
    assert rapport["ports"] == {"restaurant": 6210, "paiements": 6220}
    assert rapport["inconnues"] == []


def test_url_inter_brique_si_presente_sinon_intacte():
    # vision absente → VISION_URL laissée telle quelle (dépendance optionnelle non fournie)
    compose, _ = bundle.composer("c", ["restaurant"], _manifests(), _composes())
    env_seul = compose["services"]["restaurant"]["environment"]
    assert any("VISION_URL=${VISION_URL" in e for e in env_seul)

    # vision présente → VISION_URL pointe le service interne du bundle
    compose2, _ = bundle.composer("c", ["restaurant", "vision"], _manifests(), _composes())
    env_avec = compose2["services"]["restaurant"]["environment"]
    assert "VISION_URL=http://vision:5960" in env_avec


def test_depends_on_metier_tire_plateforme_ignoree():
    # mail dépend de vision (métier) → vision tirée, ordonnée avant mail
    ordre, inconnues = bundle.resoudre_dependances(["mail"], _manifests())
    assert ordre == ["vision", "mail"]
    assert inconnues == []
    # mail récupère l'URL interne de vision automatiquement
    compose, _ = bundle.composer("c", ["mail"], _manifests(), _composes())
    assert "VISION_URL=http://vision:5960" in compose["services"]["mail"]["environment"]


def test_dependance_plateforme_non_tiree():
    m = _manifests()
    m["restaurant"]["depends_on"] = ["gateway", "memoire"]
    ordre, _ = bundle.resoudre_dependances(["restaurant"], m)
    assert ordre == ["restaurant"]               # gateway/memoire = plateforme, exclues


def test_inconnue_signalee():
    ordre, inconnues = bundle.resoudre_dependances(["fantome"], _manifests())
    assert ordre == []
    assert inconnues == ["fantome"]


def test_collision_de_port_levee():
    m = {"a": {"nom": "a", "port": 6010}, "b": {"nom": "b", "port": 6010}}
    with pytest.raises(ValueError, match="Collision"):
        bundle.allouer_ports(["a", "b"], m)


def test_brique_sans_port_levee():
    m = {"x": {"nom": "x", "port": None}}
    with pytest.raises(ValueError, match="sans port"):
        bundle.allouer_ports(["x"], m)


def test_idempotence():
    a, _ = bundle.composer("Vincept", ["restaurant", "paiements"], _manifests(), _composes())
    b, _ = bundle.composer("Vincept", ["restaurant", "paiements"], _manifests(), _composes())
    assert a == b


def test_bundle_vivant_ajout_preserve_existant():
    avant, _ = bundle.composer("Vincept", ["restaurant"], _manifests(), _composes())
    apres, _ = bundle.composer("Vincept", ["restaurant", "paiements"], _manifests(), _composes())
    # le service et le volume du resto sont strictement identiques après ajout du paiement
    assert apres["services"]["restaurant"] == avant["services"]["restaurant"]
    assert "restaurant_data" in apres["volumes"]
    assert "paiements" in apres["services"]


def test_ecrire_bundle_sur_disque(tmp_path):
    # mini-arborescence de briques sur disque (manifest + compose + source + bruit ignoré)
    briques = tmp_path / "briques"
    for nom, port in (("restaurant", 6010), ("paiements", 6020)):
        d = briques / nom
        (d / "data").mkdir(parents=True)          # doit être ignoré à la copie
        (d / "manifest.json").write_text(json.dumps({"nom": nom, "port": port, "depends_on": []}))
        (d / "docker-compose.yml").write_text(json.dumps(_composes()[nom]))
        (d / "main.py").write_text("# source\n")
        (d / "data" / "x.db").write_text("DONNEES")
    export = tmp_path / "export"
    export.mkdir()

    recap = bundle.ecrire_bundle("Vincept", ["restaurant", "paiements"], str(briques), str(export))

    dossier = export / "vincept-bundle"
    assert dossier.is_dir()
    assert (dossier / "docker-compose.yml").exists()
    assert (dossier / ".env.example").exists()
    assert (dossier / "briques" / "restaurant" / "main.py").exists()
    assert not (dossier / "briques" / "restaurant" / "data").exists()   # bruit non copié

    meta = json.loads((dossier / "bundle.json").read_text())
    assert meta["briques"] == ["restaurant", "paiements"]
    assert meta["ports"] == {"restaurant": 6210, "paiements": 6220}
    assert recap["dossier"] == str(dossier)
