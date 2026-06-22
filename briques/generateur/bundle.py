"""Moteur de bundle (S95) — assemble une SÉLECTION de briques existantes en une
solution livrable, autonome et isolée par client.

Idée : au lieu de générer une app web jamais vue (le métier de `packager.py`), on
PACKAGE des briques déjà écrites (restaurant, paiements, mail, agenda…) que tu coches
au Studio. Le bundle produit est une stack 100 % séparée — ses conteneurs, ses ports,
ses données — qu'on lance d'un seul `docker compose up`.

Principe directeur : NE PAS deviner la config d'une brique. On lit son VRAI
`docker-compose.yml` et on le TRANSFORME pour le bundle :

  • port HÔTE remappé (port natif + décalage du client) → pas de collision entre clients ;
    le port INTERNE du conteneur reste natif.
  • réseau interne par NOM DE SERVICE : `GATEWAY_URL` et les `{AUTRE}_URL` pointent
    `http://gateway:4001`, `http://restaurant:6010`… au lieu de `host.docker.internal`.
  • `container_name` préfixé par le client, `build` recontextualisé sur les sources copiées.
  • volumes / healthcheck conservés tels quels (données isolées par projet compose).

S95 = briques métier uniquement, hors-ligne et testé. La Gateway et l'assistant (le Cœur)
comme services du bundle = S96. La réécriture vers `gateway:4001` est déjà faite ici pour
que S96 n'ait qu'à ajouter les deux services.

Honnêteté : une brique sans port (frontend pur) ou introuvable n'est pas inventée — elle
est écartée en le signalant. Aucune clé secrète n'est gravée : les secrets restent des
champs `.env` à remplir à la livraison.
"""
import copy
import json
import os
import re
import shutil

import yaml

# Décalage de ports par défaut entre le bundle et ta stack/les autres clients.
DECALAGE_DEFAUT = 200

# Briques « plateforme » : infrastructure du bundle, PAS des briques métier cochables.
# Elles ne sont jamais tirées comme dépendance métier (la Gateway et le Cœur sont
# ajoutés comme services dédiés du bundle en S96).
PLATEFORME = {"gateway", "memoire", "noyau", "oria", "connexion", "app-builder"}

_RE_URL = re.compile(r"^([A-Z0-9]+)_URL$")


def slug(nom: str) -> str:
    """Identifiant URL-safe pour un nom de client (réseau/volumes/dossier)."""
    s = re.sub(r"[^a-z0-9]+", "-", (nom or "client").lower()).strip("-")
    return s or "client"


def resoudre_dependances(choisies, manifests: dict) -> tuple[list[str], list[str]]:
    """Liste ordonnée des briques métier à embarquer (choix + `depends_on` métier
    récursifs), et la liste des noms inconnus/sans manifest signalés.

    Les dépendances « plateforme » (gateway, memoire…) sont ignorées ici : elles sont
    fournies par l'infrastructure du bundle, pas par le catalogue métier."""
    ordre: list[str] = []
    inconnues: list[str] = []
    vu: set[str] = set()

    def visiter(nom: str):
        if nom in vu:
            return
        vu.add(nom)
        if nom in PLATEFORME:
            return
        manifest = manifests.get(nom)
        if manifest is None:
            inconnues.append(nom)
            return
        for dep in manifest.get("depends_on", []) or []:
            if dep not in PLATEFORME:
                visiter(dep)
        ordre.append(nom)

    for nom in choisies:
        visiter(nom)
    return ordre, inconnues


def _port_interne(manifest: dict) -> int | None:
    """Port natif déclaré au manifest (port interne du conteneur), ou None si absent."""
    port = manifest.get("port")
    try:
        return int(port)
    except (TypeError, ValueError):
        return None


def allouer_ports(briques: list[str], manifests: dict, decalage: int = DECALAGE_DEFAUT) -> dict[str, int]:
    """{brique: port_hôte} = port natif + décalage. Lève si deux briques se télescopent
    sur le même port hôte (catalogue incohérent) ou si une brique n'a pas de port."""
    hotes: dict[str, int] = {}
    occupe: dict[int, str] = {}
    for nom in briques:
        interne = _port_interne(manifests.get(nom) or {})
        if interne is None:
            raise ValueError(f"Brique « {nom} » sans port : impossible à conteneuriser dans un bundle.")
        hote = interne + decalage
        if hote in occupe:
            raise ValueError(
                f"Collision de port hôte {hote} entre « {nom} » et « {occupe[hote]} » "
                f"(décalage {decalage}). Choisis un autre décalage."
            )
        occupe[hote] = nom
        hotes[nom] = hote
    return hotes


