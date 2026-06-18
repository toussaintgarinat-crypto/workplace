"""Auto-amélioration des PROMPTS (S69) — cible 1 de l'épopée « Organisme vivant ».

S68 a donné au Cœur la proprioception (il note ses propres réponses et REPÈRE des points
faibles). S69 ferme la première boucle d'auto-évolution : à partir d'un point faible
côté PROMPT, le Cœur PROPOSE une variante (un addendum d'instruction système), la met à
l'épreuve en A/B, et — seulement après accord humain — l'ACTIVE.

Inspiré de GEPA (réflexion sur les échecs → mutation guidée du prompt), mais cadré par
les deux invariants du projet :
  • PROPOSER ≠ VALIDER ≠ APPLIQUER (calque `revue.py`/`appliquer.py` S31-34) : rien ne
    s'active sans gate humain ; `appliquer` refuse une proposition non validée ;
  • A/B HONNÊTE (esprit `shadow.py`) : on REJOUE un échantillon de vraies questions sous
    le prompt actuel vs le prompt + addendum, on fait noter les deux par le juge S68, et on
    ne recommande que si la dimension visée progresse SANS régression ailleurs.

Le Cœur ne réécrit JAMAIS son prompt fondateur : il n'y AJOUTE qu'un court addendum,
réversible (`desactiver`) et unique (un seul addendum actif à la fois). Souveraineté du
plan de contrôle : la mutation est bornée, observable, validée à la main.
"""
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

import config_assistant
import langue as langue_mod
import llm_pipeline
import proprioception

logger = logging.getLogger(__name__)

STORE_PATH = Path(os.getenv("AMELIORATION_PATH", "/data/ameliorations.json"))
ECHANTILLON_AB = int(os.getenv("AMELIORATION_ECHANTILLON", "4"))
SEUIL_GAIN = float(os.getenv("AMELIORATION_SEUIL_GAIN", "0.05"))      # gain mini sur la cible
SEUIL_REGRESSION = float(os.getenv("AMELIORATION_SEUIL_REGRESSION", "0.10"))  # chute tolérée ailleurs

# Repli honnête : un addendum générique par dimension si le LLM réflexif est injoignable.
_TEMPLATES = {
    "honnetete": "Rappel : n'affirme jamais un fait que tes outils n'ont pas confirmé ; "
                 "dis clairement ce que tu ignores plutôt que de le deviner.",
    "pertinence": "Rappel : réponds d'abord précisément à la question posée avant "
                  "d'élargir ; ne t'écarte pas du sujet.",
    "completude": "Rappel : donne une réponse complète et actionnable ; si une "
                  "information manque, indique l'étape suivante.",
}


# ── Store (side-car JSON, propre au plan de contrôle) ────────────────────────

def _charger() -> dict:
    if not STORE_PATH.exists():
        return {"propositions": [], "actif_id": None}
    try:
        d = json.loads(STORE_PATH.read_text())
        d.setdefault("propositions", [])
        d.setdefault("actif_id", None)
        return d
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Améliorations illisibles (%s) — store vierge.", e)
        return {"propositions": [], "actif_id": None}


def _sauver(data: dict) -> None:
    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except OSError as e:
        logger.warning("Améliorations non écrites : %s", e)


def _trouver(data: dict, id_: str) -> dict | None:
    return next((p for p in data["propositions"] if p["id"] == id_), None)


def addendum_actif() -> str:
    """Addendum d'instruction système actuellement ACTIF (vide si aucun). Lu à chaud par
    l'assistant — défensif : ne casse jamais une conversation."""
    try:
        data = _charger()
        if not data.get("actif_id"):
            return ""
        p = _trouver(data, data["actif_id"])
        if p and p.get("statut") == "applique" and p.get("addendum"):
            return "\n- " + p["addendum"].strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def lister() -> dict:
    """Toutes les propositions (plus récentes d'abord) + l'addendum actif."""
    data = _charger()
    props = sorted(data["propositions"], key=lambda p: p.get("cree_le", ""), reverse=True)
    return {"propositions": props, "actif_id": data.get("actif_id"),
            "addendum_actif": addendum_actif().strip()}


# ── Proposer : réflexion sur un point faible → addendum candidat ─────────────

