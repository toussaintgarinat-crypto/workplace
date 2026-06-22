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
import secrets
import shutil

import yaml

# Décalage de ports par défaut entre le bundle et ta stack/les autres clients.
DECALAGE_DEFAUT = 200

# Briques « plateforme » : infrastructure du bundle, PAS des briques métier cochables.
# Elles ne sont jamais tirées comme dépendance métier (la Gateway et le Cœur sont
# ajoutés comme services dédiés du bundle, cf. S96).
PLATEFORME = {"gateway", "memoire", "noyau", "oria", "connexion", "app-builder"}

# Ports INTERNES (dans le réseau du bundle) ≠ ports publiés. Les conteneurs se parlent
# sur ces ports-là (la Gateway écoute 4000, le Cœur 5000), pas sur le port hôte décalé.
GATEWAY_PORT_INTERNE = 4000
ASSISTANT_PORT_INTERNE = 5000
GATEWAY_URL_INTERNE = f"http://gateway:{GATEWAY_PORT_INTERNE}"

# Images épinglées (alignées sur la stack Workplace).
GATEWAY_IMAGE = "ghcr.io/berriai/litellm:v1.86.2"
POSTGRES_IMAGE = "postgres:16.14-alpine"

# Ports « natifs » publiés par la Gateway et le Cœur dans la stack principale (pour le
# décalage hôte du bundle). La Gateway publie 4001 (→ 4000 interne), le Cœur 5100 (→ 5000).
GATEWAY_PORT_NATIF = 4001
ASSISTANT_PORT_NATIF = 5100

_RE_URL = re.compile(r"^([A-Z0-9]+)_URL$")


def _cle(prefixe: str, n: int = 24) -> str:
    """Clé interne aléatoire lisible (clé maîtresse LiteLLM, mot de passe DB…)."""
    alpha = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    return prefixe + "".join(secrets.choice(alpha) for _ in range(n))


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
            return GATEWAY_URL_INTERNE
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


def service_gateway(slug_client: str, decalage: int = DECALAGE_DEFAUT) -> tuple[dict, dict]:
    """Services Gateway du bundle : LiteLLM (`gateway`) + sa base (`gateway_db`).

    Le cerveau LLM PROPRE au bundle. `LITELLM_MASTER_KEY` et `OPENROUTER_API_KEY`
    viennent du `.env` du bundle (jamais en dur). Port interne 4000 (les autres services
    l'atteignent sur `gateway:4000`) ; port hôte décalé pour l'admin.
    Renvoie ``(services, volumes)``."""
    hote = GATEWAY_PORT_NATIF + decalage
    services = {
        "gateway_db": {
            "image": POSTGRES_IMAGE,
            "container_name": f"{slug_client}_gateway_db",
            "environment": [
                "POSTGRES_USER=litellm",
                "POSTGRES_PASSWORD=${GATEWAY_DB_PASSWORD:-litellm}",
                "POSTGRES_DB=litellm",
            ],
            "volumes": ["gateway_db:/var/lib/postgresql/data"],
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready -U litellm"],
                "interval": "5s", "timeout": "5s", "retries": 10,
            },
            "restart": "unless-stopped",
        },
        "gateway": {
            "image": GATEWAY_IMAGE,
            "container_name": f"{slug_client}_gateway",
            "command": ["--config", "/app/config.yaml", "--port", str(GATEWAY_PORT_INTERNE)],
            "env_file": ["./.env"],
            "environment": [
                "LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY}",
                "OPENROUTER_API_KEY=${OPENROUTER_API_KEY}",
                "DATABASE_URL=postgresql://litellm:${GATEWAY_DB_PASSWORD:-litellm}@gateway_db:5432/litellm",
            ],
            "volumes": ["./gateway/litellm_config.yaml:/app/config.yaml:ro"],
            "depends_on": {"gateway_db": {"condition": "service_healthy"}},
            "ports": [f"${{PORT_GATEWAY:-{hote}}}:{GATEWAY_PORT_INTERNE}"],
            "restart": "unless-stopped",
        },
    }
    return services, {"gateway_db": None}


