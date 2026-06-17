"""Adaptateur LLM provider-agnostique pour la proposition de distribution.

Deux modes (au choix, par appel ou par défaut) :
  • Gateway Workplace par défaut (cost-first : modèles gratuits servis par la Gateway) ;
  • Bring-Your-Own-Key : le client passe {base_url, cle, modele} → on tape SON endpoint
    OpenAI-compatible. Aucun coût porté par la brique.

Tout est OpenAI-compatible (`/chat/completions`). Le « Directeur de Casting » n'est
qu'un prompt système : c'est la couche métier (structure + cohérence) qui a de la valeur,
pas le prompt lui-même.
"""
from __future__ import annotations

import json
import os
import re

import httpx

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://host.docker.internal:4001")
GATEWAY_KEY = os.getenv("GATEWAY_KEY", "")
GATEWAY_MODEL = os.getenv("GATEWAY_MODEL", "free/google/gemma-4-31b-it")

PROMPT_CASTING = (
    "Tu es DIRECTEUR DE CASTING. À partir d'une prémisse / bible d'histoire, tu conçois "
    "une distribution de personnages COHÉRENTE et complémentaire (protagoniste, allié, "
    "antagoniste, second rôle…). Chaque personnage a un nom, un rôle et une courte "
    "description (physique, caractère, façon de parler). Tu ne rédiges pas de dialogues."
)


def _config(llm: dict | None) -> tuple[str, str, str]:
    """(base_url, cle, modele) : BYO si fourni et complet, sinon Gateway par défaut."""
    llm = llm or {}
    base = (llm.get("base_url") or "").strip()
    if base:   # mode BYO
        return base.rstrip("/"), (llm.get("cle") or "").strip(), (llm.get("modele") or "").strip()
    return f"{GATEWAY_URL}/v1", GATEWAY_KEY, (llm.get("modele") or GATEWAY_MODEL)


def _extraire_json(txt: str):
    """Récupère un tableau JSON même entouré de prose / fences markdown."""
    txt = re.sub(r"```(json)?", "", txt or "")
    m = re.search(r"\[.*\]", txt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _extraire_objet(txt: str):
    """Récupère un objet JSON {…} même entouré de prose / fences markdown."""
    txt = re.sub(r"```(json)?", "", txt or "")
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


async def _completer(systeme: str, tache: str, llm: dict | None) -> str:
    base, cle, modele = _config(llm)
    if not modele:
        raise RuntimeError("Aucun modèle LLM configuré (ni BYO, ni Gateway).")
    headers = {"Authorization": f"Bearer {cle}"} if cle else {}
    payload = {"model": modele, "temperature": 0.4,
               "messages": [{"role": "system", "content": systeme},
                            {"role": "user", "content": tache}]}
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{base}/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""


PROMPT_TRAITS = (
    "Tu es un analyste de personnalité. On te donne la description libre d'un caractère. "
    "Tu dois la traduire en notes sur des AXES psychologiques fixes (pas d'autres axes). "
    "Note de 0 à 3 SEULEMENT les axes réellement évoqués (0 = absent, 3 = très marqué)."
)


async def cibler_via_llm(description: str, axes: list, llm: dict | None = None) -> dict:
    """Filet de secours du mode montant : traduit une description en {axe: poids 0-3}.

    N'est appelé QUE si le lexique local n'a rien reconnu. Modèle gratuit par défaut
    (Gateway cost-first) ou endpoint BYO/local. Repli HONNÊTE : {} si réponse illisible —
    l'appelant retombe alors sur « aucun trait reconnu », il n'invente rien."""
    liste = ", ".join(axes)
    tache = (
        f"Axes autorisés (utilise EXACTEMENT ces noms) : {liste}.\n"
        f"Description du personnage :\n{description}\n\n"
        'Réponds UNIQUEMENT par un objet JSON {"Axe": entier_0_a_3, ...}, '
        "uniquement les axes pertinents, sans texte autour."
    )
    brut = await _completer(PROMPT_TRAITS, tache, llm)
    obj = _extraire_objet(brut) or {}
    permis = {a.lower(): a for a in axes}          # tolère casse/accents proches
    out: dict = {}
    for cle, val in obj.items():
        axe = permis.get(str(cle).strip().lower())
        if not axe:
            continue
        try:
            n = int(val)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out[axe] = max(0, min(n, 3))
    return out


PROMPT_LECTURE = (
    "Tu es un INTERPRÈTE SYMBOLIQUE. On te donne le profil DÉJÀ CALCULÉ d'une personne : "
    "un archétype, des forces, un point faible avec sa pierre d'équilibrage, et une empreinte "
    "multi-traditions (chaque élément vient avec son sens). Tu rédiges une lecture symbolique "
    "fluide et évocatrice qui TISSE ces éléments entre eux et dégage un fil conducteur. "
    "Règles STRICTES : n'invente AUCUN fait absent des données ; pas de prédiction, pas de "
    "conseil médical/financier ; ton sobre et bienveillant. C'est du divertissement."
)


async def approfondir_lecture(portrait: dict, empreinte: list,
                              langue: str = "français", llm: dict | None = None) -> str:
    """Réécrit la lecture symbolique en version littéraire, à partir des SEULES données
    calculées. Bonus opt-in (modèle gratuit Gateway par défaut, ou BYO). Repli HONNÊTE :
    l'appelant retombe sur le récit déterministe si l'on renvoie une chaîne vide / si on lève."""
    lignes = [f"- {e.get('cle')} : {e.get('valeur')} → {e.get('sens')}"
              for e in (empreinte or []) if e.get("sens")]
    pierre = portrait.get("pierre_equilibrage") or {}
    tache = (
        f"Rédige en {langue}, 4 à 6 courts paragraphes, sans liste à puces.\n"
        f"Archétype : {portrait.get('archetype','')}\n"
        f"Forces dominantes : {', '.join(portrait.get('forces', []))}\n"
        f"Point à travailler : {portrait.get('faiblesse','')} "
        f"(pierre d'équilibrage : {pierre.get('pierre','')} — {pierre.get('vertu','')})\n"
        f"Empreinte multi-traditions (valeur → sens) :\n" + "\n".join(lignes) +
        "\n\nTisse ces éléments en une lecture cohérente avec un fil conducteur. "
        "N'invente aucun fait. Termine sans formule de politesse."
    )
    txt = await _completer(PROMPT_LECTURE, tache, llm)
    return (txt or "").strip()


async def proposer_distribution(premisse: str, langue: str = "français",
                                combien: int = 4, deja: str = "",
                                llm: dict | None = None) -> list:
    """Propose `combien` personnages structurés. Repli HONNÊTE : si le JSON est
    illisible, on renvoie [] (l'appelant sait que la proposition a échoué)."""
    combien = max(2, min(int(combien or 4), 8))
    bloc_deja = f"\nDistribution déjà retenue (ne la répète pas) :\n{deja}\n" if deja else ""
    tache = (
        f"Rédige en {langue}. Prémisse de l'histoire :\n{premisse or '(libre)'}\n"
        f"{bloc_deja}\nPropose {combien} personnages cohérents et complémentaires.\n\n"
        'Réponds UNIQUEMENT par un tableau JSON '
        '[{"nom":"...","role":"...","description":"..."}], sans aucun texte autour.'
    )
    brut = await _completer(PROMPT_CASTING, tache, llm)
    options = _extraire_json(brut) or []
    return [
        {"nom": str(o.get("nom") or "").strip(),
         "role": str(o.get("role") or "").strip(),
         "description": str(o.get("description") or "").strip()}
        for o in options if isinstance(o, dict) and (o.get("nom") or "").strip()
    ]
