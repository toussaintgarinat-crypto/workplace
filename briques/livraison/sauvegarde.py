"""Sauvegarde et vérification par restauration jetable (S247)."""
import asyncio
import secrets
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import preuve
from client_executeur import Executeur, ExecuteurErreur
from dokploy import Dokploy, DokployErreur

# Tolérance d'horloge entre le HP (qui mesure `debut`) et la VM 100 (qui date le fichier).
TOLERANCE_HORLOGE_S = 120
# Délai TOTAL de la vérification, propre à la brique. Le Cœur (core/outils_communs.py,
# TIMEOUT_VERIFICATION = 600) doit rester strictement au-dessus : il ne coupe jamais avant.
DELAI_GLOBAL_S = 540.0


def _epoch(iso: Optional[str]) -> float:
    try:
        return datetime.strptime((iso or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


MOTIF_DESYNCHRONISEE = "sauvegarde_desynchronisee"


class SauvegardeDesynchronisee(Exception):
    """La sauvegarde Dokploy ne vise pas la base attendue (base active ou base d'inventaire)."""

    def __init__(self, base: str):
        super().__init__(f"{MOTIF_DESYNCHRONISEE} : la sauvegarde Dokploy ne vise pas la base "
                         f"{base} (base active) ; la remettre sur {base} dans Dokploy")
        self.base = base


async def _exiger_synchronisee(d: Dokploy, b: dict) -> None:
    """`b["base"]` vient de `base_effective` (base active d'un reset, sinon celle de
    l'inventaire) : la sauvegarde Dokploy doit viser exactement cette base."""
    if await d.base_sauvegarde(b["sauvegarde_id"]) != b["base"]:
        raise SauvegardeDesynchronisee(b["base"])


async def sauvegarder(d: Dokploy, entree: dict) -> dict:
    for b in entree.get("bases", []):      # toutes contrôlées AVANT d'en lancer une seule
        await _exiger_synchronisee(d, b)
    bases = []
    for b in entree.get("bases", []):
        await d.sauvegarder_base(b["sauvegarde_id"])
        bases.append(b["base"])
    for v in entree.get("volumes", []):
        await d.sauvegarder_volume(v["volume_backup_id"])
    return {"bases": bases, "volumes": len(entree.get("volumes", []))}


async def verifier(d: Dokploy, ex: Executeur, entree: dict, app_id: str,
                   horloge: Callable[[], float] = time.time,
                   delai_global: float = DELAI_GLOBAL_S) -> dict:
    """Sauvegarde FRAÎCHE de chaque base, restauration jetable (exécuteur), comparaison des
    comptages. Toute défaillance (Dokploy, exécuteur, comptages, délai global, disque) donne un
    verdict `invalide` avec `ok: True` : le Cœur révoque alors toute preuve antérieure (fail
    closed)."""
    preuve_id = secrets.token_hex(8)
    try:
        # Une vérification en cours ne laisse JAMAIS subsister une preuve antérieure : si elle
        # échoue, est interrompue ou coupée, il n'y a aucune preuve valide (fail closed).
        preuve.revoquer(app_id)
    except OSError:
        return {"ok": True, "verdict": "invalide", "preuve_id": preuve_id,
                "raisons": ["preuve antérieure non révoquée (erreur disque) : vérification "
                            "non lancée"],
                "alertes": [], "comptages": {}, "expire_a": float(horloge()),
                "volumes_non_verifies": len(entree.get("volumes", []))}
    try:
        return await _verifier(d, ex, entree, app_id, preuve_id, horloge, delai_global)
    except BaseException:
        # Exception inattendue, annulation (client HTTP déconnecté) : on révoque et on relance.
        try:
            preuve.revoquer(app_id)
        except OSError:
            pass
        raise


async def _verifier(d, ex, entree, app_id, preuve_id, horloge, delai_global) -> dict:
    debut = horloge()
    raisons: list[str] = []
    alertes: list[str] = []
    comptages: dict = {}
    bases = entree.get("bases", [])
    if not bases:
        raisons.append("aucune base déclarée à l'inventaire : rien à vérifier")

    async def _boucle() -> None:
        for b in bases:
            nom = b["base"]
            try:
                await _exiger_synchronisee(d, b)
                await d.sauvegarder_base(b["sauvegarde_id"])
                fichiers = await d.fichiers_sauvegarde(b["sauvegarde_id"])
                if not fichiers or _epoch(fichiers[0]["date"]) < debut - TOLERANCE_HORLOGE_S:
                    raisons.append(f"{nom} : aucune sauvegarde récente")
                    continue
                r = await ex.verifier(b["service"], b["utilisateur"], b["base"],
                                      f"{b['prefixe_s3']}/{fichiers[0]['nom']}")
            except SauvegardeDesynchronisee:
                raisons.append(f"{nom} : {MOTIF_DESYNCHRONISEE}")
                continue
            except (DokployErreur, ExecuteurErreur) as e:
                raisons.append(f"{nom} : {e.message}")
                continue
            comptages[nom] = r.get("comptages_restaures") or {}
            if r.get("nettoyage") == "echec":
                alertes.append(f"{nom} : base jetable restore_* non supprimée sur la VM de "
                               "restauration (à nettoyer à la main)")
            if r.get("verdict") != "valide":
                raisons.append(f"{nom} : {r.get('raison') or 'restauration non conforme'}")

    try:
        await asyncio.wait_for(_boucle(), delai_global)
    except asyncio.TimeoutError:
        raisons.append("délai global de vérification dépassé")
    verdict = "valide" if not raisons else "invalide"
    expire_a = float(horloge())
    try:
        if verdict == "valide":
            expire_a = preuve.noter(app_id, preuve_id, verdict, comptages)["expire_a"]
        else:
            preuve.revoquer(app_id)   # invalide : aucune preuve, pas même une entrée `invalide`
    except OSError:
        # Preuve non écrite/révoquée : rien n'est garanti. Verdict forcé `invalide`.
        verdict = "invalide"
        raisons.append("preuve non enregistrée (erreur disque)")
        expire_a = float(horloge())
        try:
            preuve.revoquer(app_id)
        except OSError:
            pass
    return {"ok": True, "verdict": verdict, "preuve_id": preuve_id, "raisons": raisons,
            "alertes": alertes, "comptages": comptages, "expire_a": expire_a,
            "volumes_non_verifies": len(entree.get("volumes", []))}