def service_assistant(slug_client: str, briques: list[str], ports_internes: dict[str, int],
                      decalage: int = DECALAGE_DEFAUT) -> tuple[dict, dict]:
    """Service assistant (le Cœur) du bundle. Découvre les briques du bundle par leurs
    manifests (`BRIQUES_DIR=/manifests`) et les joint par NOM DE SERVICE via les overrides
    `{NOM}_URL` (mécanisme `core/catalogue.py`). `GATEWAY_KEY` = clé maîtresse LiteLLM.

    Volontairement allégé vs la stack complète : pas de socket Docker, pas de proxy_net,
    pas d'écriture du `.env` Gateway (le ⚙ Cerveau à chaud est désactivé dans un bundle ;
    la clé se pose dans le `.env`). Renvoie ``(services, volumes)``."""
    hote = ASSISTANT_PORT_NATIF + decalage
    env = [
        "BRIQUES_DIR=/manifests",
        "BRIQUE_HOST=host.docker.internal",   # repli ; les overrides {NOM}_URL priment
        f"NOYAU_URL=http://127.0.0.1:{ASSISTANT_PORT_INTERNE}",
        f"GATEWAY_URL={GATEWAY_URL_INTERNE}",
        "GATEWAY_KEY=${GATEWAY_KEY}",          # == LITELLM_MASTER_KEY (cf. .env)
        "GATEWAY_MODEL=",
        "CASCADE_AUTO=1",
        "CASCADE_FREE_N=3",
        "REPLI_PAYANT=deepseek/deepseek-v4-flash",
        "LIVRAISONS_DB=/data/livraisons.db",
        "ASSISTANT_CONFIG_PATH=/data/assistant_config.json",
        "MCP_ACTIF=0",
    ]
    for nom in briques:
        env.append(f"{nom.upper().replace('-', '_')}_URL=http://{nom}:{ports_internes[nom]}")

    service = {
        "build": "./core",
        "container_name": f"{slug_client}_assistant",
        "env_file": ["./.env"],
        "environment": env,
        "volumes": ["./manifests:/manifests:ro", "assistant_data:/data"],
        "depends_on": ["gateway", *briques],
        "ports": [f"${{PORT_ASSISTANT:-{hote}}}:{ASSISTANT_PORT_INTERNE}"],
        "restart": "unless-stopped",
    }
    return {"assistant": service}, {"assistant_data": None}


def composer(client: str, choisies, manifests: dict, composes: dict,
             decalage: int = DECALAGE_DEFAUT,
             avec_gateway: bool = True, avec_assistant: bool = True) -> tuple[dict, dict]:
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

    # Infrastructure du bundle : Gateway (cerveau LLM) puis assistant (le Cœur).
    if avec_gateway:
        svc_gw, vol_gw = service_gateway(sc, decalage)
        services.update(svc_gw)
        volumes.update(vol_gw)
    if avec_assistant:
        svc_as, vol_as = service_assistant(sc, ordre, ports_internes, decalage)
        services.update(svc_as)
        volumes.update(vol_as)

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


_LISEZMOI = """Bundle « {client} » — solution livrée, autonome et isolée
================================================================

Stack 100 %% séparée : ses conteneurs, ses ports, ses données. Lancée d'une commande.
Contenu : {briques}{plus}.

DÉMARRAGE
---------
  1. Ouvrez .env et renseignez OPENROUTER_API_KEY (votre clé du fournisseur LLM).
     Les autres clés (clé maîtresse interne, mot de passe base) sont déjà générées.
  2. docker compose up -d --build
  3. Assistant :  http://localhost:{port_assistant}
{lignes_briques}
DONNÉES & COMPTES
-----------------
Chaque service a SON volume Docker (données isolées, survivent au redémarrage).
  docker compose down       garde les données
  docker compose down -v    efface TOUT (remise à zéro)

NOTES
-----
• Le réglage du cerveau « à chaud » (⚙) est désactivé en bundle : le modèle/clé se
  posent dans .env. GATEWAY_KEY DOIT rester identique à LITELLM_MASTER_KEY (déjà le cas).
• Certaines briques exigent leurs propres secrets (Stripe, IMAP/SMTP…) : voir leur
  README dans briques/<nom>/ et complétez .env en conséquence.

Généré par Workplace.
"""


