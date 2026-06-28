"""Tests hors-ligne du moteur de bundle (S95).

Pures données en entrée (manifests + composes en mémoire) → aucun docker, aucun réseau.
Vérifie : composition, remap des ports, réécriture des URLs vers les noms de service,
résolution des dépendances (métier tirées, plateforme ignorées), garde-fous (collision /
brique sans port), idempotence, bundle vivant (ajout préserve l'existant) et écriture disque.
"""
import json

import pytest

import yaml
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
    # Briques métier seules (infra gateway/assistant testée à part).
    compose, rapport = bundle.composer("Vincept", ["restaurant", "paiements"], _manifests(),
                                       _composes(), avec_gateway=False, avec_assistant=False)
    svc = compose["services"]
    assert set(svc) == {"restaurant", "paiements"}

    r = svc["restaurant"]
    assert r["container_name"] == "vincept_restaurant"
    assert r["build"] == "./briques/restaurant"
    assert "image" not in r                       # image épinglée retirée → build local
    assert r["env_file"] == ["./.env"]            # secrets = .env DU bundle
    assert "depends_on" not in r                  # dépendances d'origine purgées
    assert r["ports"] == ["${PORT_RESTAURANT:-6210}:6010"]   # hôte décalé, interne natif
    assert "GATEWAY_URL=http://gateway:4000" in r["environment"]   # port INTERNE de la gateway
    assert "PORT=6010" in r["environment"]        # port interne intact
    # healthcheck conservé tel quel
    assert r["healthcheck"] == {"test": ["CMD", "true"]}

    assert svc["paiements"]["ports"] == ["${PORT_PAIEMENTS:-6220}:6020"]
    assert compose["volumes"] == {"restaurant_data": None, "paiements_data": None}
    assert rapport["ports"] == {"restaurant": 6210, "paiements": 6220}
    assert rapport["inconnues"] == []


def test_gateway_et_assistant_par_defaut():
    compose, _ = bundle.composer("Vincept", ["restaurant"], _manifests(), _composes())
    svc = compose["services"]
    # infra présente d'office
    assert {"gateway", "gateway_db", "assistant"} <= set(svc)

    gw = svc["gateway"]
    assert gw["image"] == bundle.GATEWAY_IMAGE
    assert gw["command"] == ["--config", "/app/config.yaml", "--port", "4000"]
    assert gw["ports"] == ["${PORT_GATEWAY:-4201}:4000"]       # hôte décalé → interne 4000
    assert "LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY}" in gw["environment"]
    assert gw["depends_on"] == {"gateway_db": {"condition": "service_healthy"}}

    a = svc["assistant"]
    assert a["build"] == "./core"
    assert a["ports"] == ["${PORT_ASSISTANT:-5300}:5000"]
    assert "GATEWAY_URL=http://gateway:4000" in a["environment"]
    assert "GATEWAY_KEY=${GATEWAY_KEY}" in a["environment"]
    assert "BRIQUES_DIR=/manifests" in a["environment"]
    assert "RESTAURANT_URL=http://restaurant:6010" in a["environment"]   # join par nom de service
    assert a["depends_on"] == ["gateway", "restaurant"]
    assert compose["volumes"]["gateway_db"] is None
    assert compose["volumes"]["assistant_data"] is None


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


# ── Briques dépendant de shared/ (S120 : build-context racine du bundle) ──────────
def _service_shared():
    """Service d'une brique au build-context racine du monorepo (forme S118/S120)."""
    return {"services": {"donnees": {
        "build": {"context": "../..", "dockerfile": "briques/donnees/Dockerfile"},
        "container_name": "workplace_donnees",
        "ports": ["5500:5500"],
        "environment": ["DB_PATH=/data/donnees.db"],
        "volumes": ["donnees_data:/data"],
    }}}


def test_depend_de_shared_detecte_le_contexte_racine():
    assert bundle.depend_de_shared({"build": {"context": "../..", "dockerfile": "x"}}) is True
    assert bundle.depend_de_shared({"build": "."}) is False
    assert bundle.depend_de_shared({"build": "./briques/x"}) is False
    assert bundle.depend_de_shared({}) is False


