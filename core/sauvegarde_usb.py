"""Sauvegarde/restauration portable sur clé USB — instantané à la demande (pas de
réplication continue, pas de cloud). Remplace, pour cet usage, l'approche « réplication
continue vers S3 » abandonnée (Litestream/WAL-G jamais branchés en prod, cf.
docs/superpowers/specs/2026-08-20-sauvegarde-usb-portable-design.md).

Toutes les interactions Docker passent par l'API HTTP du démon via `httpx` sur le socket
Unix — même motif que `config_assistant._docker_client()` (S168, redémarrage de la
Gateway) : évite d'ajouter le SDK `docker` en dépendance pour un besoin déjà couvert.
"""
import os
import shutil
from pathlib import Path

import httpx

DOCKER_SOCK = os.getenv("DOCKER_SOCK", "/var/run/docker.sock")

SENTINELLE_NOM = ".cle-sauvegarde-workplace"


def verifier_sentinelle(destination: Path) -> None:
    """Garde-fou anti-écriture-silencieuse : refuse si le fichier sentinelle n'est pas déjà
    présent à la racine du point de montage. Posé une fois, à la main, lors de la
    préparation de la clé (cf. outils/sauvegarde-usb/README.md) — son absence signifie soit
    que la clé n'est pas vraiment montée (le dossier existe mais est vide), soit qu'il ne
    s'agit pas de LA clé de sauvegarde. Sans ce garde-fou, une sauvegarde lancée avec une clé
    débranchée écrirait silencieusement sur le disque interne du HP."""
    if not (destination / SENTINELLE_NOM).exists():
        raise RuntimeError(
            f"Clé de sauvegarde absente ou non montée sur {destination} "
            f"(fichier sentinelle « {SENTINELLE_NOM} » introuvable)."
        )


def verifier_espace(destination: Path, octets_requis: int) -> None:
    """Abandon propre AVANT d'écrire quoi que ce soit si la clé n'a pas la place."""
    libre = shutil.disk_usage(destination).free
    if libre < octets_requis:
        raise RuntimeError(
            f"Espace insuffisant sur {destination} : {libre} octet(s) libre(s), "
            f"{octets_requis} requis."
        )


def _docker_client() -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCK)
    return httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=60)


def _demultiplexer(brut: bytes) -> bytes:
    """Isole les trames STDOUT (type 1) d'un flux `exec/start` Docker (Tty=false).

    Format par trame, imposé par l'API Docker : 1 octet type de flux (0=stdin, 1=stdout,
    2=stderr) + 3 octets réservés + 4 octets de longueur (big-endian) + la charge. STDERR
    est délibérément ignoré ici (pas utile pour lire une sortie `pg_dump`/`find`/`stat` ;
    en cas d'échec, `_exec` renvoie aussi le code de sortie, qui suffit à détecter l'erreur)."""
    sortie = bytearray()
    i = 0
    while i + 8 <= len(brut):
        type_flux = brut[i]
        taille = int.from_bytes(brut[i + 4:i + 8], "big")
        charge = brut[i + 8:i + 8 + taille]
        if type_flux == 1:
            sortie += charge
        i += 8 + taille
    return bytes(sortie)


async def _exec(client: httpx.AsyncClient, conteneur_id: str, cmd: list[str]) -> tuple[int, bytes]:
    """Exécute `cmd` dans un conteneur déjà démarré, renvoie (code_sortie, stdout).

    Équivalent de `docker exec` via l'API : création de l'exec, démarrage (le corps de la
    réponse EST le flux multiplexé stdout/stderr), puis relecture du code de sortie."""
    r = await client.post(f"/containers/{conteneur_id}/exec",
                           json={"AttachStdout": True, "AttachStderr": True, "Cmd": cmd})
    r.raise_for_status()
    exec_id = r.json()["Id"]
    r2 = await client.post(f"/exec/{exec_id}/start", json={"Detach": False, "Tty": False})
    r2.raise_for_status()
    sortie = _demultiplexer(r2.content)
    r3 = await client.get(f"/exec/{exec_id}/json")
    r3.raise_for_status()
    code = r3.json().get("ExitCode") or 0
    return code, sortie


def _est_postgres(image: str) -> bool:
    """Détecte une base Postgres par motif d'image — couvre les 6 bases connues du HP au
    2026-08-20 (postgres:16.*, workplace/*-walg, patroni-pg16) sans en coder les noms."""
    image = image.lower()
    return any(motif in image for motif in ("postgres", "-walg", "patroni"))


async def _chercher_sqlite(client: httpx.AsyncClient, conteneur_id: str) -> list[str]:
    """Fichiers `*.db` sous /data (SQLite) dans un conteneur — motif vérifié en pratique
    (inventaire manuel du HP, 2026-08-20) sur les 19 conteneurs SQLite du stack."""
    code, sortie = await _exec(client, conteneur_id,
                                ["find", "/data", "-maxdepth", "2", "-iname", "*.db"])
    if code != 0:
        return []
    return [l for l in sortie.decode("utf-8", "ignore").splitlines() if l.strip()]


async def decouvrir_sources(client: httpx.AsyncClient) -> list[dict]:
    """Inventaire dynamique : interroge Docker plutôt qu'une liste figée (une liste en dur
    serait fausse dès la prochaine brique ajoutée — cf. spec). Ne considère que les
    conteneurs ACTIFS (`/containers/json` sans `all=true` ne renvoie que ceux-là).

    Conteneur en échec (inspection/exec échoue) est simplement ignoré, pas d'échec global."""
    r = await client.get("/containers/json")
    r.raise_for_status()
    sources: list[dict] = []
    for resume in r.json():
        conteneur_id = resume["Id"]
        nom = resume["Names"][0].lstrip("/")
        try:
            if _est_postgres(resume.get("Image", "")):
                insp = await client.get(f"/containers/{conteneur_id}/json")
                insp.raise_for_status()
                env = dict(e.split("=", 1) for e in insp.json()["Config"]["Env"] if "=" in e)
                user = env.get("POSTGRES_USER", "postgres")
                db = env.get("POSTGRES_DB", user)
                sources.append({"brique": nom, "type": "postgres", "conteneur_id": conteneur_id,
                                 "db": db, "user": user})
            else:
                for chemin in await _chercher_sqlite(client, conteneur_id):
                    sources.append({"brique": nom, "type": "sqlite", "conteneur_id": conteneur_id,
                                     "chemin": chemin})
        except Exception:
            # Conteneur en échec (arrêt soudain, race condition, image sans shell, etc.)
            # est simplement absent du manifeste, pas d'échec global.
            continue
    return sources


async def decouvrir_conteneurs_par_brique(client: httpx.AsyncClient) -> dict[str, str]:
    """Nom de brique (= nom du conteneur) → id du conteneur, pour les conteneurs ACTIFS.
    Utilisé par la restauration pour retrouver la cible d'une entrée du manifeste."""
    r = await client.get("/containers/json")
    r.raise_for_status()
    return {resume["Names"][0].lstrip("/"): resume["Id"] for resume in r.json()}
