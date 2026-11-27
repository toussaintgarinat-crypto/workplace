"""Orchestration des paquets de données utilisateur (S248 3a) : export → chiffrement → dépôt
SeaweedFS (via l'exécuteur) → registre ; vérification par RELECTURE du stockage. Jamais le contenu
en retour, jamais l'identité en clair."""
import time
from typing import Optional

import chiffrement
import paquets
from client_executeur import ExecuteurErreur


async def exporter_et_stocker(app, ex, utilisateur: str, maintenant: Optional[float] = None) -> dict:
    h = paquets.empreinte_utilisateur(utilisateur)
    paquet, meta = await app.exporter(utilisateur)
    pid = paquets.nouveau_id()
    objet = paquets.cle_objet(app.nom, h, pid)
    await ex.deposer(objet, chiffrement.chiffrer(paquet, objet))
    try:
        rec = paquets.enregistrer(pid, app.nom, h, objet, meta["empreinte"], meta["comptages"],
                                  app.version_schema, maintenant)
    except OSError:
        try:
            await ex.supprimer(objet)     # pas d'objet orphelin hors registre
        except ExecuteurErreur:
            pass
        raise
    paquets.journaliser("exporter", app.nom, h, pid, True, maintenant)
    return {"paquet_id": pid, "empreinte": rec["empreinte"], "comptages": rec["comptages"],
            "version_schema": rec["version_schema"], "expire_a": rec["expire_a"], "h": h}


async def verifier_paquet(app, ex, utilisateur: str, maintenant: Optional[float] = None) -> dict:
    """Exporte à neuf, stocke, RELIT depuis le stockage, déchiffre, et fait vérifier CE paquet par
    l'app (import dans un dossier jetable + ré-export + même empreinte). Toute défaillance donne un
    verdict `invalide` avec `ok: True` (fail closed, convention S247)."""
    from contrats import ContratErreur
    r = await exporter_et_stocker(app, ex, utilisateur, maintenant)
    pid, raisons = r["paquet_id"], []
    try:
        rec = paquets.lire(pid)
        if rec is None:
            raise LookupError
        blob = await ex.lire(rec["objet"])
        clair = chiffrement.dechiffrer(blob, rec["objet"])
        retour = await app.verifier(utilisateur, clair)
        if retour.get("ok") is not True or retour.get("empreinte") != rec["empreinte"]:
            raisons.append("l'application ne confirme pas l'empreinte exportée")
    except chiffrement.Illisible:
        raisons.append("paquet relu illisible (altéré ou mauvaise clé)")
    except ContratErreur as e:
        raisons.append(f"refus de l'application : {e.raison or 'erreur'}")
    except ExecuteurErreur as e:
        raisons.append(f"stockage : {e.message}")
    except LookupError:
        raisons.append("paquet introuvable dans le registre")
    except Exception:   # fail closed : jamais d'exception brute (ni son message) vers l'appelant
        raisons.append("erreur inattendue pendant la vérification")
    verdict = "valide" if not raisons else "invalide"
    if verdict == "valide":
        paquets.marquer_verifie(pid, maintenant)
    paquets.journaliser("verifier", app.nom, r["h"], pid, verdict == "valide", maintenant)
    now = maintenant if maintenant is not None else time.time()
    return {"ok": True, "verdict": verdict, "paquet_id": pid, "empreinte": r["empreinte"],
            "comptages": r["comptages"], "raisons": raisons,
            "expire_a": min(now + paquets.PREUVE_TTL_S, r["expire_a"])}


async def purger_expires(ex, maintenant: Optional[float] = None) -> dict:
    supprimes = restants = 0
    for rec in paquets.expires(maintenant):
        try:
            await ex.supprimer(rec["objet"])
            paquets.retirer(rec["id"])
            paquets.journaliser("purger", rec["app"], rec["h"], rec["id"], True, maintenant)
        except (ExecuteurErreur, OSError, KeyError, TypeError, ValueError):
            restants += 1          # on réessaiera : une entrée en échec n'arrête pas les autres
            continue
        supprimes += 1
    return {"supprimes": supprimes, "restants": restants}
