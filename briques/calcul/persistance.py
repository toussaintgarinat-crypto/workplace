"""Persistance du parc de nœuds de calcul — fusion env + fichier JSON.

Pourquoi : ``CALCUL_NOEUDS`` (env) permet de déclarer des nœuds au démarrage mais
ils sont perdus à chaque reboot si l'inscription provient de l'API dynamique (S131).
Ce module fusionne les deux sources et écrit atomiquement sur disque (write-temp +
``os.replace``) pour éviter les fichiers à moitié écrits en cas de crash.

Convention de fusion — fichier prioritaire sur env pour un même id :
  • Les nœuds env (déclarés une fois pour toutes dans la config) forment la base.
  • Les nœuds du fichier (inscrits dynamiquement via API) viennent les compléter et,
    pour un ``id`` identique, remplacer la déclaration statique. Cela garantit qu'un
    nœud réinscrit dynamiquement avec des paramètres mis à jour ne régresse pas vers
    l'ancienne valeur d'env au prochain rechargement.

Tolérance aux pannes :
  • Fichier absent → {}  (première inscription le crée).
  • Fichier corrompu / illisible → {} (le parc env reste utilisable, on ne plante pas).
  • Écriture atomique → si la machine coupe pendant l'écriture, l'ancien fichier reste
    intact (``os.replace`` est atomique sur POSIX).
"""
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

import noeud as noeud_mod

# Chemin par défaut du parc persisté. Surcharger via CALCUL_PARC_FILE (p.ex. en test).
PARC_FILE_DEFAUT = "/data/noeuds.json"


def _chemin_parc() -> Path:
    """Résout le chemin du fichier du parc depuis l'env (injectable en test)."""
    return Path(os.getenv("CALCUL_PARC_FILE", PARC_FILE_DEFAUT))


def _lire_fichier(chemin: Path) -> dict:
    """Lit le fichier JSON du parc → {id: Noeud}. Absent / illisible → {} (tolérant)."""
    if not chemin.exists():
        return {}
    try:
        texte = chemin.read_text(encoding="utf-8")
        items = json.loads(texte)
        if not isinstance(items, list):
            items = [items]
    except (OSError, ValueError, TypeError):
        return {}
    parc: dict = {}
    for it in items:
        try:
            n = noeud_mod.Noeud.from_dict(it)
            parc[n.id] = n
        except (ValueError, TypeError):
            continue          # entrée bancale ignorée
    return parc


def _lire_items_bruts(chemin: Path) -> list:
    """Lit les items bruts du fichier (pour modification partielle). Absent → []."""
    if not chemin.exists():
        return []
    try:
        items = json.loads(chemin.read_text(encoding="utf-8"))
        return items if isinstance(items, list) else [items]
    except (OSError, ValueError, TypeError):
        return []


def _ecrire_atomique(chemin: Path, items: list) -> None:
    """Écrit la liste JSON atomiquement : fichier temp dans le même répertoire + os.replace."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=chemin.parent, suffix=".tmp")
    try:
        os.close(fd)
        Path(tmp).write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, chemin)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def charger_parc(brut_env: Optional[str] = None) -> dict:
    """Fusionne le parc env (CALCUL_NOEUDS) + fichier (CALCUL_PARC_FILE) → {id: Noeud}.

    Le fichier a la priorité sur l'env pour un même id (voir module docstring).
    Tolérant : une source absente ou illisible ne plante pas — on continue avec l'autre.
    """
    depuis_env = noeud_mod.charger_noeuds(brut_env)
    depuis_fichier = _lire_fichier(_chemin_parc())
    # env d'abord → fichier vient écraser à la même clé (fichier prioritaire)
    return {**depuis_env, **depuis_fichier}


def sauver_noeud(n: noeud_mod.Noeud) -> None:
    """Ajoute ou met à jour le nœud dans le fichier persisté (écriture atomique).

    Un nœud existant avec le même id est remplacé ; les autres nœuds restent intacts.
    Si le fichier n'existe pas, il est créé (y compris les répertoires parents).
    """
    chemin = _chemin_parc()
    items = [it for it in _lire_items_bruts(chemin) if str(it.get("id") or "") != n.id]
    items.append(n.to_dict())
    _ecrire_atomique(chemin, items)


def retirer_noeud(nid: str) -> bool:
    """Supprime le nœud d'id donné du fichier persisté. Retourne True si effectivement trouvé.

    Si le fichier est absent ou le nœud introuvable, retourne False sans erreur.
    """
    chemin = _chemin_parc()
    items = _lire_items_bruts(chemin)
    avant = len(items)
    items = [it for it in items if str(it.get("id") or "") != nid]
    if len(items) == avant:
        return False
    _ecrire_atomique(chemin, items)
    return True
