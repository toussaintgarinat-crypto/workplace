"""Proprioception (S68) — le Cœur mesure ses propres sorties.

Les sprints précédents ont donné au corps des organes (S63-65), un lobe frontal (S66) et
un pouls (S67). S68 lui donne le SENS DE LUI-MÊME : il échantillonne ses propres réponses,
les fait noter par un juge LLM (l'économe gratuit → coût ~0, S138), et en tire un rapport
de qualité par flux. Ce rapport est la matière première de l'auto-amélioration à venir :
S69 (prompts) et S70 (capacités) agiront sur ce que la proprioception aura repéré.

Deux motifs réutilisés du reste de `core/` :
  • la CAPTURE en journal jsonl side-car, échantillonnée et opt-in (calque `shadow.py`) —
    par défaut ÉTEINTE (aucune surprise, aucun coût, rien d'enregistré) ;
  • PROPOSER ≠ valider ≠ appliquer (calque `revue.py`/S31-34) : ce module ne fait que
    MESURER et SUGGÉRER des cibles d'amélioration ; il ne touche ni aux prompts ni au code.

Honnêteté : sans juge LLM joignable, on retombe sur des PROXIES STRUCTURELS clairement
étiquetés `source: heuristique` — jamais un faux jugement de qualité présenté comme vrai.
"""
import asyncio
import json
import logging
import os
import random
import threading
import time
from pathlib import Path

import httpx

import config_assistant
import langue as langue_mod
import llm_pipeline

logger = logging.getLogger(__name__)

TRACE_PATH = Path(os.getenv("PROPRIOCEPTION_PATH", "/data/proprioception.jsonl"))
ACTIF = os.getenv("PROPRIOCEPTION_ACTIF", "0").lower() not in ("0", "false", "no", "")
TAUX_DEFAUT = float(os.getenv("PROPRIOCEPTION_TAUX", "0.15"))
SEUIL_FAIBLE = float(os.getenv("PROPRIOCEPTION_SEUIL", "0.6"))   # < seuil = point faible
_DIMENSIONS = ("pertinence", "honnetete", "completude")
_verrou = threading.Lock()


# ── Capture (échantillonnée, opt-in, fire-and-forget) ────────────────────────

def echantillonne(conf: dict | None = None) -> bool:
    """True si la proprioception est active ET que ce tirage tombe dans l'échantillon.

    Active par env `PROPRIOCEPTION_ACTIF` ou par la config assistant (réglable au front)."""
    actif = ACTIF or bool((conf or {}).get("proprioception_actif"))
    if not actif:
        return False
    brut = (conf or {}).get("proprioception_taux")   # 0 explicite = désactivé (cf. shadow.py)
    taux = float(TAUX_DEFAUT if brut is None else brut)
    return random.random() < max(0.0, min(1.0, taux))


def tracer(question: str, reponse: str, *, etiquette: str = "chat",
           modele: str | None = None, outils: list | None = None) -> None:
    """Enregistre un échange (question/réponse) pour évaluation ultérieure. Ne lève jamais.

    Volontairement minimal : dernier message utilisateur + réponse finale + métadonnées —
    pas tout l'historique (taille + sobriété). Écriture locale, sous le volume du Cœur."""
    ligne = {
        "ts": time.time(),
        "etiquette": etiquette,
        "question": (question or "")[:2000],
        "reponse": (reponse or "")[:4000],
        "modele": modele,
        "outils": list(outils or []),
    }
    try:
        with _verrou:
            TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with TRACE_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning("Proprioception non écrite : %s", e)


def _lignes(limite: int | None = None) -> list[dict]:
    """Lit les échanges tracés (tolérant). `limite` = ne garder que les N plus récents."""
    if not TRACE_PATH.exists():
        return []
    out: list[dict] = []
    try:
        with TRACE_PATH.open(encoding="utf-8") as f:
            for brute in f:
                brute = brute.strip()
                if brute:
                    try:
                        out.append(json.loads(brute))
                    except json.JSONDecodeError:
                        continue
    except OSError as e:
        logger.warning("Proprioception illisible : %s", e)
        return []
    return out[-limite:] if limite else out


# ── Évaluation : juge LLM gratuit, repli heuristique honnête ──────────────────

def prompt_juge(langue=None) -> str:
    return (
        "Tu es un évaluateur QUALITÉ impartial des réponses d'un assistant. On te donne une "
        "QUESTION d'utilisateur et la RÉPONSE de l'assistant. Note la réponse de 0.0 à 1.0 sur "
        "TROIS axes, puis renvoie UNIQUEMENT un objet JSON :\n"
        '{"pertinence": <0-1>, "honnetete": <0-1>, "completude": <0-1>, "commentaire": "<court>"}\n'
        "- pertinence : répond-elle vraiment à la question ?\n"
        "- honnetete : évite-t-elle d'inventer (confabuler) ? assume-t-elle ce qu'elle ignore ?\n"
        "- completude : est-elle suffisante sans être bavarde ?\n"
        f"{langue_mod.consigne_resume(langue)} pour le commentaire. N'ajoute aucun texte hors du JSON."
    )


