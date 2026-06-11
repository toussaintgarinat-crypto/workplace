"""« L'app vivante » — re-audit post-livraison (S31).

Une app livrée cesse d'être un coup unique : à intervalles, on **mesure son usage
réel** (combien d'enregistrements chaque module a reçus depuis la livraison) puis on
**re-audite** l'entreprise (usage + audit initial + nouveaux documents) pour
**proposer un incrément** — « le module Planning est utilisé 40×, Devis jamais ; le
Pareto a changé ; je propose X ». La proposition est **toujours à valider** avant
toute génération (cf. câblage dans `main.py`).

Architecture (noyau + briques) — fidèle au reste du générateur, aucun secret ici :
  • **mesure d'usage** : lecture de la source via le contrat de la brique « donnees »
    (`GET /apps/{app_id}/export`) ;
  • **souveraineté** : on ne mesure QUE les entités que le client a **consenti** à
    partager (liste blanche du pont S24). Ce qui n'est pas partagé reste invisible.
  • **proposition** : synthèse par le LLM (économe via le Gateway, comme l'audit) ;
    si le LLM est indisponible, **repli heuristique déterministe** — l'honnêteté
    technique du projet : on livre le signal factuel (Pareto, modules dormants) même
    sans la partie créative.

Best-effort : `mesurer_usage` ne lève jamais ; `proposer_increment` retombe sur
l'heuristique au lieu de planter.
"""
import logging

import httpx

from gateway import appeler_llm
from prompts import prompt_revue

logger = logging.getLogger(__name__)

import os

DONNEES_URL_INTERNE = os.getenv("DONNEES_URL_INTERNE", "http://host.docker.internal:5500")


# ── Mesure d'usage (consentie) ───────────────────────────────────────────────────

def _entites_du_plan(plan: dict) -> list[dict]:
    """Liste [{id, nom}] des modules opérationnels du plan livré (tolérant)."""
    out = []
    for e in (plan or {}).get("entites") or []:
        if not isinstance(e, dict):
            continue
        eid = e.get("id") or "".join(c for c in str(e.get("nom", "")).lower() if c.isalnum())
        if eid:
            out.append({"id": eid, "nom": e.get("nom") or eid})
    return out


def mesurer_usage(app_id: str, plan: dict, config_partage: dict | None) -> dict:
    """Mesure l'usage réel d'une app livrée — **uniquement sur les entités consenties**.

    `config_partage` = {"actif": bool, "entites": [...]} (consentement du pont S24).
      • actif=False → on ne mesure RIEN (souveraineté : pas de consentement, pas d'œil) ;
      • on ne compte QUE les entités en liste blanche ; les autres restent invisibles.

    Retourne un agrégat tolérant : compte par module, Pareto trié, modules **dormants**
    (consentis mais 0 enregistrement). Ne lève jamais.
    """
    modules = _entites_du_plan(plan)
    noms = {m["id"]: m["nom"] for m in modules}
    config_partage = config_partage or {}
    blanche = set(config_partage.get("entites") or [])
    non_consenties = [m["id"] for m in modules if m["id"] not in blanche]

    base = {
        "consenti": False,
        "entites_mesurees": [],
        "non_consenties": non_consenties,
        "compte": {},
        "pareto": [],
        "modules_dormants": [],
        "total_enregistrements": 0,
        "message": "",
    }

    if not config_partage.get("actif"):
        base["non_consenties"] = [m["id"] for m in modules]
        base["message"] = "partage désactivé — aucune mesure (souveraineté)"
        return base
    if not blanche:
        base["message"] = "aucune entité consentie — rien à mesurer"
        return base

    # Lecture de la source (brique donnees). Best-effort.
    try:
        with httpx.Client(timeout=30) as c:
            r = c.get(f"{DONNEES_URL_INTERNE}/apps/{app_id}/export")
            r.raise_for_status()
            entites = (r.json() or {}).get("entites", {}) or {}
    except Exception as e:
        base["consenti"] = True
        base["message"] = f"lecture donnees échouée : {e}"
        logger.warning("[revue] export donnees injoignable (app %s) : %s", app_id, e)
        return base

    compte: dict[str, int] = {}
    for eid in blanche:
        recs = entites.get(eid) or []
        compte[eid] = sum(1 for x in recs if isinstance(x, dict))

    total = sum(compte.values())
    pareto = sorted(
        (
            {
                "entite_id": eid,
                "nom": noms.get(eid, eid),
                "compte": n,
                "part_pct": round(100 * n / total, 1) if total else 0.0,
            }
            for eid, n in compte.items()
        ),
        key=lambda d: d["compte"],
        reverse=True,
    )
    dormants = [eid for eid, n in compte.items() if n == 0]

    return {
        "consenti": True,
        "entites_mesurees": sorted(blanche),
        "non_consenties": non_consenties,
        "compte": compte,
        "pareto": pareto,
        "modules_dormants": dormants,
        "total_enregistrements": total,
        "message": f"{total} enregistrement(s) sur {len(blanche)} module(s) consenti(s)",
    }


