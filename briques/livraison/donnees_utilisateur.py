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


class RefusDonnees(Exception):
    """Refus d'orchestration : `.message` est une chaîne FIXE (jamais l'utilisateur, une clé ni un
    corps de réponse), `.statut` le code HTTP à restituer."""

    def __init__(self, statut: int, message: str):
        super().__init__(message)
        self.statut, self.message = statut, message


_EN_COURS: set = set()     # (app, h) ayant une opération en cours : un reset ne double jamais
_RACINE_AMBIGU = ("l'application n'a pas répondu : la remise à zéro a peut-être été effectuée, "
                  "vérifie avec livraison_donnees_verifier avant de réessayer")
_RESEAU = ("injoignable", "delai")


def _tout_a_zero(comptages: dict) -> bool:
    return all(isinstance(v, int) and v == 0 for v in comptages.values())


def _journal(operation: str, app: str, h: str, pid: str, ok: bool, maintenant) -> None:
    """Journal au mieux APRÈS un effet irréversible : une erreur disque ne change pas l'issue."""
    try:
        paquets.journaliser(operation, app, h, pid, ok, maintenant)
    except OSError:
        pass


async def _relire(ex, rec) -> bytes:
    try:
        return chiffrement.dechiffrer(await ex.lire(rec["objet"]), rec["objet"])
    except chiffrement.Illisible:
        raise RefusDonnees(409, "paquet stocké illisible (altéré ou clé changée) : "
                                "refais une vérification") from None
    except (ExecuteurErreur, chiffrement.CleAbsente, KeyError, OSError):
        raise RefusDonnees(502, "paquet stocké inaccessible : rien n'a été touché, réessaie plus "
                                "tard") from None


def _refus_app(e, avant_effacement: bool) -> RefusDonnees:
    statut = 409 if e.statut in (409, 422) else 502
    suite = " ; les données sont intactes" if avant_effacement else ""
    return RefusDonnees(statut, f"l'application refuse : {e.raison or 'erreur'}{suite}")


def _prendre(app, h):
    cible = (app.nom, h)
    if cible in _EN_COURS:
        raise RefusDonnees(409, "une opération est déjà en cours pour cet utilisateur")
    _EN_COURS.add(cible)
    return cible


async def reinitialiser_donnees(app, ex, utilisateur: str, maintenant: Optional[float] = None) -> dict:
    """Efface les données d'UN utilisateur, sous preuve fraîche (≤ 6 h), empreinte inchangée.
    Avant `app.reinitialiser` : tout échec laisse les données intactes. Après : plus aucune
    exception brute ni refus laissant croire que rien n'a eu lieu."""
    from contrats import ContratErreur
    h = paquets.empreinte_utilisateur(utilisateur)
    cible = _prendre(app, h)
    try:
        rec = paquets.dernier_verifie(app.nom, h, maintenant)           # preuve ≤ 6 h
        if rec is None:
            raise RefusDonnees(409, "aucun paquet vérifié et récent pour cet utilisateur : "
                                    "lance d'abord livraison_donnees_verifier")
        await _relire(ex, rec)                         # le paquet est TOUJOURS restituable
        try:
            _, meta = await app.exporter(utilisateur)
        except ContratErreur as e:
            raise _refus_app(e, True) from None
        if meta.get("empreinte") != rec["empreinte"]:
            raise RefusDonnees(409, "les données ont changé depuis la vérification : "
                                    "relance livraison_donnees_verifier")
        try:
            r = await app.reinitialiser(utilisateur, rec["empreinte"])
        except ContratErreur as e:
            if e.raison == "empreinte":
                raise RefusDonnees(409, "les données ont changé depuis la vérification : "
                                        "relance livraison_donnees_verifier") from None
            if e.statut is None or e.raison in _RESEAU:
                raise RefusDonnees(504, _RACINE_AMBIGU) from None   # effacement peut-être fait
            raise _refus_app(e, False) from None
        # --- ICI les données sont effacées : plus rien ne doit se lire comme « rien ne s'est passé » ---
        try:
            paquets.marquer_consomme(rec["id"], maintenant)         # d'abord, au mieux
        except OSError:
            pass
        try:
            _, apres = await app.exporter(utilisateur)
            reste = apres["comptages"]
            zero = _tout_a_zero(reste)
        except Exception:
            _journal("reinitialiser", app.nom, h, rec["id"], False, maintenant)
            raise RefusDonnees(502, "remise à zéro effectuée mais le contrôle final a échoué : "
                                    "vérifie l'état de l'application (le paquet reste "
                                    "restituable)") from None
        _journal("reinitialiser", app.nom, h, rec["id"], zero, maintenant)
        if not zero:
            raise RefusDonnees(409, "remise à zéro au résultat incomplet : des données sont réapparues (une "
                                    "opération de l'application était en cours) ; le paquet reste "
                                    "restituable, relance la vérification puis réessaie")
        supprimes = r.get("supprimes", {}) if isinstance(r, dict) else {}
        return {"ok": True, "etat": "reinitialise", "paquet_id": rec["id"], "supprimes": supprimes}
    finally:
        _EN_COURS.discard(cible)


async def restituer_donnees(app, ex, utilisateur: str, paquet_id: Optional[str] = None,
                            maintenant: Optional[float] = None) -> dict:
    from contrats import ContratErreur
    h = paquets.empreinte_utilisateur(utilisateur)
    cible = _prendre(app, h)
    try:
        if paquet_id:
            rec = paquets.lire(paquet_id)
            try:
                valide = bool(rec and rec["app"] == app.nom and rec["h"] == h
                              and rec.get("verifie_a") is not None
                              and float(rec["expire_a"]) > (maintenant if maintenant is not None
                                                            else time.time()))
            except (KeyError, TypeError, ValueError):
                valide = False
            if not valide:
                raise RefusDonnees(404, "paquet introuvable, expiré ou non vérifié pour cet "
                                        "utilisateur")
        else:
            rec = paquets.dernier_verifie(app.nom, h, maintenant, preuve_s=None,
                                          inclure_consommes=True)
            if rec is None:
                raise RefusDonnees(404, "aucun paquet vérifié disponible pour cet utilisateur")
        clair = await _relire(ex, rec)
        try:
            await app.importer(utilisateur, clair)
            _, apres = await app.exporter(utilisateur)
        except ContratErreur as e:
            _journal("restituer", app.nom, h, rec["id"], False, maintenant)
            if e.statut is None or e.raison in _RESEAU:
                raise RefusDonnees(504, "l'application n'a pas répondu : la restitution a peut-être "
                                        "été appliquée, vérifie l'état avant de réessayer") from None
            raise _refus_app(e, False) from None
        if apres["empreinte"] != rec["empreinte"]:
            _journal("restituer", app.nom, h, rec["id"], False, maintenant)
            raise RefusDonnees(409, "restitution incomplète : l'état restauré ne correspond pas "
                                    "au paquet")
        _journal("restituer", app.nom, h, rec["id"], True, maintenant)
        return {"ok": True, "etat": "restitue", "paquet_id": rec["id"],
                "comptages": apres["comptages"]}
    finally:
        _EN_COURS.discard(cible)
