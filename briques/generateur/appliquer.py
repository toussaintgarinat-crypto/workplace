"""« Appliquer l'incrément » — régénération enrichie post-revue (S32).

S31 mesure l'usage **consenti** et **propose** un incrément ; l'humain le **valide**.
S32 franchit le dernier pas, sous garde-fou : une proposition **validée** est appliquée
en réinjectant les **modules proposés** dans le plan livré, puis l'app est **régénérée**
(même gabarit). C'est le « contrat d'évolution » du backlog rendu mécanique — l'app livrée
cesse d'être un coup unique (du one-shot au **revenu récurrent**).

Garde-fous (la chaîne **proposer ≠ valider ≠ appliquer**) :
  • on n'applique QUE si la revue est au statut « validee » (sinon refus côté `main.py`) ;
  • **idempotent** : un module dont l'id existe déjà dans le plan n'est jamais dupliqué ;
  • **non destructif** : les modules dormants ne sont PAS supprimés (perte de données) —
    leur retrait éventuel reste une décision humaine séparée, hors de ce module ;
  • **honnête** : si la proposition ne contient aucun nouveau module (repli heuristique,
    ou incrément déjà appliqué), on n'invente rien — `construire_plan_enrichi` renvoie
    une liste d'ajouts vide et l'appelant le signale franchement.

Module pur (aucun réseau, aucun secret) : construit le plan enrichi, la régénération HTML
reste au gabarit via son contrat. Ne lève jamais sur des entrées tolérées.
"""
import re

# Schéma générique d'un module fraîchement proposé : on ne connaît pas son schéma fin
# (le LLM n'a donné qu'un nom + une raison), on pose des champs CRUD immédiatement
# utilisables. L'affinage par le LLM est une amélioration future assumée.
_CHAMPS_DEFAUT = [
    {"cle": "libelle", "label": "Libellé", "type": "texte", "options": []},
    {"cle": "statut", "label": "Statut", "type": "statut",
     "options": ["À faire", "En cours", "Terminé"]},
    {"cle": "date", "label": "Date", "type": "date", "options": []},
    {"cle": "montant", "label": "Montant", "type": "montant", "options": []},
    {"cle": "notes", "label": "Notes", "type": "texte", "options": []},
]


def _slug(nom: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (nom or "").lower()).strip("-")


def _entite_increment(eid: str, nom: str, raison: str) -> dict:
    """Entité CRUD fonctionnelle pour un module proposé (champs génériques)."""
    return {
        "id": eid,
        "nom": nom,
        "icone": "bi-stars",
        "description": (raison or "").strip(),
        "champs": [dict(c) for c in _CHAMPS_DEFAUT],
        "exemples": [],
        # Traçabilité : module né d'une revue « app vivante » (S31/S32), pas de l'audit
        # initial. Persiste dans le plan stocké ; ignoré par le moteur de rendu.
        "origine": "increment",
    }


def construire_plan_enrichi(plan: dict, proposition: dict) -> tuple[dict, list]:
    """Renvoie `(plan_enrichi, modules_ajoutes)`.

    Ajoute au plan les `modules_proposes` de la proposition (validée) comme nouvelles
    entités. **Idempotent** : ignore un module dont l'id (slug du nom) existe déjà.
    Ne lève jamais ; une proposition sans module → plan inchangé, `modules_ajoutes` vide.
    """
    plan = dict(plan or {})
    entites = [e for e in (plan.get("entites") or []) if isinstance(e, dict)]

    existants = set()
    for e in entites:
        eid = e.get("id") or _slug(e.get("nom") or "")
        if eid:
            existants.add(eid)

    ajoutes = []
    for m in (proposition or {}).get("modules_proposes") or []:
        if not isinstance(m, dict):
            continue
        nom = str(m.get("nom") or "").strip()
        eid = _slug(nom)
        if not eid or eid in existants:
            continue  # nom vide ou module déjà présent (idempotence)
        entites.append(_entite_increment(eid, nom, str(m.get("raison") or "")))
        existants.add(eid)
        ajoutes.append({"id": eid, "nom": nom})

    plan["entites"] = entites
    return plan, ajoutes
