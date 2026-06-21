"""Flux BMAD léger (S88) : PLANIFIER avant de coder. L'agent « Architect » d'abord.

On reprend 3 idées de BMAD sans installer BMAD : (1) un agent spécialisé par phase — ici le
rôle « Architect » qui ne code pas, il conçoit ; (2) le **plan AVANT le code** ; (3) une
**story qui porte le contexte** (le plan validé est ensuite injecté à l'agent codeur).

Le plan a trois sections imposées, dans cet ordre — le DOMAINE d'abord, le DDD avant la
technique :
  • **Mini-PRD** — quoi/pourquoi, critère de succès ;
  • **Stories** — découpage en petites tranches livrables ;
  • **Domaine (DDD)** — entités/agrégats, langage métier, ce qui doit vivre dans un `domaine.py`
    pur (sans I/O) avant toute logique technique.

On délègue la rédaction à la Gateway LLM (modèle gratuit par défaut, cost-first), comme
`mail/resume.py`. Repli **HONNÊTE** : sans LLM joignable, on rend un squelette de plan local —
clairement étiqueté « local » — qui structure le travail sans rien inventer de spécifique.
"""
from __future__ import annotations

import os
import re

import httpx

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://host.docker.internal:4001")
GATEWAY_KEY = os.getenv("GATEWAY_KEY", "")
GATEWAY_MODEL = os.getenv("GATEWAY_MODEL", "free/google/gemma-4-31b-it")

_LANGUES = {"fr": "français", "en": "anglais", "es": "espagnol"}

# En-têtes EXACTS attendus dans le plan — sert au parsing ET au gabarit local.
H_PRD, H_STORIES, H_DOMAINE = "## Mini-PRD", "## Stories", "## Domaine (DDD)"

PROMPT_ARCHITECT = (
    "Tu es l'« Architect » d'un atelier de développement souverain (méthode BMAD allégée). "
    "Tu ne codes PAS : tu produis un PLAN court et actionnable AVANT que l'agent codeur ne "
    "touche au code. Le projet « Workplace » est fait d'un noyau + de briques indépendantes ; "
    "chaque brique respecte le Domain-Driven Design (un `domaine.py` PUR sans I/O, langage "
    "métier). Rends EXACTEMENT trois sections markdown, dans cet ordre et avec ces titres :\n"
    f"{H_PRD}\n(2-4 phrases : le quoi, le pourquoi, le critère de succès)\n"
    f"{H_STORIES}\n(3 à 6 puces « - », chacune une tranche livrable et testable)\n"
    f"{H_DOMAINE}\n(les entités/agrégats et le langage métier à modéliser dans le domaine pur "
    "AVANT la logique technique)\n"
    "Reste FIDÈLE à l'intention, n'invente pas d'exigences hors sujet. Écris en {langue}, "
    "sobre et concret. Rends UNIQUEMENT le markdown des trois sections."
)


def _section(texte: str, entete: str, suivantes: list[str]) -> str:
    """Extrait le corps d'une section markdown `entete` jusqu'à la prochaine `## …`."""
    if entete not in texte:
        return ""
    debut = texte.index(entete) + len(entete)
    fin = len(texte)
    for autre in suivantes:
        i = texte.find(autre, debut)
        if i != -1:
            fin = min(fin, i)
    return texte[debut:fin].strip()


def _stories(bloc: str) -> list[str]:
    """Transforme un bloc de puces markdown en liste de stories propres."""
    out = []
    for ligne in bloc.splitlines():
        m = re.match(r"\s*[-*]\s+(.*\S)", ligne)
        if m:
            out.append(m.group(1).strip())
    return out


def _structurer(texte: str, genere_par: str, note: str = "") -> dict:
    """Découpe un plan markdown en {prd, stories[], domaine, texte, genere_par, note}."""
    prd = _section(texte, H_PRD, [H_STORIES, H_DOMAINE])
    stories = _stories(_section(texte, H_STORIES, [H_DOMAINE]))
    dom = _section(texte, H_DOMAINE, [])
    return {"genere_par": genere_par, "prd": prd, "stories": stories,
            "domaine": dom, "texte": texte.strip(), "note": note}


def plan_local(intention: str, brique_cible: str = "", lang: str = "fr") -> dict:
    """Squelette de plan HONNÊTE, sans LLM : structure le travail sans inventer de spécifique."""
    cible = brique_cible or "(brique à préciser)"
    texte = (
        f"{H_PRD}\n"
        f"Intention : {intention}. Brique cible : {cible}. Objectif : livrer cet incrément "
        f"sans casser la prod (filet git, fusion sous gate). Succès = le diff répond à "
        f"l'intention, tests hors-ligne verts, doc à jour.\n\n"
        f"{H_STORIES}\n"
        f"- Modéliser le domaine pur impacté (entités/agrégats, langage métier) avant tout code.\n"
        f"- Implémenter « {intention} » dans la brique {cible}.\n"
        f"- Couvrir par des tests hors-ligne et mettre à jour README/manifest.\n\n"
        f"{H_DOMAINE}\n"
        f"Commencer par un `domaine.py` PUR (sans I/O), nommer les concepts en langage métier, "
        f"garder la logique testable hors-ligne. (Plan généré localement : à affiner.)"
    )
    return _structurer(texte, "local",
                       "Plan généré localement (LLM indisponible) : squelette honnête à affiner.")


async def _completer(systeme: str, tache: str) -> str:
    if not GATEWAY_MODEL:
        raise RuntimeError("Aucun modèle LLM configuré (GATEWAY_MODEL).")
    headers = {"Authorization": f"Bearer {GATEWAY_KEY}"} if GATEWAY_KEY else {}
    payload = {"model": GATEWAY_MODEL, "temperature": 0.3,
               "messages": [{"role": "system", "content": systeme},
                            {"role": "user", "content": tache}]}
    async with httpx.AsyncClient(timeout=45) as c:
        r = await c.post(f"{GATEWAY_URL}/v1/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        return (r.json()["choices"][0]["message"]["content"] or "").strip()


async def concevoir(intention: str, brique_cible: str = "", lang: str = "fr") -> dict:
    """Conçoit le plan d'un chantier (Architect). LLM si dispo, sinon squelette local honnête.

    Renvoie toujours un plan STRUCTURÉ (prd + stories + domaine + texte). `genere_par` dit la
    vérité (« ia » / « local »). Si le LLM répond mais sans les 3 sections, on complète avec le
    squelette local pour ne jamais rendre un plan boiteux."""
    local = plan_local(intention, brique_cible, lang)
    langue = _LANGUES.get(lang, "français")
    tache = (f"Intention du chantier : « {intention} ». "
             f"Brique cible : {brique_cible or '(non précisée)'}. "
             f"Produis le plan (les trois sections).")
    try:
        texte = await _completer(PROMPT_ARCHITECT.format(langue=langue), tache)
    except Exception:  # noqa: BLE001 — repli honnête, jamais d'erreur opaque côté client
        return local
    plan = _structurer(texte, "ia")
    # Garde-fou : un plan IA sans ses sections imposées n'est pas exploitable → repli honnête.
    if not (plan["prd"] and plan["stories"] and plan["domaine"]):
        return {**local, "note": "Plan IA incomplet (sections manquantes) : repli sur squelette local."}
    return plan