def test_brique_shared_recoit_build_context_racine_du_bundle():
    manifests = {"donnees": {"nom": "donnees", "port": 5500, "depends_on": []}}
    compose, _ = bundle.composer("Acme", ["donnees"], manifests, _service_shared_map(),
                                 avec_gateway=False, avec_assistant=False)
    d = compose["services"]["donnees"]
    # Build-context = racine du bundle (reproduit <bundle>/shared/ + <bundle>/briques/donnees/)
    assert d["build"] == {"context": ".", "dockerfile": "./briques/donnees/Dockerfile"}
    assert "image" not in d


def _service_shared_map():
    return {"donnees": _service_shared()}


def test_ecrire_bundle_embarque_shared(tmp_path, monkeypatch):
    # Arborescence minimale d'un faux dépôt : briques/donnees/ + shared/.
    racine = tmp_path / "repo"
    briques_dir = racine / "briques"
    (briques_dir / "donnees").mkdir(parents=True)
    (briques_dir / "donnees" / "Dockerfile").write_text("FROM python:3.11-slim\n")
    (briques_dir / "donnees" / "manifest.json").write_text(
        json.dumps({"nom": "donnees", "port": 5500, "depends_on": []}))
    (briques_dir / "donnees" / "docker-compose.yml").write_text(yaml.safe_dump(_service_shared()))
    (racine / "shared").mkdir()
    (racine / "shared" / "workplace_auth.py").write_text("# lib partagée\n")

    export = tmp_path / "export"
    rapport = bundle.ecrire_bundle("Acme", ["donnees"], str(briques_dir), str(export),
                                   avec_gateway=False, avec_assistant=False)
    dossier = export / f"{rapport['slug']}-bundle"
    # shared/ copiée à la racine du bundle → le build-context racine la trouve.
    assert (dossier / "shared" / "workplace_auth.py").is_file()
    assert (dossier / "briques" / "donnees" / "Dockerfile").is_file()


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


def _arbo_disque(tmp_path):
    """Mini-arborescence Workplace sur disque : briques (+ gateway config) et core."""
    briques = tmp_path / "briques"
    for nom, port in (("restaurant", 6010), ("paiements", 6020)):
        d = briques / nom
        (d / "data").mkdir(parents=True)          # doit être ignoré à la copie
        (d / "manifest.json").write_text(json.dumps({"nom": nom, "port": port, "depends_on": []}))
        (d / "docker-compose.yml").write_text(json.dumps(_composes()[nom]))
        (d / "main.py").write_text("# source\n")
        (d / "data" / "x.db").write_text("DONNEES")
    (briques / "gateway").mkdir()
    (briques / "gateway" / "litellm_config.yaml").write_text("master_key: os.environ/LITELLM_MASTER_KEY\n")
    core = tmp_path / "core"
    core.mkdir()
    (core / "Dockerfile").write_text("FROM python:3.12-slim\n")
    export = tmp_path / "export"
    export.mkdir()
    return briques, export


def test_ecrire_bundle_sur_disque(tmp_path):
    briques, export = _arbo_disque(tmp_path)
    recap = bundle.ecrire_bundle("Vincept", ["restaurant", "paiements"], str(briques), str(export))

    dossier = export / "vincept-bundle"
    assert dossier.is_dir()
    assert (dossier / "docker-compose.yml").exists()
    assert (dossier / "LISEZMOI.txt").exists()
    assert (dossier / "briques" / "restaurant" / "main.py").exists()
    assert not (dossier / "briques" / "restaurant" / "data").exists()        # bruit non copié
    # manifests copiés pour la découverte par l'assistant
    assert (dossier / "manifests" / "restaurant" / "manifest.json").exists()
    # Cœur (build assistant) + config Gateway copiés
    assert (dossier / "core" / "Dockerfile").exists()
    assert (dossier / "gateway" / "litellm_config.yaml").exists()

    meta = json.loads((dossier / "bundle.json").read_text())
    assert meta["briques"] == ["restaurant", "paiements"]
    assert meta["ports"] == {"restaurant": 6210, "paiements": 6220}
    assert recap["dossier"] == str(dossier)


