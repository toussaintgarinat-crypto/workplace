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

La construction du plan enrichi est **pure** (déterministe, testable). L'enrichissement
du schéma des modules par le LLM (S34) est une couche **async** optionnelle, best-effort,
qui retombe sur le schéma générique si le Gateway est indisponible — l'application aboutit
toujours. La régénération HTML reste au gabarit via son contrat. Aucun secret ici.
"""
import logging
import re

logger = logging.getLogger(__name__)

# Schéma générique d'un module fraîchement proposé : repli quand on ne dispose pas du
# schéma fin (LLM indisponible). Champs CRUD passe-partout, immédiatement utilisables.
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


_TYPES_VALIDES = ("texte", "nombre", "montant", "date", "statut")


def _entite_increment(eid: str, nom: str, raison: str,
                      champs: list | None = None, icone: str | None = None) -> dict:
    """Entité fonctionnelle pour un module proposé.

    `champs`/`icone` fournis (schéma fin LLM, S34) → utilisés ; sinon champs CRUD
    génériques (repli). Le gabarit normalise les champs ; on garantit juste une liste non
    vide et bien formée.
    """
    return {
        "id": eid,
        "nom": nom,
        "icone": icone or "bi-stars",
        "description": (raison or "").strip(),
        "champs": champs if champs else [dict(c) for c in _CHAMPS_DEFAUT],
        "exemples": [],
        # Traçabilité : module né d'une revue « app vivante » (S31/S32), pas de l'audit
        # initial. Persiste dans le plan stocké ; ignoré par le moteur de rendu.
        "origine": "increment",
    }


def _modules_a_ajouter(plan: dict, proposition: dict) -> tuple[list, set]:
    """Modules proposés réellement nouveaux (idempotence) + ids déjà présents.

    Renvoie `([{nom, raison}], ids_existants)` — partagé par les variantes synchrone et
    LLM pour garantir la **même** règle d'idempotence.
    """
    entites = [e for e in (plan or {}).get("entites") or [] if isinstance(e, dict)]
    existants = {e.get("id") or _slug(e.get("nom") or "") for e in entites}
    existants.discard("")

    nouveaux, vus = [], set()
    for m in (proposition or {}).get("modules_proposes") or []:
        if not isinstance(m, dict):
            continue
        nom = str(m.get("nom") or "").strip()
        eid = _slug(nom)
        if not eid or eid in existants or eid in vus:
            continue
        vus.add(eid)
        nouveaux.append({"id": eid, "nom": nom, "raison": str(m.get("raison") or "")})
    return nouveaux, existants


def construire_plan_enrichi(plan: dict, proposition: dict) -> tuple[dict, list]:
    """Renvoie `(plan_enrichi, modules_ajoutes)` — schéma générique (déterministe, S32).

    Ajoute au plan les `modules_proposes` (validés) comme nouvelles entités CRUD.
    **Idempotent** : ignore un module dont l'id (slug du nom) existe déjà. Ne lève jamais.
    """
    plan = dict(plan or {})
    entites = [e for e in (plan.get("entites") or []) if isinstance(e, dict)]
    nouveaux, _ = _modules_a_ajouter(plan, proposition)

    ajoutes = []
    for m in nouveaux:
        entites.append(_entite_increment(m["id"], m["nom"], m["raison"]))
        ajoutes.append({"id": m["id"], "nom": m["nom"]})

    plan["entites"] = entites
    return plan, ajoutes


def _normaliser_champs(brut) -> list | None:
    """Champs d'un schéma LLM → forme attendue ({cle,label,type,options}). None si vide."""
    out = []
    for c in brut or []:
        if not isinstance(c, dict):
            continue
        label = str(c.get("label") or c.get("cle") or "").strip()
        cle = c.get("cle") or "".join(ch for ch in label.lower() if ch.isalnum())
        if not cle:
            continue
        typ = c.get("type") if c.get("type") in _TYPES_VALIDES else "texte"
        options = c.get("options") or [] if typ == "statut" else []
        out.append({"cle": cle, "label": label or cle, "type": typ,
                    "options": [str(o) for o in options]})
    return out or None


async def _schema_module_llm(audit: dict, nom_entreprise: str, module: dict,
                             langue: str = "fr") -> dict:
    """Schéma fin d'un module via le LLM (S34). Best-effort : repli silencieux → {}."""
    try:
        from gateway import appeler_llm
        from prompts import prompt_schema_module
        brut = await appeler_llm(
            prompt_schema_module(nom_entreprise, module["nom"], module["raison"], audit, langue),
            langue)
        champs = _normaliser_champs(brut.get("champs"))
        icone = brut.get("icone") if isinstance(brut.get("icone"), str) else None
        return {"champs": champs, "icone": icone} if champs else {}
    except Exception as e:  # Gateway KO, JSON invalide… → repli générique
        logger.warning("[appliquer] schéma LLM indisponible pour « %s » : %s",
                       module.get("nom"), e)
        return {}


async def construire_plan_enrichi_llm(plan: dict, proposition: dict,
                                      audit: dict | None = None,
                                      langue: str = "fr") -> tuple[dict, list]:
    """Comme `construire_plan_enrichi`, mais demande au LLM un **schéma fin** par module
    (S34), dans le vocabulaire de l'entreprise. Repli sur le schéma générique si le LLM
    est indisponible — l'application aboutit toujours. `modules_ajoutes` indique la
    `source` du schéma (`llm` | `generique`). `langue` = langue de l'app (S37).
    """
    plan = dict(plan or {})
    entites = [e for e in (plan.get("entites") or []) if isinstance(e, dict)]
    nouveaux, _ = _modules_a_ajouter(plan, proposition)
    nom_ent = (audit or {}).get("nom_entreprise") or plan.get("nom_app") or "l'entreprise"

    ajoutes = []
    for m in nouveaux:
        fin = await _schema_module_llm(audit or {}, nom_ent, m, langue)
        source = "llm" if fin.get("champs") else "generique"
        entites.append(_entite_increment(m["id"], m["nom"], m["raison"],
                                         champs=fin.get("champs"), icone=fin.get("icone")))
        ajoutes.append({"id": m["id"], "nom": m["nom"], "schema": source})

    plan["entites"] = entites
    return plan, ajoutes
