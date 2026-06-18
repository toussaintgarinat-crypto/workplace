"""Stockage JSON persistant de la brique — un volume, des petits fichiers.

Tout l'état de la brique (historiques de conversation, table de correspondance,
décalage de polling Telegram) vit sous `CONNEXION_DIR`. On garde un format simple et
lisible (JSON indenté), façon `STUDIO_DIR` du Studio : pas de base, pas de schéma à migrer.
"""
import json
import os
from pathlib import Path


def dossier() -> Path:
    """Répertoire de persistance (créé au besoin). Surchargé par `CONNEXION_DIR`."""
    d = Path(os.getenv("CONNEXION_DIR", "/data/connexion"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def lire_json(nom: str, defaut):
    """Lit `nom` (chemin relatif au dossier) ; rend `defaut` si absent ou illisible."""
    f = dossier() / nom
    if not f.exists():
        return defaut
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — un fichier corrompu ne doit pas tuer la brique
        return defaut


def ecrire_json(nom: str, data) -> None:
    """Écrit `data` en JSON dans `nom` (crée les sous-dossiers au besoin)."""
    f = dossier() / nom
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def slug(valeur: str) -> str:
    """Rend une chaîne sûre pour un nom de fichier (id externe, nom de réseau)."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(valeur))[:120] or "_"