def ecrire_bundle(client: str, choisies, briques_dir: str, export_dir: str,
                  decalage: int = DECALAGE_DEFAUT, core_dir: str | None = None,
                  avec_gateway: bool = True, avec_assistant: bool = True) -> dict:
    """Écrit le bundle sur disque : sources des briques + Cœur + config Gateway, manifests
    des briques (pour la découverte par l'assistant), docker-compose.yml, bundle.json,
    .env (clés internes générées, OPENROUTER_API_KEY à remplir) et LISEZMOI.

    Idempotent et « vivant » : régénérer recompose à plat SANS écraser un .env existant
    (clés/secrets du déploiement préservés) ni toucher aux volumes Docker (nommés,
    namespacés par projet) → on ré-enrichit un bundle livré sans rien perdre."""
    if core_dir is None:
        core_dir = os.path.join(os.path.dirname(briques_dir.rstrip("/")), "core")

    manifests = lire_manifests(briques_dir)
    composes = {nom: c for nom in choisies if (c := lire_compose(briques_dir, nom)) is not None}

    compose, rapport = composer(client, choisies, manifests, composes, decalage,
                                avec_gateway=avec_gateway, avec_assistant=avec_assistant)

    dossier = os.path.join(export_dir, f"{rapport['slug']}-bundle")
    os.makedirs(dossier, exist_ok=True)

    # 1. Sources des briques embarquées + leurs manifests (découverte par l'assistant).
    briques_out = os.path.join(dossier, "briques")
    manifests_out = os.path.join(dossier, "manifests")
    for nom in rapport["briques"]:
        src = os.path.join(briques_dir, nom)
        if os.path.isdir(src):
            dst = os.path.join(briques_out, nom)
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst, ignore=_IGNORER)
        man_dst = os.path.join(manifests_out, nom)
        os.makedirs(man_dst, exist_ok=True)
        with open(os.path.join(man_dst, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifests.get(nom, {"nom": nom}), f, ensure_ascii=False, indent=2)

    # 2. Le Cœur (contexte de build de l'assistant) + la config LiteLLM de la Gateway.
    if avec_assistant and os.path.isdir(core_dir):
        dst = os.path.join(dossier, "core")
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(core_dir, dst, ignore=_IGNORER)
    if avec_gateway:
        cfg = os.path.join(briques_dir, "gateway", "litellm_config.yaml")
        if os.path.isfile(cfg):
            os.makedirs(os.path.join(dossier, "gateway"), exist_ok=True)
            shutil.copy2(cfg, os.path.join(dossier, "gateway", "litellm_config.yaml"))

    # 3. Orchestration + mémoire du bundle.
    with open(os.path.join(dossier, "docker-compose.yml"), "w", encoding="utf-8") as f:
        f.write(f"# Bundle « {client} » — solution livrée, autonome et isolée.\n")
        f.write("# Un seul `docker compose up -d --build`. Stack 100% séparée par client.\n")
        f.write(compose_yaml(compose))

    with open(os.path.join(dossier, "bundle.json"), "w", encoding="utf-8") as f:
        json.dump({"client": client, "slug": rapport["slug"], "decalage": decalage,
                   "briques": rapport["briques"], "ports": rapport["ports"],
                   "gateway": avec_gateway, "assistant": avec_assistant},
                  f, ensure_ascii=False, indent=2)

    # 4. .env — généré UNE fois (clés internes aléatoires) ; jamais réécrit ensuite pour
    #    préserver les secrets/clés d'un bundle déjà déployé (bundle vivant).
    chemin_env = os.path.join(dossier, ".env")
    if not os.path.exists(chemin_env):
        master = _cle("sk-")
        lignes = ["# Bundle « %s » — configuration. Renseignez OPENROUTER_API_KEY.\n\n" % client]
        lignes.append("# === Clé du fournisseur LLM (À REMPLIR) ===\n")
        lignes.append("OPENROUTER_API_KEY=\n\n")
        lignes.append("# === Clés internes (générées — ne pas modifier sauf besoin) ===\n")
        lignes.append(f"LITELLM_MASTER_KEY={master}\n")
        lignes.append(f"GATEWAY_KEY={master}\n")          # DOIT == LITELLM_MASTER_KEY
        lignes.append(f"GATEWAY_DB_PASSWORD={_cle('', 16)}\n\n")
        lignes.append("# === Ports publiés (modifiables) ===\n")
        if avec_gateway:
            lignes.append(f"PORT_GATEWAY={GATEWAY_PORT_NATIF + decalage}\n")
        if avec_assistant:
            lignes.append(f"PORT_ASSISTANT={ASSISTANT_PORT_NATIF + decalage}\n")
        for nom in rapport["briques"]:
            lignes.append(f"PORT_{nom.upper().replace('-', '_')}={rapport['ports'][nom]}\n")
        with open(chemin_env, "w", encoding="utf-8") as f:
            f.writelines(lignes)

    lignes_briques = "".join(
        f"  • {nom} :  http://localhost:{rapport['ports'][nom]}\n" for nom in rapport["briques"]
    )
    with open(os.path.join(dossier, "LISEZMOI.txt"), "w", encoding="utf-8") as f:
        f.write(_LISEZMOI.format(
            client=client, briques=", ".join(rapport["briques"]) or "(aucune)",
            plus=(" + assistant + gateway" if avec_assistant and avec_gateway else ""),
            port_assistant=ASSISTANT_PORT_NATIF + decalage, lignes_briques=lignes_briques,
        ))

    return {
        "dossier": dossier,
        "fichiers": ["docker-compose.yml", "bundle.json", ".env", "LISEZMOI.txt",
                     "briques/", "manifests/", "core/", "gateway/"],
        **rapport,
    }