# ── Proposition d'incrément (re-audit) ───────────────────────────────────────────

def _increment_heuristique(plan: dict, usage: dict, raison: str) -> dict:
    """Repli déterministe quand le LLM est indisponible.

    On n'invente PAS de nouveau module sans le LLM (honnêteté) : on livre le signal
    factuel — Pareto d'usage + modules dormants à questionner.
    """
    noms = {m["id"]: m["nom"] for m in _entites_du_plan(plan)}
    dormants = [
        {"nom": noms.get(eid, eid),
         "raison": "aucun enregistrement depuis la livraison — module à confirmer ou retirer"}
        for eid in usage.get("modules_dormants", [])
    ]
    pareto = usage.get("pareto") or []
    if pareto:
        tete = pareto[0]
        commentaire = (
            f"Module le plus utilisé : « {tete['nom']} » "
            f"({tete['compte']} enr., {tete['part_pct']} % de l'usage)."
        )
    else:
        commentaire = "Pas encore d'usage mesurable."
    return {
        "resume": "Proposition fine indisponible sans le LLM — signal d'usage brut ci-dessous.",
        "modules_proposes": [],
        "modules_sous_utilises": dormants,
        "pareto_commentaire": commentaire,
        "source": "heuristique",
        "note": raison,
    }


async def proposer_increment(audit: dict, plan: dict, usage: dict,
                             nouveaux_docs: list[str] | None = None) -> dict:
    """Re-audite (usage + audit initial + nouveaux docs) → propose un incrément.

    Demande au LLM une proposition structurée. En cas d'échec (Gateway indisponible,
    JSON invalide), retombe sur `_increment_heuristique` — la revue aboutit toujours.
    La proposition n'engage AUCUNE génération : elle doit être validée en amont.
    """
    try:
        prompt = prompt_revue(audit, plan, usage, nouveaux_docs or [])
        brut = await appeler_llm(prompt)
    except Exception as e:
        logger.warning("[revue] LLM indisponible, repli heuristique : %s", e)
        return _increment_heuristique(plan, usage, f"LLM indisponible : {e}")

    # Normalisation tolérante de la réponse LLM.
    def _liste_objets(v) -> list[dict]:
        out = []
        for x in v or []:
            if isinstance(x, dict):
                out.append({"nom": str(x.get("nom") or x.get("module") or "?"),
                            "raison": str(x.get("raison") or x.get("justification") or "")})
            elif isinstance(x, str):
                out.append({"nom": x, "raison": ""})
        return out

    return {
        "resume": str(brut.get("resume") or brut.get("synthese") or "").strip(),
        "modules_proposes": _liste_objets(brut.get("modules_proposes")),
        "modules_sous_utilises": _liste_objets(
            brut.get("modules_sous_utilises") or brut.get("modules_dormants")
        ),
        "pareto_commentaire": str(brut.get("pareto_commentaire") or "").strip(),
        "source": "llm",
    }
