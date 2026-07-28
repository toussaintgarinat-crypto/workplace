"""Le côté API du pont (S214) — appelle PyAirbyte sans jamais l'importer.

`pont/executer.py` vit dans un autre interpréteur (`/opt/pyairbyte/bin/python`) pour une
raison de dépendances (cf. son en-tête et l'ADR). Mais la cloison rend deux services que
l'on aurait dû construire de toute façon :

  • **la boucle d'événements ne bloque jamais.** Une sync de plusieurs minutes tourne dans
    un processus séparé, attendue en asyncio ; `/sante` répond pendant ce temps. C'est
    exactement le défaut que S212 a corrigé sur `etl`, où l'OCR faisait tomber le
    healthcheck — ici il ne peut pas se produire.
  • **un connecteur tiers qui plante n'emporte pas la brique.** Les connecteurs Airbyte
    sont du code tiers ; un segfault ou une fuite mémoire reste de l'autre côté.

Le prix : tout passe par du JSON. C'est assumé, et c'est peu.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("connecteurs.pont")

RACINE_BRIQUE = Path(__file__).resolve().parent

# Surchargeables : les tests substituent un faux exécuteur pour éprouver le PROTOCOLE
# (bruit sur stdout, sortie vide, code de retour non nul) sans installer PyAirbyte.
PYTHON_PYAIRBYTE = os.getenv("CONNECTEURS_PYTHON", "/opt/pyairbyte/bin/python")
EXECUTEUR = os.getenv("CONNECTEURS_EXECUTEUR", str(RACINE_BRIQUE / "pont" / "executer.py"))

# Une sync tierce peut être longue (premier plein d'un dépôt GitHub). Une heure par défaut,
# mais BORNÉE : sans plafond, un connecteur qui pend laisse une sync « en_cours » éternelle
# et bloque la suivante.
TIMEOUT_DEFAUT = float(os.getenv("CONNECTEURS_TIMEOUT", "3600"))
TIMEOUT_COURT = float(os.getenv("CONNECTEURS_TIMEOUT_COURT", "600"))


class PontIndisponible(RuntimeError):
    """L'interpréteur PyAirbyte est absent — image mal construite, pas erreur de l'usager."""


def disponible() -> bool:
    return Path(PYTHON_PYAIRBYTE).exists() and Path(EXECUTEUR).exists()


def _extraire(sortie: bytes) -> dict | None:
    """La DERNIÈRE ligne JSON de stdout. `executer.py` garantit qu'il n'en écrit qu'une —
    on prend malgré tout la dernière, pour qu'un jour où la garantie se fissure (un
    `print` égaré) on lise la réponse plutôt qu'un fragment de barre de progression."""
    for ligne in reversed(sortie.decode("utf-8", "replace").splitlines()):
        ligne = ligne.strip()
        if not ligne.startswith("{"):
            continue
        try:
            charge = json.loads(ligne)
        except json.JSONDecodeError:
            continue
        if isinstance(charge, dict) and "ok" in charge:
            return charge
    return None


async def executer(job: dict, *, timeout: float | None = None) -> dict:
    """Lance un job de l'autre côté de la cloison. Ne lève que si l'image est cassée.

    Rend toujours un dict `{"ok": bool, …}` : un échec de connecteur est une DONNÉE
    (rangée dans `syncs.erreur`, lisible par l'assistant), pas une exception à rattraper
    au niveau de la route.
    """
    if not disponible():
        raise PontIndisponible(
            f"interpréteur PyAirbyte introuvable ({PYTHON_PYAIRBYTE} / {EXECUTEUR})")

    proc = await asyncio.create_subprocess_exec(
        PYTHON_PYAIRBYTE, EXECUTEUR,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # La config voyage par stdin, jamais par argv (`ps` la rendrait lisible).
        env={**os.environ, "DO_NOT_TRACK": "1"},
    )
    entree = json.dumps(job, ensure_ascii=False).encode()
    try:
        sortie, erreurs = await asyncio.wait_for(
            proc.communicate(entree), timeout=timeout or TIMEOUT_DEFAUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"ok": False, "erreur": f"délai dépassé ({timeout or TIMEOUT_DEFAUT:.0f} s) — "
                                       "la sync suivante reprendra au dernier curseur enregistré"}

    charge = _extraire(sortie)
    if charge is not None:
        return charge

    # Pas de réponse exploitable : le processus est mort avant d'écrire (OOM, kill, import
    # cassé). On rend la QUEUE de stderr — c'est là qu'est la cause, et l'opérateur ne
    # devrait pas avoir à ouvrir `docker logs` pour un diagnostic de base.
    queue = erreurs.decode("utf-8", "replace").strip().splitlines()[-15:]
    logger.warning("Pont : aucune réponse JSON (code %s)", proc.returncode)
    return {"ok": False,
            "erreur": f"le pont PyAirbyte n'a rien rendu (code {proc.returncode})",
            "journal": "\n".join(queue)}


def schema_de(tenant: str, source_id: int) -> str:
    """Schéma DuckDB d'une source. Isolé par tenant ET par source : deux personnes qui
    branchent le même connecteur ne partagent ni leurs tables ni leur curseur.

    Le tenant est déjà une empreinte ou un `perso:<id>` (cf. main.py) ; on ne garde que
    ce qui est licite dans un identifiant SQL."""
    propre = "".join(c if c.isalnum() else "_" for c in tenant)[:40]
    return f"s{source_id}_{propre}"
