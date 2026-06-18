"""Curator (S70) — le Cœur révise son propre corps à rythme régulier (façon Hermes).

C'est le dernier maillon du fil principal de l'épopée. Hermes (Nous Research) a un
« Curator » qui, périodiquement, passe en revue le système et propose ses évolutions.
Ici, sur une cadence hebdomadaire pilotée par l'horloge S29, le Cœur :

  1. se mesure (proprioception S68) ;
  2. propose une amélioration de PROMPT si un point faible le justifie (réutilise S69) ;
  3. rédige un brouillon de CAPACITÉ manquante si une faiblesse de complétude le suggère
     (cible 2) — une déclaration façon manifest S63, clairement marquée « à implémenter » ;
  4. dépose un DIGEST DE CURATION en rappel 🔔 pour que l'humain tranche.

Garde-fous, fidèles au reste de l'épopée :
  • le Curator PROPOSE et SURFACE, il n'APPLIQUE jamais — le gate humain reste maître
    (les prompts via les endpoints S69 ; les capacités via retenir/rejeter ici) ;
  • HONNÊTETÉ DURE sur les capacités : le Cœur ne sait pas fabriquer l'endpoint d'une
    brique ; un brouillon de capacité n'est donc JAMAIS auto-câblé (ce serait un outil
    cassé). Il est enregistré comme une SPÉCIFICATION à implémenter par une brique.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

import amelioration
import config_assistant
import conscience
import llm_pipeline
import outils
import proactif
import proprioception

logger = logging.getLogger(__name__)

CAPACITES_PATH = Path(os.getenv("CAPACITES_PROPOSEES_PATH", "/data/capacites_proposees.json"))


# ── Store des brouillons de capacités (spécifications à implémenter) ──────────

def _charger() -> dict:
    if not CAPACITES_PATH.exists():
        return {"brouillons": []}
    try:
        d = json.loads(CAPACITES_PATH.read_text())
        d.setdefault("brouillons", [])
        return d
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Capacités proposées illisibles (%s) — store vierge.", e)
        return {"brouillons": []}


def _sauver(data: dict) -> None:
    try:
        CAPACITES_PATH.parent.mkdir(parents=True, exist_ok=True)
        CAPACITES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except OSError as e:
        logger.warning("Capacités proposées non écrites : %s", e)


def lister_capacites() -> dict:
    data = _charger()
    return {"brouillons": sorted(data["brouillons"], key=lambda b: b.get("cree_le", ""),
                                 reverse=True)}


def _transition_capacite(id_: str, vers: str, depuis: tuple[str, ...]) -> dict:
    data = _charger()
    b = next((x for x in data["brouillons"] if x["id"] == id_), None)
    if not b:
        return {"ok": False, "erreur": "Brouillon introuvable."}
    if b["statut"] not in depuis:
        return {"ok": False, "erreur": f"Transition refusée (statut « {b['statut']} »)."}
    b["statut"] = vers
    _sauver(data)
    return {"ok": True, "brouillon": b}


def retenir_capacite(id_: str) -> dict:
    """Gate humain : retient un brouillon comme SPÉC à implémenter (depuis « propose »).
    N'active rien — c'est un cahier des charges pour une brique, pas un outil câblé."""
    return _transition_capacite(id_, "retenue", ("propose",))


def rejeter_capacite(id_: str) -> dict:
    return _transition_capacite(id_, "rejetee", ("propose", "retenue"))


# ── Rédaction d'un brouillon de capacité depuis une faiblesse ────────────────

async def _rediger_capacite(client, faiblesse: dict, anatomie: dict, conf: dict) -> dict:
    """Demande au LLM (gratuit) une déclaration de capacité plausible qui comblerait la
    faiblesse, ANCRÉE dans les organes existants. Repli honnête si Gateway KO."""
    organes = ", ".join(f"{o['brique']} ({o['organe'].split(' (')[0]})"
                        for o in anatomie.get("organes", []))
    modeles = await config_assistant.chaine_modeles(conf)
    brouillon = {
        "nom": "capacite_a_definir",
        "brique_suggeree": "(à déterminer)",
        "description": f"Capacité comblant une faiblesse de {faiblesse.get('dimension')} "
                       f"sur le flux « {faiblesse.get('flux')} ».",
        "methode": "GET",
        "chemin": "/(à définir)",
    }
    if not modeles:
        return {**brouillon, "genere_par": "template"}
    messages = [
        {"role": "system", "content":
            "Tu es un architecte d'API. À partir d'une FAIBLESSE récurrente d'un assistant "
            "et de la liste de ses ORGANES (briques), propose UNE capacité (outil) qui la "
            "comblerait. Renvoie UNIQUEMENT un JSON : "
            '{"nom":"verbe_objet","brique_suggeree":"<une brique existante ou nouvelle>",'
            '"description":"<à quoi elle sert, lecture/action>","methode":"GET|POST",'
            '"chemin":"/...","raison":"<pourquoi elle comble la faiblesse>"}. '
            "Reste réaliste : préfère une brique existante. N'invente pas de pouvoir magique."},
        {"role": "user", "content":
            f"FAIBLESSE : {json.dumps(faiblesse, ensure_ascii=False)}\nORGANES : {organes}"},
    ]
    res = await llm_pipeline.completer(messages, modeles=modeles, tools=None,
                                       temperature=0.4, max_tokens=200,
                                       response_format={"type": "json_object"},
                                       etiquette="curateur", conf=conf,
                                       trim_contexte=False, client=client)
    if not res.ok:
        return {**brouillon, "genere_par": "template"}
    try:
        d = json.loads(res.message.get("content") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {**brouillon, "genere_par": "template"}
    return {
        "nom": str(d.get("nom") or brouillon["nom"])[:60],
        "brique_suggeree": str(d.get("brique_suggeree") or "(à déterminer)")[:60],
        "description": str(d.get("description") or brouillon["description"])[:400],
        "methode": "POST" if str(d.get("methode")).upper() == "POST" else "GET",
        "chemin": str(d.get("chemin") or "/(à définir)")[:120],
        "raison": str(d.get("raison") or "")[:300],
        "genere_par": "llm",
    }


async def proposer_capacite(registre, faiblesse: dict, conf: dict,
                            client: httpx.AsyncClient) -> dict:
    """Crée un brouillon de capacité (statut `propose`) — une SPÉC, jamais un outil câblé."""
    anatomie = conscience.anatomie(registre, outils.outils_pour(registre),
                                   lambda n: outils.est_action(n, registre))
    decl = await _rediger_capacite(client, faiblesse, anatomie, conf)
    brouillon = {
        "id": uuid.uuid4().hex[:8],
        "cree_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "faiblesse": {k: faiblesse.get(k) for k in ("flux", "dimension", "score")},
        "declaration": decl,
        "statut": "propose",
        "note": "Spécification à IMPLÉMENTER par une brique (manifest `capacites`, S63). "
                "Le Cœur ne peut pas câbler un endpoint inexistant — non auto-appliqué.",
    }
    data = _charger()
    data["brouillons"].append(brouillon)
    _sauver(data)
    return brouillon


# ── Le cycle de curation (déclenché par l'horloge, cadence hebdo) ─────────────

def _aujourdhui_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _digest(mesure: dict, prompt_prop: dict | None, capacite: dict | None) -> str:
    """Texte court du rappel de curation : ce que le Cœur propose pour s'améliorer."""
    lignes = [f"Curation du {_aujourdhui_iso()} — proprioception sur {mesure.get('n', 0)} "
              f"échange(s), source {mesure.get('source')}."]
    moy = mesure.get("moyennes") or {}
    if any(v is not None for v in moy.values()):
        lignes.append("Scores moyens : " + ", ".join(
            f"{d} {moy[d]}" for d in moy if moy[d] is not None) + ".")
    if prompt_prop and prompt_prop.get("statut") == "propose":
        p = prompt_prop["proposition"]
        ev = p.get("eval") or {}
        reco = " (A/B : recommandé ✅)" if ev.get("recommande") else (
            " (A/B : non concluant)" if ev else "")
        lignes.append(f"Prompt proposé [{p['id']}] pour {p['dimension']} : "
                      f"« {p['addendum']} »{reco}. À valider.")
    if capacite:
        d = capacite["declaration"]
        lignes.append(f"Capacité esquissée [{capacite['id']}] : {d['nom']} "
                      f"(brique {d['brique_suggeree']}) — à implémenter puis retenir.")
    if not prompt_prop and not capacite:
        lignes.append("Aucune amélioration à proposer : le corps se porte bien.")
    return "\n".join(lignes)


