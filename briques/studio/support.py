"""Contrat de données utilisateur du Studio (S248) — export / reset / import / vérification.

LOGIQUE PURE sur les fichiers JSON du Studio, sans FastAPI. Toutes les fonctions prennent une
`racine` (défaut : le volume réel `S.ATELIERS_DIR`) : la VÉRIFICATION rejoue l'import dans un
dossier jetable puis ré-exporte, et compare l'empreinte — preuve que le paquet est restaurable.

Disposition sous la racine (identique au volume réel) :
  {id}.json                séries           profils/{id}.json            profils lecteurs
  profils/{id}-journal.json journaux        comptes/{sha256(u)[:16]}.json compte (nom de famille)
  pont/{serie_id}.json     lien personnages ↔ world-engine

Limite documentée : les médias (images, audio) des séries vivent dans d'autres briques ; le
paquet n'en contient que les références.
"""
import hashlib
import json
import os
import re
import tempfile
from typing import Optional

import contrat_donnees as C
import studio as S

APP = "studio"
VERSION_SCHEMA = "1"
# {version_source: fonction(objets) -> objets en version_source + 1}
MIGRATIONS: dict = {}

CLES = ("series", "profils", "journaux", "comptes", "ponts")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class Refus(Exception):
    def __init__(self, raison: str, detail: str = ""):
        super().__init__(f"{raison} : {detail}" if detail else raison)
        self.raison = raison


def _id_sur(valeur) -> bool:
    """Un identifiant n'entre dans un chemin que s'il est sûr (anti-évasion de la racine)."""
    return isinstance(valeur, str) and _ID.match(valeur) is not None


def _chemins(racine: str) -> dict:
    return {"series": racine, "profils": os.path.join(racine, "profils"),
            "comptes": os.path.join(racine, "comptes"), "ponts": os.path.join(racine, "pont")}


def _compte_chemin(racine: str, utilisateur: str) -> str:
    h = hashlib.sha256(utilisateur.encode("utf-8")).hexdigest()[:16]
    return os.path.join(_chemins(racine)["comptes"], f"{h}.json")


def _appartient(objet: dict, utilisateur: str, serie: bool) -> bool:
    """POINT UNIQUE du cloisonnement : à qui appartient cet objet ? (séries : identité
    normalisée comme le Studio ; profils : égalité stricte comme `_profil_de`.)"""
    if serie:
        return S.identite_effective(objet) == utilisateur
    return objet.get("cree_par") == utilisateur


