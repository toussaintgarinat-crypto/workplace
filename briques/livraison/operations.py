"""État persistant des opérations longues (reset bleu/vert) par application.

Contrairement à `repere_rollback`, les erreurs disque ne sont PAS avalées : une opération
dont on ne peut pas persister l'état ne démarre pas, et l'état précédent reste intact
(écriture atomique tmp + fsync + os.replace). La brique tourne avec un seul worker ; un
verrou de module protège le lire-modifier-écrire entre threads.
"""
import copy
import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)
_verrou = threading.RLock()
ETATS_FINAUX = {"reussie", "echec", "interrompue"}
MESSAGE_MAX = 300
CLES_RESERVEES = {"id", "etat", "type", "debut", "fin", "message"}
_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class OperationEnCours(Exception):
    pass


class OperationInconnue(Exception):
    pass


def _chemin() -> Path:
    return Path(os.getenv("LIVRAISON_DATA", "/data")) / "operations.json"


def _mettre_de_cote(p: Path) -> None:
    try:
        os.replace(p, p.with_name(p.name + ".corrompu"))
    except OSError:
        log.warning("operations.json corrompu : mise de côté impossible")


def _lire_tout() -> dict:
    """Seuls fichier absent, JSON invalide ou racine non-objet valent « état vide » ; toute
    autre erreur de lecture (permission, EIO) se propage pour ne rien écraser."""
    p = _chemin()
    try:
        d = json.loads(p.read_text())
    except FileNotFoundError:
        return {}
    except ValueError:
        d = None
    if not isinstance(d, dict):
        log.warning("operations.json corrompu : mis de côté (.corrompu), état repris à vide")
        _mettre_de_cote(p)
        return {}
    return d


def _ecrire_tout(tout: dict) -> None:
    p = _chemin()
    donnees = json.dumps(tout)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w") as f:
        f.write(donnees)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    try:
        fd = os.open(p.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass  # fsync du dossier : meilleur effort (le fichier lui-même est déjà synchronisé)


def _propre(message: Optional[str]) -> Optional[str]:
    if message is None:
        return None
    return _CTRL.sub("", str(message))[:MESSAGE_MAX]


def lire(app: str) -> Optional[dict]:
    with _verrou:
        r = _lire_tout().get(app)
        return copy.deepcopy(r) if isinstance(r, dict) else None


def _entree(tout: dict, app: str) -> dict:
    e = tout.get(app)
    if not isinstance(e, dict):
        e = tout[app] = {}
    return e


def _op_en_cours(tout: dict, app: str, operation_id: str) -> dict:
    e = tout.get(app)
    op = e.get("op") if isinstance(e, dict) else None
    if not isinstance(op, dict) or op.get("etat") != "en_cours" or op.get("id") != operation_id:
        raise OperationInconnue(f"aucune opération en cours « {operation_id} » pour {app}")
    return op


def demarrer(app: str, type_: str) -> str:
    with _verrou:
        tout = _lire_tout()
        e = tout.get(app)
        op = e.get("op") if isinstance(e, dict) else None
        if isinstance(op, dict) and op.get("etat") == "en_cours":
            raise OperationEnCours(f"une opération est déjà en cours pour {app}")
        oid = uuid.uuid4().hex
        _entree(tout, app)["op"] = {"id": oid, "type": type_, "etat": "en_cours", "etape": None,
                                    "debut": time.time(), "fin": None, "message": None,
                                    "essais": 1}
        _ecrire_tout(tout)
        return oid


def etape(app: str, operation_id: str, nom: str, **extra) -> None:
    with _verrou:
        tout = _lire_tout()
        op = _op_en_cours(tout, app, operation_id)
        for k in extra:
            if k in CLES_RESERVEES:
                raise ValueError(f"clé réservée : {k}")
        op.update(extra)
        op["etape"] = nom
        _ecrire_tout(tout)


def terminer(app: str, operation_id: str, etat: str, message: Optional[str] = None) -> None:
    if etat not in ETATS_FINAUX:
        raise ValueError(f"état final invalide : {etat!r}")
    with _verrou:
        tout = _lire_tout()
        op = _op_en_cours(tout, app, operation_id)
        op.update(etat=etat, fin=time.time(), message=_propre(message))
        _ecrire_tout(tout)


def enregistrer_emplacements(app: str, a: dict, b: dict, actif: str, base_active: str) -> None:
    """Pensé pour le premier provisionnement du jumeau ; préserve un `base_precedente` existant."""
    with _verrou:
        tout = _lire_tout()
        e = _entree(tout, app)
        e.update(emplacements={"A": dict(a), "B": dict(b)}, actif=actif,
                 base_active=base_active)
        e.setdefault("base_precedente", None)
        _ecrire_tout(tout)


def basculer_etat(app: str, actif: str, base_active: str, base_precedente: Optional[str],
                  precedente_protegee: bool = False) -> None:
    """`precedente_protegee` (posé par un retour arrière, effacé par un reset réussi) : la base
    précédente porte les écritures les plus récentes de l'instance quittée ; le reset suivant
    ne doit PAS la supprimer comme « N-2 ». Écrit dans la MÊME écriture atomique que la bascule."""
    with _verrou:
        tout = _lire_tout()
        e = _entree(tout, app)
        e.update(actif=actif, base_active=base_active, base_precedente=base_precedente,
                 retour_invalide=False, precedente_protegee=bool(precedente_protegee))
        _ecrire_tout(tout)


def precedente_protegee(etat: Optional[dict]) -> bool:
    return isinstance(etat, dict) and etat.get("precedente_protegee") is True


def invalider_retour(app: str) -> None:
    """L'emplacement inactif ne porte plus la génération précédente (un reset a réécrit son env
    puis échoué) : le retour arrière est refusé jusqu'à la prochaine bascule réussie.
    `base_precedente` est gardée pour que le reset suivant la nettoie."""
    with _verrou:
        tout = _lire_tout()
        _entree(tout, app)["retour_invalide"] = True
        _ecrire_tout(tout)


def marquer_interrompues() -> list:
    with _verrou:
        tout = _lire_tout()
        changes = []
        for app, e in tout.items():
            op = e.get("op") if isinstance(e, dict) else None
            if isinstance(op, dict) and op.get("etat") == "en_cours":
                message = "la brique a redémarré pendant l'opération"
                neuve = op.get("base_neuve")
                if isinstance(neuve, str) and neuve and neuve != e.get("base_active"):
                    if op.get("etape") in ("sauvegarde", "bascule"):
                        # Les hôtes ont peut-être déjà été échangés : la base neuve peut être
                        # la base EN SERVICE. Ne rien supprimer avant d'avoir vérifié les domaines.
                        message += (f" ; base neuve {neuve} peut-être EN SERVICE : vérifier les "
                                    "domaines avant toute action, ne pas la supprimer")
                    else:
                        message += f" ; base neuve {neuve} peut-être orpheline (à vérifier)"
                op.update(etat="interrompue", fin=time.time(), message=_propre(message))
                changes.append(app)
        if changes:
            _ecrire_tout(tout)
        return changes