async def curer(registre, *, forcer: bool = False, conf: dict | None = None) -> dict:
    """Un tour de curation : mesure → propositions (prompt S69 + capacité S70) → digest 🔔.

    Idempotent par jour (clé `curation:DATE`). PROPOSE et SURFACE uniquement ; n'applique
    rien. Déclenché par l'horloge (tâche `curation-hebdo` du manifest noyau)."""
    conf = conf or config_assistant.charger()
    cle = "curation:" + _aujourdhui_iso()
    proactif.init_db()
    if proactif.existe_cle(cle):
        if not forcer:
            return {"ok": True, "statut": "deja_fait", "cle": cle}
        proactif.supprimer_cle(cle)

    mesure = await proprioception.mesurer(conf=conf)
    props = mesure.get("propositions", [])
    faibles_s70 = [p for p in props if p.get("cible_sprint") == "S70"]

    # Prompt (S69) : on délègue à l'amélioration, en réutilisant la mesure déjà faite.
    prompt_prop = None
    if any(p.get("cible_sprint") == "S69" for p in props):
        prompt_prop = await amelioration.proposer(conf=conf, mesure=mesure)
        if prompt_prop.get("statut") == "propose":
            await amelioration.evaluer(prompt_prop["proposition"]["id"], conf=conf)
            prompt_prop = {"statut": "propose",
                           "proposition": amelioration._trouver(
                               amelioration._charger(), prompt_prop["proposition"]["id"])}

    # Capacité (S70) : brouillon de spéc si une faiblesse de complétude le justifie.
    capacite = None
    if faibles_s70:
        async with httpx.AsyncClient(timeout=60) as client:
            capacite = await proposer_capacite(registre, faibles_s70[0], conf, client)

    digest = _digest(mesure, prompt_prop, capacite)
    titre = "Curation du " + datetime.now(timezone.utc).strftime("%d %B")
    proactif._ajouter("curation", titre, digest, cle)
    logger.info("Curateur : digest déposé (%s ; prompt=%s ; capacité=%s).", cle,
                bool(prompt_prop), bool(capacite))
    return {
        "ok": True, "statut": "cree", "cle": cle, "digest": digest,
        "mesure": {"n": mesure.get("n"), "moyennes": mesure.get("moyennes"),
                   "points_faibles": mesure.get("points_faibles")},
        "prompt_propose": prompt_prop["proposition"]["id"] if prompt_prop else None,
        "capacite_proposee": capacite["id"] if capacite else None,
    }