def _json_dossier(dossier: str, exclure_suffixe: Optional[str] = None) -> list:
    out = []
    if not os.path.isdir(dossier):
        return out
    for fn in sorted(os.listdir(dossier)):
        chemin = os.path.join(dossier, fn)
        if not fn.endswith(".json") or not os.path.isfile(chemin):
            continue
        if exclure_suffixe and fn.endswith(exclure_suffixe):
            continue
        try:
            with open(chemin, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def _lire(chemin: str):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def exporter(utilisateur: str, racine: Optional[str] = None) -> dict:
    racine = racine or S.ATELIERS_DIR
    d = _chemins(racine)
    # Les objets à identifiant non sûr ne sont ni exportés ni (donc) supprimés : leur id
    # servirait à fabriquer un chemin.
    series = [s for s in _json_dossier(d["series"])
              if _id_sur(s.get("id")) and _appartient(s, utilisateur, True)]
    profils = [p for p in _json_dossier(d["profils"], "-journal.json")
               if _id_sur(p.get("id")) and _appartient(p, utilisateur, False)]
    journaux = []
    for p in profils:
        j = _lire(os.path.join(d["profils"], f"{p['id']}-journal.json"))
        if isinstance(j, dict) and j.get("profil_id") == p["id"]:
            journaux.append(j)
    compte = _lire(_compte_chemin(racine, utilisateur))
    ponts = []
    for s in series:
        pt = _lire(os.path.join(d["ponts"], f"{s['id']}.json"))
        if isinstance(pt, dict) and pt.get("serie_id") == s["id"]:
            ponts.append(pt)
    return {
        "series": sorted(series, key=lambda x: str(x.get("id"))),
        "profils": sorted(profils, key=lambda x: str(x.get("id"))),
        "journaux": sorted(journaux, key=lambda x: str(x.get("profil_id"))),
        "comptes": [compte] if isinstance(compte, dict) else [],
        "ponts": sorted(ponts, key=lambda x: str(x.get("serie_id"))),
    }


def _supprimer(chemin: str) -> None:
    try:
        os.remove(chemin)
    except FileNotFoundError:
        pass


def reinitialiser(utilisateur: str, empreinte_attendue: str,
                  racine: Optional[str] = None) -> dict:
    """Remet l'espace de `utilisateur` à zéro. Refuse sans l'empreinte EXACTE des données
    courantes : le paquet exporté couvre donc bien l'état qu'on s'apprête à effacer."""
    racine = racine or S.ATELIERS_DIR
    d = _chemins(racine)
    objets = exporter(utilisateur, racine)
    if C.empreinte(objets) != empreinte_attendue:
        raise Refus("empreinte", "les données ont changé depuis l'export (ou paquet d'un autre état)")
    for s in objets["series"]:
        _supprimer(os.path.join(d["series"], f"{s['id']}.json"))
    for p in objets["profils"]:
        _supprimer(os.path.join(d["profils"], f"{p['id']}.json"))
        _supprimer(os.path.join(d["profils"], f"{p['id']}-journal.json"))
    for pt in objets["ponts"]:
        _supprimer(os.path.join(d["ponts"], f"{pt['serie_id']}.json"))
    if objets["comptes"]:
        _supprimer(_compte_chemin(racine, utilisateur))
    return C.comptages(objets)


def migrer(objets: dict, version_paquet) -> dict:
    v, cible = int(version_paquet), int(VERSION_SCHEMA)
    while v < cible:
        f = MIGRATIONS.get(v)
        if f is None:
            raise Refus("migration", f"aucune migration depuis la version {v}")
        objets = f(objets)
        v += 1
    return objets


def _valider(utilisateur: str, objets: dict, racine: str) -> None:
    """Toutes les vérifications AVANT la moindre écriture."""
    d = _chemins(racine)
    if not isinstance(objets, dict) or set(objets) - set(CLES):
        raise Refus("format", "clés inattendues")
    for cle in CLES:
        if not isinstance(objets.get(cle, []), list):
            raise Refus("format", f"{cle} doit être une liste")
    ids_series, ids_profils = set(), set()
    for s in objets.get("series", []):
        if not isinstance(s, dict) or not _id_sur(s.get("id")):
            raise Refus("format", "identifiant de série invalide")
        ids_series.add(s["id"])
        if not _appartient(s, utilisateur, True):
            raise Refus("objet_etranger", "série")
        existant = _lire(os.path.join(d["series"], f"{s['id']}.json"))
        if isinstance(existant, dict) and not _appartient(existant, utilisateur, True):
            raise Refus("conflit", "série")
    for p in objets.get("profils", []):
        if not isinstance(p, dict) or not _id_sur(p.get("id")):
            raise Refus("format", "identifiant de profil invalide")
        ids_profils.add(p["id"])
        if not _appartient(p, utilisateur, False):
            raise Refus("objet_etranger", "profil")
        existant = _lire(os.path.join(d["profils"], f"{p['id']}.json"))
        if isinstance(existant, dict) and not _appartient(existant, utilisateur, False):
            raise Refus("conflit", "profil")
    for j in objets.get("journaux", []):
        if not isinstance(j, dict) or j.get("profil_id") not in ids_profils:
            raise Refus("incoherent", "journal sans profil")
    for pt in objets.get("ponts", []):
        if not isinstance(pt, dict) or pt.get("serie_id") not in ids_series:
            raise Refus("incoherent", "pont sans série")
    if len(objets.get("comptes", [])) > 1 or any(
            not isinstance(c, dict) for c in objets.get("comptes", [])):
        raise Refus("format", "compte")


def _ecrire(chemin: str, data: dict) -> None:
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, chemin)


def importer(utilisateur: str, objets: dict, racine: Optional[str] = None) -> dict:
    racine = racine or S.ATELIERS_DIR
    d = _chemins(racine)
    _valider(utilisateur, objets, racine)
    for s in objets.get("series", []):
        _ecrire(os.path.join(d["series"], f"{s['id']}.json"), s)
    for p in objets.get("profils", []):
        _ecrire(os.path.join(d["profils"], f"{p['id']}.json"), p)
    for j in objets.get("journaux", []):
        _ecrire(os.path.join(d["profils"], f"{j['profil_id']}-journal.json"), j)
    for pt in objets.get("ponts", []):
        _ecrire(os.path.join(d["ponts"], f"{pt['serie_id']}.json"), pt)
    for c in objets.get("comptes", []):
        _ecrire(_compte_chemin(racine, utilisateur), c)
    return C.comptages({k: objets.get(k, []) for k in CLES})


def verifier(octets: bytes, cle: bytes, utilisateur: str) -> dict:
    """Prouve qu'un paquet est restaurable : lecture signée, import dans un dossier JETABLE,
    ré-export, comparaison de l'empreinte. N'écrit jamais dans le volume réel."""
    meta, objets = C.lire_paquet(octets, cle, APP, utilisateur, VERSION_SCHEMA)
    objets = migrer(objets, meta["version_schema"])
    with tempfile.TemporaryDirectory() as tmp:
        importer(utilisateur, objets, racine=tmp)
        relu = exporter(utilisateur, racine=tmp)
    if C.empreinte(relu) != C.empreinte(objets):
        raise Refus("verification", "le ré-export ne redonne pas les mêmes données")
    return {"ok": True, "comptages": C.comptages(relu), "empreinte": C.empreinte(relu),
            "version_schema": meta["version_schema"]}