async def _generer_addendum(client, dimension: str, flux: str, exemples: list[dict],
                            conf: dict) -> tuple[str, bool]:
    """Demande au LLM réflexif (gratuit) un court addendum qui corrige le point faible.

    Renvoie (addendum, par_llm). Repli sur un template honnête si Gateway/LLM KO."""
    modeles = await config_assistant.chaine_modeles(conf)
    gabarit = _TEMPLATES.get(dimension, _TEMPLATES["pertinence"])
    if not modeles:
        return gabarit, False
    extraits = "\n".join(f"- Q: {e.get('question','')[:200]}\n  R: {e.get('reponse','')[:300]}"
                         for e in exemples[:3])
    messages = [
        {"role": "system", "content":
            "Tu es un ingénieur de prompts. On te donne une faiblesse RÉCURRENTE des "
            "réponses d'un assistant (dimension + exemples). Propose UNE seule consigne "
            "système COURTE (1 phrase, ≤ 30 mots, impérative) qui corrigerait ce défaut "
            "SANS contredire l'honnêteté ni la souveraineté de l'assistant. Réponds par la "
            "consigne SEULE, sans guillemets ni préambule."},
        {"role": "user", "content":
            f"Dimension faible : {dimension} (flux « {flux} »).\nExemples :\n{extraits}"},
    ]
    res = await llm_pipeline.completer(messages, modeles=modeles, tools=None,
                                       temperature=0.4, max_tokens=80,
                                       etiquette="amelioration", conf=conf,
                                       trim_contexte=False, client=client)
    if not res.ok:
        return gabarit, False
    texte = (res.message.get("content") or "").strip().strip('"').strip()
    return (texte or gabarit), bool(texte)


async def proposer(conf: dict | None = None, mesure: dict | None = None) -> dict:
    """Mesure la proprioception et, s'il existe un point faible côté PROMPT, propose un
    addendum candidat (statut `propose`, INACTIF). Aucun effet sur les conversations.

    `mesure` : proprioception déjà calculée (réutilisée par le Curator S70 pour ne pas la
    relancer) ; None → on la calcule."""
    conf = conf or config_assistant.charger()
    mesure = mesure if mesure is not None else await proprioception.mesurer(conf=conf)
    cibles = [p for p in mesure.get("propositions", []) if p.get("cible_sprint") == "S69"]
    if not cibles:
        return {"statut": "rien_a_proposer",
                "raison": "Aucun point faible côté prompt dans la proprioception récente.",
                "mesure": mesure}

    pire = cibles[0]  # déjà triées par score croissant (le plus faible d'abord)
    dimension, flux = pire["dimension"], pire["flux"]
    exemples = [l for l in proprioception._lignes(40) if (l.get("etiquette") or "chat") == flux]
    async with httpx.AsyncClient(timeout=60) as client:
        addendum, par_llm = await _generer_addendum(client, dimension, flux, exemples, conf)

    prop = {
        "id": uuid.uuid4().hex[:8],
        "cree_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dimension": dimension,
        "flux": flux,
        "score_observe": pire["score"],
        "addendum": addendum,
        "genere_par": "llm" if par_llm else "template",
        "raison": pire["suggestion"],
        "statut": "propose",
        "eval": None,
    }
    data = _charger()
    data["propositions"].append(prop)
    _sauver(data)
    return {"statut": "propose", "proposition": prop}


# ── Évaluer : A/B honnête (prompt actuel vs prompt + addendum) ───────────────

def _systeme_base(conf: dict) -> str:
    """Prompt système de référence pour l'A/B (cœur + langue, sans persona ni addendum).

    Import LOCAL d'`assistant` : il importe ce module (`addendum_actif`) — on casse le
    cycle en n'accédant à `PROMPT_SYSTEME` qu'au moment de l'appel."""
    import assistant
    return assistant.PROMPT_SYSTEME + "\n- " + langue_mod.consigne_reponse(conf.get("langue"))


async def _reponse(client, question: str, systeme: str, modeles: list, conf: dict) -> str:
    res = await llm_pipeline.completer(
        [{"role": "system", "content": systeme}, {"role": "user", "content": question}],
        modeles=modeles, tools=None, temperature=0.2, max_tokens=400,
        etiquette="amelioration", conf=conf, trim_contexte=False, client=client)
    return (res.message.get("content") or "") if res.ok else ""