def test_env_cle_interne_partagee_et_openrouter_vide(tmp_path):
    briques, export = _arbo_disque(tmp_path)
    bundle.ecrire_bundle("Vincept", ["restaurant"], str(briques), str(export))
    env = (export / "vincept-bundle" / ".env").read_text()
    vals = dict(l.split("=", 1) for l in env.splitlines() if "=" in l and not l.startswith("#"))
    assert vals["OPENROUTER_API_KEY"] == ""                       # à remplir par le client
    assert vals["LITELLM_MASTER_KEY"] == vals["GATEWAY_KEY"]      # couplage critique respecté
    assert vals["LITELLM_MASTER_KEY"].startswith("sk-")
    assert vals["PORT_ASSISTANT"] == "5300"


def test_env_non_ecrase_au_reenrichissement(tmp_path):
    # Bundle vivant : ajouter une brique NE DOIT PAS régénérer le .env (clés/secrets gardés).
    briques, export = _arbo_disque(tmp_path)
    bundle.ecrire_bundle("Vincept", ["restaurant"], str(briques), str(export))
    chemin_env = export / "vincept-bundle" / ".env"
    chemin_env.write_text("OPENROUTER_API_KEY=sk-DEJA-POSEE\nLITELLM_MASTER_KEY=sk-fixe\nGATEWAY_KEY=sk-fixe\n")

    bundle.ecrire_bundle("Vincept", ["restaurant", "paiements"], str(briques), str(export))

    assert "sk-DEJA-POSEE" in chemin_env.read_text()              # clé du client préservée
    meta = json.loads((export / "vincept-bundle" / "bundle.json").read_text())
    assert meta["briques"] == ["restaurant", "paiements"]        # mais la brique est bien ajoutée


# ── Config Gateway du bundle (S99) : ne garder que ce que le bundle peut démarrer ──

_CONFIG_PLATEFORME = """
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
litellm_settings:
  drop_params: true
model_list:
  - model_name: or/gpt
    litellm_params:
      model: openrouter/openai/gpt-4o
      api_key: os.environ/OPENROUTER_API_KEY
  - model_name: or/claude
    litellm_params:
      model: openrouter/anthropic/claude
      api_key: os.environ/OPENROUTER_API_KEY
  - model_name: anthropic-direct/sonnet
    litellm_params:
      model: anthropic/claude-sonnet
      api_key: os.environ/ANTHROPIC_API_KEY
  - model_name: groq/llama
    litellm_params:
      model: groq/llama-3.3
      api_key: os.environ/GROQ_API_KEY
virtual_keys:
  - key: sk-forge
    models: auto
"""


def test_config_gateway_allegee_ne_garde_que_les_variables_disponibles():
    out = bundle.config_gateway_allegee(_CONFIG_PLATEFORME)
    data = yaml.safe_load(out)
    noms = [m["model_name"] for m in data["model_list"]]
    assert noms == ["or/gpt", "or/claude"]          # OpenRouter gardés, fournisseurs directs retirés
    assert "virtual_keys" not in data                # section non standard retirée
    assert set(data) == {"general_settings", "litellm_settings", "model_list"}
    # plus aucune variable hors de ce que le .env du bundle fournit -> LiteLLM démarre
    assert bundle._refs_env(data) <= bundle.ENV_BUNDLE_GATEWAY


def test_ecrire_bundle_ecrit_une_config_gateway_allegee(tmp_path):
    briques, export = _arbo_disque(tmp_path)
    (briques / "gateway").mkdir(parents=True, exist_ok=True)
    (briques / "gateway" / "litellm_config.yaml").write_text(_CONFIG_PLATEFORME)
    bundle.ecrire_bundle("Vincept", ["restaurant"], str(briques), str(export))
    cfg = (export / "vincept-bundle" / "gateway" / "litellm_config.yaml").read_text()
    data = yaml.safe_load(cfg)
    assert bundle._refs_env(data) <= bundle.ENV_BUNDLE_GATEWAY
    assert all("anthropic-direct" not in m["model_name"] for m in data["model_list"])
