"""Persistance du lien personnage Studio ↔ habitant world-engine (pont, voir
docs/superpowers/specs/2026-08-26-pont-studio-world-engine-design.md) : un fichier JSON
par série, séparé de la fiche série (`serie.personnages`) ET de la fiche world-engine —
décision utilisateur explicite (isole la responsabilité du lien des deux modèles de
données existants). Même idiome que `_profil_path`/`_journal_path` de `studio.py`
(fichier JSON par concept), volontairement PAS importé de `studio.py` (lirait
`STUDIO_DIR` deux fois plutôt qu'un import circulaire — `studio.py` importera ce module
en Task 4)."""
import json
import os

ATELIERS_DIR = os.getenv("STUDIO_DIR", "/data/ateliers")
PONT_DIR = os.path.join(ATELIERS_DIR, "pont")
os.makedirs(PONT_DIR, exist_ok=True)


def _pont_path(serie_id: str) -> str:
    return os.path.join(PONT_DIR, f"{serie_id}.json")


def lire_pont(serie_id: str) -> dict:
    p = _pont_path(serie_id)
    if not os.path.exists(p):
        return {"serie_id": serie_id, "monde_id": None, "habitants": {}}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _sauver(pont: dict) -> None:
    with open(_pont_path(pont["serie_id"]), "w", encoding="utf-8") as f:
        json.dump(pont, f, ensure_ascii=False, indent=2)


def fixer_monde(serie_id: str, monde_id: str) -> dict:
    pont = lire_pont(serie_id)
    pont["monde_id"] = monde_id
    _sauver(pont)
    return pont


def lier_habitant(serie_id: str, nom_cle: str, eid: str, nom_affiche: str, lie_le: str) -> dict:
    pont = lire_pont(serie_id)
    pont["habitants"][nom_cle] = {"eid": eid, "nom_affiche": nom_affiche, "lie_le": lie_le}
    _sauver(pont)
    return pont


def detacher_habitant(serie_id: str, nom_cle: str) -> dict:
    pont = lire_pont(serie_id)
    pont["habitants"].pop(nom_cle, None)
    _sauver(pont)
    return pont