def _service_primaire(compose: dict, nom: str) -> dict:
    """Service principal du compose d'une brique : celui dont la clé == nom de la brique,
    sinon le premier déclaré. (Les services annexes — ex. IDE — sont ignorés au bundle.)"""
    services = (compose or {}).get("services") or {}
    if nom in services:
        return services[nom]
    if services:
        return next(iter(services.values()))
    raise ValueError(f"Le docker-compose de « {nom} » ne déclare aucun service.")


def _reecrire_environment(env, ports_internes: dict[str, int]):
    """Réécrit les variables `*_URL` vers le réseau interne du bundle (noms de service).

    `GATEWAY_URL` → http://gateway:4001 (la Gateway du bundle, ajoutée en S96).
    `{AUTRE}_URL` où AUTRE est une brique du bundle → http://{autre}:{port_interne}.
    Le reste est laissé intact. Accepte la forme liste (`["K=V", …]`) ou dict."""
    def cible(cle: str) -> str | None:
        if cle == "GATEWAY_URL":
            return "http://gateway:4001"
        m = _RE_URL.match(cle)
        if m:
            autre = m.group(1).lower()
            if autre in ports_internes:
                return f"http://{autre}:{ports_internes[autre]}"
        return None

    if isinstance(env, dict):
        out = {}
        for cle, val in env.items():
            nv = cible(cle)
            out[cle] = nv if nv is not None else val
        return out

    if isinstance(env, list):
        out = []
        for item in env:
            if isinstance(item, str) and "=" in item:
                cle, _, val = item.partition("=")
                nv = cible(cle)
                out.append(f"{cle}={nv}" if nv is not None else item)
            else:
                out.append(item)
        return out

    return env


def transformer_service(nom: str, service: dict, slug_client: str, port_hote: int,
                        port_interne: int, ports_internes: dict[str, int]) -> dict:
    """Transforme le service d'une brique en service du bundle (copie profonde, non destructif)."""
    s = copy.deepcopy(service)

    # Build local sur les sources copiées dans le bundle ; on retire l'image épinglée
    # pour forcer un build reproductible propre au bundle.
    s.pop("image", None)
    s["build"] = f"./briques/{nom}"
    s["container_name"] = f"{slug_client}_{nom}"

    # Secrets/réglages : le bundle a SON propre .env (et non celui de la racine Workplace).
    if "env_file" in s:
        s["env_file"] = ["./.env"]

    # Le `depends_on` d'origine référence des services du compose d'origine, absents ici.
    s.pop("depends_on", None)

    s["environment"] = _reecrire_environment(s.get("environment"), ports_internes)

    var = nom.upper().replace("-", "_")
    s["ports"] = [f"${{PORT_{var}:-{port_hote}}}:{port_interne}"]

    return s


def _volumes_nommes(service: dict) -> list[str]:
    """Noms des volumes nommés référencés par un service (entrées `nom:/chemin`),
    en ignorant les montages liés (`./x:/y`, `../x:/y`)."""
    noms = []
    for v in service.get("volumes", []) or []:
        if isinstance(v, str) and ":" in v:
            source = v.split(":", 1)[0]
            if source and not source.startswith((".", "/")):
                noms.append(source)
    return noms


def composer(client: str, choisies, manifests: dict, composes: dict,
             decalage: int = DECALAGE_DEFAUT) -> tuple[dict, dict]:
    """Compose le `docker-compose` du bundle (dict prêt à sérialiser) + un rapport.

    `manifests` = {nom: manifest.json}, `composes` = {nom: docker-compose.yml chargé}.
    Renvoie ``(compose_dict, rapport)`` avec ``rapport = {inconnues, ports, briques}``.
    Pures données en entrée → testable hors-ligne, sans disque ni docker."""
    sc = slug(client)
    ordre, inconnues = resoudre_dependances(choisies, manifests)
    ports_hote = allouer_ports(ordre, manifests, decalage)
    ports_internes = {n: _port_interne(manifests[n]) for n in ordre}

    services: dict = {}
    volumes: dict = {}
    for nom in ordre:
        compose_brique = composes.get(nom)
        if compose_brique is None:
            inconnues.append(nom)
            continue
        primaire = _service_primaire(compose_brique, nom)
        svc = transformer_service(
            nom, primaire, sc, ports_hote[nom], ports_internes[nom], ports_internes
        )
        services[nom] = svc
        for vn in _volumes_nommes(svc):
            volumes[vn] = None

    compose = {"services": services}
    if volumes:
        compose["volumes"] = volumes

    rapport = {
        "client": client,
        "slug": sc,
        "decalage": decalage,
        "briques": ordre,
        "ports": ports_hote,
        "inconnues": inconnues,
    }
    return compose, rapport


