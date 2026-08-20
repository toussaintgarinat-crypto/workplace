"""Sauvegarde/restauration portable sur clé USB — instantané à la demande (pas de
réplication continue, pas de cloud). Remplace, pour cet usage, l'approche « réplication
continue vers S3 » abandonnée (Litestream/WAL-G jamais branchés en prod, cf.
docs/superpowers/specs/2026-08-20-sauvegarde-usb-portable-design.md).

Toutes les interactions Docker passent par l'API HTTP du démon via `httpx` sur le socket
Unix — même motif que `config_assistant._docker_client()` (S168, redémarrage de la
Gateway) : évite d'ajouter le SDK `docker` en dépendance pour un besoin déjà couvert.
"""
import os

import httpx

DOCKER_SOCK = os.getenv("DOCKER_SOCK", "/var/run/docker.sock")


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