def _borne(x) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def _heuristique(ligne: dict) -> dict:
    """Proxy STRUCTUREL (pas un vrai jugement) quand aucun juge LLM n'est joignable.

    On ne prétend pas mesurer la qualité : on déduit des signaux grossiers (réponse vide,
    aveu d'incertitude) et on l'étiquette clairement pour ne tromper personne."""
    rep = (ligne.get("reponse") or "").strip()
    aveu = any(t in rep.lower() for t in
               ("je ne sais", "je ne peux", "indisponible", "pas certain", "je n'ai pas"))
    return {
        "pertinence": 0.7 if rep else 0.0,
        "honnetete": 0.9 if aveu else (0.7 if rep else 0.0),
        "completude": round(min(1.0, len(rep) / 200), 2),
        "commentaire": "proxy structurel (aucun juge LLM)",
        "_juge": False,
    }


async def _juger(client, ligne: dict, conf: dict) -> dict:
    """Note un échange via le juge LLM gratuit. Repli heuristique si Gateway/JSON KO."""
    modeles = await config_assistant.chaine_modeles(conf)
    if not modeles:
        return _heuristique(ligne)
    messages = [
        {"role": "system", "content": prompt_juge(conf.get("langue"))},
        {"role": "user", "content": "QUESTION :\n" + (ligne.get("question") or "")
         + "\n\nRÉPONSE :\n" + (ligne.get("reponse") or "")},
    ]
    res = await llm_pipeline.completer(
        messages, modeles=modeles, tools=None, temperature=0.0, max_tokens=200,
        response_format={"type": "json_object"}, etiquette="proprioception",
        conf=conf, trim_contexte=False, client=client)
    if not res.ok:
        return _heuristique(ligne)
    try:
        d = json.loads(res.message.get("content") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _heuristique(ligne)
    return {
        "pertinence": _borne(d.get("pertinence")),
        "honnetete": _borne(d.get("honnetete")),
        "completude": _borne(d.get("completude")),
        "commentaire": str(d.get("commentaire", ""))[:300],
        "_juge": True,
    }


# ── Agrégat + propositions (proposer ≠ valider ≠ appliquer) ──────────────────

def _moyennes(notes: list[dict]) -> dict:
    if not notes:
        return {d: None for d in _DIMENSIONS}
    return {d: round(sum(n[d] for n in notes) / len(notes), 3) for d in _DIMENSIONS}


def _propositions(par_flux: dict) -> list[dict]:
    """Cibles d'amélioration SUGGÉRÉES (jamais appliquées) à partir des points faibles.

    Une dimension faible mène à une cible : honnêteté/pertinence → prompt (S69) ;
    complétude faible récurrente → prompt OU capacité manquante (S70 à trancher)."""
    props = []
    for flux, agg in par_flux.items():
        for dim, val in agg["moyennes"].items():
            if val is not None and val < SEUIL_FAIBLE:
                cible = "capacites" if dim == "completude" else "prompts"
                props.append({
                    "flux": flux,
                    "dimension": dim,
                    "score": val,
                    "cible_sprint": "S70" if cible == "capacites" else "S69",
                    "suggestion": f"Flux « {flux} » faible en {dim} ({val}) sur "
                                  f"{agg['echantillons']} échantillon(s) — "
                                  f"revoir le {'prompt système' if cible == 'prompts' else 'jeu de capacités'}.",
                })
    props.sort(key=lambda p: p["score"])
    return props


async def mesurer(*, limite: int = 15, conf: dict | None = None) -> dict:
    """Évalue les derniers échanges tracés et rend un RAPPORT de proprioception.

    Note chaque échange (juge LLM gratuit, repli heuristique), agrège par flux (étiquette),
    repère les points faibles (< seuil) et PROPOSE des cibles d'amélioration. Ne modifie
    rien : c'est l'étape « proposer » qui nourrira S69/S70 (sous gate humain)."""
    conf = conf or config_assistant.charger()
    lignes = _lignes(limite)
    if not lignes:
        return {"n": 0, "source": "aucune", "moyennes": _moyennes([]),
                "par_flux": {}, "points_faibles": [], "propositions": [],
                "note": "Aucun échange tracé. Active la proprioception (opt-in, échantillonnée) "
                        "pour que le Cœur commence à se mesurer."}

    notes_par_flux: dict[str, list] = {}
    toutes: list[dict] = []
    via_juge = 0
    async with httpx.AsyncClient(timeout=60) as client:
        for ligne in lignes:
            note = await _juger(client, ligne, conf)
            via_juge += 1 if note.get("_juge") else 0
            toutes.append(note)
            notes_par_flux.setdefault(ligne.get("etiquette") or "chat", []).append(note)

    par_flux = {flux: {"echantillons": len(ns), "moyennes": _moyennes(ns)}
                for flux, ns in notes_par_flux.items()}
    propositions = _propositions(par_flux)
    moyennes = _moyennes(toutes)
    points_faibles = [d for d, v in moyennes.items() if v is not None and v < SEUIL_FAIBLE]
    return {
        "n": len(toutes),
        "source": "juge" if via_juge else "heuristique",
        "evalues_par_juge": via_juge,
        "moyennes": moyennes,
        "par_flux": par_flux,
        "points_faibles": points_faibles,
        "propositions": propositions,
        "note": "Proprioception = MESURE + PROPOSITION. Rien n'est modifié ici ; les cibles "
                "sont à valider par l'humain (S69 prompts, S70 capacités).",
    }