def compose_yaml(compose: dict) -> str:
    """Sérialise le compose en YAML lisible (ordre préservé, pas d'ancres)."""
    return yaml.safe_dump(compose, sort_keys=False, allow_unicode=True, default_flow_style=False)


# ── Couche disque (lit les vraies sources, écrit le bundle) ───────────────────────

_IGNORER = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".venv", "venv", "node_modules", "data", ".pytest_cache",
    "*.db", ".git",
)


def lire_manifests(briques_dir: str) -> dict:
    """{nom: manifest.json} pour toutes les briques d'un répertoire."""
    manifests: dict = {}
    for entree in sorted(os.listdir(briques_dir)):
        chemin = os.path.join(briques_dir, entree, "manifest.json")
        if os.path.isfile(chemin):
            try:
                with open(chemin, encoding="utf-8") as f:
                    manifests[entree] = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
    return manifests


def lire_compose(briques_dir: str, nom: str) -> dict | None:
    """Charge le docker-compose.yml d'une brique (1ʳᵉ variante trouvée), ou None."""
    for variante in ("docker-compose.yml", "docker-compose.yaml"):
        chemin = os.path.join(briques_dir, nom, variante)
        if os.path.isfile(chemin):
            with open(chemin, encoding="utf-8") as f:
                return yaml.safe_load(f)
    return None


def ecrire_bundle(client: str, choisies, briques_dir: str, export_dir: str,
                  decalage: int = DECALAGE_DEFAUT) -> dict:
    """Écrit le bundle sur disque : copie les sources des briques choisies, génère le
    docker-compose.yml, un bundle.json (mémoire vivante du bundle) et un .env.example.

    Idempotent : régénérer recompose à plat sans toucher aux volumes Docker (volumes
    nommés, namespacés par projet) → un bundle « vivant » qu'on ré-enrichit sans perte."""
    manifests = {n: m for n, m in lire_manifests(briques_dir).items()}
    composes = {}
    for nom in choisies:
        c = lire_compose(briques_dir, nom)
        if c is not None:
            composes[nom] = c

    compose, rapport = composer(client, choisies, manifests, composes, decalage)

    dossier = os.path.join(export_dir, f"{rapport['slug']}-bundle")
    os.makedirs(dossier, exist_ok=True)

    # Copie des sources de chaque brique embarquée (contexte de build du bundle).
    briques_out = os.path.join(dossier, "briques")
    for nom in rapport["briques"]:
        src = os.path.join(briques_dir, nom)
        dst = os.path.join(briques_out, nom)
        if os.path.isdir(src):
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst, ignore=_IGNORER)

    with open(os.path.join(dossier, "docker-compose.yml"), "w", encoding="utf-8") as f:
        f.write("# Bundle « %s » — solution livrée, autonome et isolée.\n" % client)
        f.write("# Un seul `docker compose up -d --build`. Stack 100%% séparée par client.\n")
        f.write(compose_yaml(compose))

    bundle_json = {
        "client": client,
        "slug": rapport["slug"],
        "decalage": decalage,
        "briques": rapport["briques"],
        "ports": rapport["ports"],
    }
    with open(os.path.join(dossier, "bundle.json"), "w", encoding="utf-8") as f:
        json.dump(bundle_json, f, ensure_ascii=False, indent=2)

    lignes_env = ["# Ports publiés par le bundle (modifiables). Secrets à compléter ci-dessous.\n"]
    for nom in rapport["briques"]:
        var = nom.upper().replace("-", "_")
        lignes_env.append(f"PORT_{var}={rapport['ports'][nom]}\n")
    with open(os.path.join(dossier, ".env.example"), "w", encoding="utf-8") as f:
        f.writelines(lignes_env)

    return {
        "dossier": dossier,
        "fichiers": ["docker-compose.yml", "bundle.json", ".env.example", "briques/"],
        **rapport,
    }
