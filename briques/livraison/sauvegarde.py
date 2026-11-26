"""Sauvegarde et vérification par restauration jetable (S247)."""
import secrets
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import preuve
from client_executeur import Executeur, ExecuteurErreur
from dokploy import Dokploy, DokployErreur

# Tolérance d'horloge entre le HP (qui mesure `debut`) et la VM 100 (qui date le fichier).
TOLERANCE_HORLOGE_S = 120


def _epoch(iso: Optional[str]) -> float:
    try:
        return datetime.strptime((iso or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


async def sauvegarder(d: Dokploy, entree: dict) -> dict:
    bases = []
    for b in entree.get("bases", []):
        await d.sauvegarder_base(b["sauvegarde_id"])
        bases.append(b["base"])
    for v in entree.get("volumes", []):
        await d.sauvegarder_volume(v["volume_backup_id"])
    return {"bases": bases, "volumes": len(entree.get("volumes", []))}


async def verifier(d: Dokploy, ex: Executeur, entree: dict, app_id: str,
                   horloge: Callable[[], float] = time.time) -> dict:
    """Sauvegarde FRAÎCHE de chaque base, restauration jetable (exécuteur), comparaison des
    comptages. Toute défaillance (Dokploy, exécuteur, comptages) donne un verdict `invalide` avec
    `ok: True` : le Cœur révoque alors toute preuve antérieure (fail closed)."""
    debut = horloge()
    raisons: list[str] = []
    comptages: dict = {}
    alertes: list[str] = []
    bases = entree.get("bases", [])
    if not bases:
        raisons.append("aucune base déclarée à l'inventaire : rien à vérifier")
    for b in bases:
        nom = b["base"]
        try:
            await d.sauvegarder_base(b["sauvegarde_id"])
            fichiers = await d.fichiers_sauvegarde(b["sauvegarde_id"])
            if not fichiers or _epoch(fichiers[0]["date"]) < debut - TOLERANCE_HORLOGE_S:
                raisons.append(f"{nom} : aucune sauvegarde récente")
                continue
            r = await ex.verifier(b["service"], b["utilisateur"], b["base"],
                                  f"{b['prefixe_s3']}/{fichiers[0]['nom']}")
        except (DokployErreur, ExecuteurErreur) as e:
            raisons.append(f"{nom} : {e.message}")
            continue
        comptages[nom] = r.get("comptages_restaures") or {}
        if r.get("nettoyage") == "echec":
            alertes.append(f"{nom} : base jetable restore_* non supprimée sur la VM de "
                           "restauration (à nettoyer à la main)")
        if r.get("verdict") != "valide":
            raisons.append(f"{nom} : {r.get('raison') or 'restauration non conforme'}")
    verdict = "valide" if not raisons else "invalide"
    preuve_id = secrets.token_hex(8)
    rec = preuve.noter(app_id, preuve_id, verdict, comptages)
    return {"ok": True, "verdict": verdict, "preuve_id": preuve_id, "raisons": raisons,
            "alertes": alertes, "comptages": comptages, "expire_a": rec["expire_a"],
            "volumes_non_verifies": len(entree.get("volumes", []))}
