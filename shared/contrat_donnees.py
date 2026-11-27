"""Contrat d'app « données utilisateur » (S248) — bibliothèque partagée, stdlib seule.

Une app qui veut la portée « par utilisateur » déclare un bloc `contrat_donnees` dans son
manifeste et expose trois routes internes (exporter / réinitialiser / importer). Ce module
fournit le PAQUET échangé : une archive tar.gz de deux membres,
  • `meta.json`    : app, utilisateur, version_schema, date, comptages par type, empreinte
                     des données, signature HMAC-SHA256 de tout le reste ;
  • `donnees.json` : les données de CET utilisateur, JSON canonique.
L'assistant ne manipule que `meta` (jamais `donnees`). Source unique = `shared/` ; copiée dans
chaque brique par `outils/sync_socle.sh` (chaque brique est une image autonome).
"""
import hashlib
import hmac
import io
import json
import tarfile
import zlib
from datetime import datetime, timezone
from typing import Optional

FORMAT = 1
TAILLE_MAX = 64 * 1024 * 1024
MEMBRES = ("meta.json", "donnees.json")
ACTIONS = ("exporter", "reinitialiser", "importer")


class PaquetInvalide(Exception):
    def __init__(self, raison: str, detail: str = ""):
        super().__init__(f"{raison} : {detail}" if detail else raison)
        self.raison = raison


def _canon(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def empreinte(objets: dict) -> str:
    return hashlib.sha256(_canon(objets)).hexdigest()


def comptages(objets: dict) -> dict:
    return {k: len(v) for k, v in sorted(objets.items())}


def _signer(meta_sans_signature: dict, cle: bytes) -> str:
    return hmac.new(cle, _canon(meta_sans_signature), hashlib.sha256).hexdigest()


def _version(v) -> int:
    try:
        n = int(str(v))
    except ValueError:
        raise PaquetInvalide("format", "version_schema non numérique")
    if n < 0:
        raise PaquetInvalide("format", "version_schema négative")
    return n


def construire_paquet(app: str, utilisateur: str, version_schema: str, objets: dict,
                      cle: bytes, maintenant: Optional[datetime] = None) -> bytes:
    donnees = _canon(objets)
    meta = {
        "format": FORMAT, "app": app, "utilisateur": utilisateur,
        "version_schema": str(version_schema),
        "cree_le": (maintenant or datetime.now(timezone.utc)).isoformat(),
        "comptages": comptages(objets),
        "empreinte": hashlib.sha256(donnees).hexdigest(),
    }
    meta["signature"] = _signer(meta, cle)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for nom, contenu in (("meta.json", _canon(meta)), ("donnees.json", donnees)):
            info = tarfile.TarInfo(nom)
            info.size = len(contenu)
            t.addfile(info, io.BytesIO(contenu))
    return buf.getvalue()


def _lire_membres(octets: bytes) -> dict:
    if len(octets) > TAILLE_MAX:
        raise PaquetInvalide("trop_gros")
    out: dict = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(octets), mode="r:gz") as t:
            for m in t:   # taille vérifiée AVANT de décompresser le membre (anti bombe)
                if m.name not in MEMBRES or not m.isfile() or m.name in out:
                    raise PaquetInvalide("illisible", "contenu inattendu")
                if m.size > TAILLE_MAX:
                    raise PaquetInvalide("trop_gros")
                out[m.name] = t.extractfile(m).read()
    except (tarfile.TarError, OSError, EOFError, zlib.error) as e:
        raise PaquetInvalide("illisible", type(e).__name__) from e
    if set(out) != set(MEMBRES):
        raise PaquetInvalide("illisible", "membre manquant")
    return out


def lire_paquet(octets: bytes, cle: bytes, app: str, utilisateur: str,
                version_schema_app: str) -> tuple:
    """Vérifie (dans cet ordre) lisibilité, signature, somme de contrôle, app, utilisateur,
    version. Renvoie `(meta, objets)` ou lève `PaquetInvalide`."""
    membres = _lire_membres(octets)
    try:
        meta = json.loads(membres["meta.json"])
        if not isinstance(meta, dict):
            raise ValueError
    except ValueError:
        raise PaquetInvalide("illisible", "meta.json")
    signature = meta.pop("signature", "")
    if not isinstance(signature, str) or not hmac.compare_digest(signature, _signer(meta, cle)):
        raise PaquetInvalide("signature")
    if meta.get("format") != FORMAT:
        raise PaquetInvalide("format")
    if hashlib.sha256(membres["donnees.json"]).hexdigest() != meta.get("empreinte"):
        raise PaquetInvalide("somme_controle")
    try:
        objets = json.loads(membres["donnees.json"])
        if not isinstance(objets, dict):
            raise ValueError
    except ValueError:
        raise PaquetInvalide("illisible", "donnees.json")
    if meta.get("app") != app:
        raise PaquetInvalide("app")
    if meta.get("utilisateur") != utilisateur:
        raise PaquetInvalide("utilisateur")
    if _version(meta.get("version_schema")) > _version(version_schema_app):
        raise PaquetInvalide("version_future")
    return meta, objets


def valider_bloc_contrat(bloc) -> list:
    """Erreurs du bloc `contrat_donnees` d'un manifeste (liste vide = conforme)."""
    if not isinstance(bloc, dict):
        return ["contrat_donnees absent ou n'est pas un objet"]
    erreurs = []
    v = bloc.get("version_schema")
    if not (isinstance(v, str) and v.isdigit()):
        erreurs.append("version_schema doit être une chaîne numérique")
    for action in ACTIONS:
        a = bloc.get(action)
        if not isinstance(a, dict):
            erreurs.append(f"{action} manquant")
            continue
        if a.get("methode") != "POST":
            erreurs.append(f"{action}.methode doit être POST")
        chemin = a.get("chemin")
        if not (isinstance(chemin, str) and chemin.startswith("/support/")):
            erreurs.append(f"{action}.chemin doit commencer par /support/")
    return erreurs