async def evaluer(id_: str, conf: dict | None = None, echantillon: int | None = None) -> dict:
    """A/B : rejoue un échantillon de questions du flux sous le prompt ACTUEL vs + addendum,
    fait noter les deux par le juge (S68), et recommande si la cible progresse sans régresser."""
    conf = conf or config_assistant.charger()
    data = _charger()
    prop = _trouver(data, id_)
    if not prop:
        return {"ok": False, "erreur": "Proposition introuvable."}

    n = echantillon or ECHANTILLON_AB
    questions = [l.get("question", "") for l in proprioception._lignes(80)
                 if (l.get("etiquette") or "chat") == prop["flux"] and l.get("question")][-n:]
    if not questions:
        return {"ok": False, "erreur": "Aucune question tracée pour ce flux."}

    base = _systeme_base(conf)
    avec = base + "\n- " + prop["addendum"].strip()
    modeles = await config_assistant.chaine_modeles(conf)
    if not modeles:
        return {"ok": False, "erreur": "Aucun modèle disponible pour l'évaluation."}

    notes_avant, notes_apres = [], []
    async with httpx.AsyncClient(timeout=90) as client:
        for q in questions:
            r_av = await _reponse(client, q, base, modeles, conf)
            r_ap = await _reponse(client, q, avec, modeles, conf)
            notes_avant.append(await proprioception._juger(client, {"question": q, "reponse": r_av}, conf))
            notes_apres.append(await proprioception._juger(client, {"question": q, "reponse": r_ap}, conf))

    avant = proprioception._moyennes(notes_avant)
    apres = proprioception._moyennes(notes_apres)
    cible = prop["dimension"]
    gain = round((apres.get(cible) or 0) - (avant.get(cible) or 0), 3)
    regressions = {d: round((apres[d] or 0) - (avant[d] or 0), 3)
                   for d in proprioception._DIMENSIONS
                   if d != cible and (apres[d] or 0) - (avant[d] or 0) <= -SEUIL_REGRESSION}
    recommande = gain >= SEUIL_GAIN and not regressions

    prop["eval"] = {
        "echantillon": len(questions), "avant": avant, "apres": apres,
        "dimension_cible": cible, "gain_cible": gain, "regressions": regressions,
        "recommande": recommande,
        "evalue_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _sauver(data)
    return {"ok": True, "proposition": prop, "eval": prop["eval"]}


# ── Gate humain : valider → appliquer (réversible) ───────────────────────────

def _statut(id_: str, vers: str, depuis: tuple[str, ...]) -> dict:
    """Transition d'état gardée : refuse si la proposition n'est pas dans un état attendu."""
    data = _charger()
    prop = _trouver(data, id_)
    if not prop:
        return {"ok": False, "erreur": "Proposition introuvable."}
    if prop["statut"] not in depuis:
        return {"ok": False, "erreur": f"Transition refusée : statut « {prop['statut']} » "
                f"(attendu : {', '.join(depuis)}).", "statut": prop["statut"]}
    prop["statut"] = vers
    if vers == "applique":
        # Un seul addendum actif : l'ancien actif redevient « remplace ».
        for autre in data["propositions"]:
            if autre["id"] != id_ and autre["statut"] == "applique":
                autre["statut"] = "remplace"
        data["actif_id"] = id_
        prop["applique_le"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if vers == "rejete" and data.get("actif_id") == id_:
        data["actif_id"] = None
    _sauver(data)
    return {"ok": True, "proposition": prop}


def valider(id_: str) -> dict:
    """Gate humain — étape 1 : marque la proposition « validée » (depuis « propose »)."""
    return _statut(id_, "valide", ("propose",))


def appliquer(id_: str) -> dict:
    """Gate humain — étape 2 : ACTIVE l'addendum (refusé si non validé). Réversible."""
    return _statut(id_, "applique", ("valide",))


def rejeter(id_: str) -> dict:
    """Écarte une proposition (depuis n'importe quel état) ; la désactive si elle était active."""
    return _statut(id_, "rejete", ("propose", "valide", "applique", "remplace"))


def desactiver() -> dict:
    """Revient au prompt fondateur : aucun addendum actif (n'efface pas l'historique)."""
    data = _charger()
    ancien = data.get("actif_id")
    data["actif_id"] = None
    for p in data["propositions"]:
        if p["id"] == ancien and p["statut"] == "applique":
            p["statut"] = "remplace"
    _sauver(data)
    return {"ok": True, "actif_id": None}
