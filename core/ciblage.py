"""Ciblage de l'assistant (S165) — « pose-le où il doit travailler ».

L'utilisateur saisit le jeton assistant du dashboard et le dépose sur une tuile,
un onglet ou une carte de brique : le front envoie alors `cible` (le nom de la
brique) avec chaque message du tour. Ce module fabrique le CONTEXTE volatile
correspondant — ce que fait la brique et ses capacités appelables — injecté dans
l'amorce à côté des instructions de projet (zone volatile S90a, après le préfixe
stable mis en cache).

Phase « yeux » (S165 phase 2) : en plus du manifest, l'utilisateur peut MONTRER la
zone ciblée — le front capture l'écran de la zone (bouton 👁 du chip) et l'envoie en
base64 ; ce module la fait lire par la brique vision 5960 (OCR souverain, POST /lire)
et injecte le texte extrait dans la même zone volatile.

Le ciblage donne du CONTEXTE, jamais un pouvoir : les gates de confirmation des
actions restent strictement inchangés. Honnêteté : une brique inconnue du registre
n'est pas inventée — on le dit à l'assistant tel quel ; de même, une capture que
l'OCR n'a pas pu lire donne une note qui LE DIT, jamais un texte inventé.
"""
import logging
import os

import httpx

import catalogue
import orchestrateur

logger = logging.getLogger(__name__)

# Les capacités listées dans le contexte sont plafonnées : une brique très riche
# (ex. Forge, 15 capacités) ne doit pas gonfler la zone volatile (coût LLM, S138).
MAX_CAPACITES = 12
# Le texte OCR d'une capture est plafonné lui aussi, et pour la même raison : la zone
# volatile est réinjectée à chaque tour du fil.
MAX_TEXTE_CAPTURE = 1500


def contexte_de(brique: str | None, registre) -> str:
    """Texte de ciblage à injecter dans l'amorce, ou '' si pas de cible.

    Brique connue → description du manifest + capacités appelables (nom, description,
    pastille ACTION pour celles qui exigent le gate). Brique inconnue → note honnête,
    l'assistant sait que le ciblage n'a pas abouti au lieu de confabuler."""
    nom = (brique or "").strip()
    if not nom:
        return ""
    manifest = (getattr(registre, "briques", None) or {}).get(nom) if registre else None
    if manifest is None:
        return (f"Ciblage : l'utilisateur t'a déposé sur « {nom} », mais aucune brique "
                "de ce nom n'est connue du registre. Dis-le-lui simplement et propose "
                "`etat_briques` pour lister ce qui existe.")
    lignes = [f"Ciblage : l'utilisateur t'a déposé sur la brique « {nom} » — c'est LÀ "
              "qu'il veut que tu travailles pour ce message. Priorise ses outils, sans "
              "jamais court-circuiter les confirmations d'action."]
    description = (manifest.get("description") or "").strip()
    if description:
        lignes.append(f"Rôle de la brique : {description}")
    caps = [c for c in catalogue.collecter_capacites(registre) if c["brique"] == nom]
    if caps:
        lignes.append("Capacités de la brique :")
        for cap in caps[:MAX_CAPACITES]:
            suffixe = " [ACTION — confirmation requise]" if cap.get("action") else ""
            lignes.append(f"- {cap['nom']} : {cap.get('description') or 'sans description'}{suffixe}")
        if len(caps) > MAX_CAPACITES:
            lignes.append(f"(+{len(caps) - MAX_CAPACITES} autres — voir `mes_capacites`.)")
    return "\n".join(lignes)


def fusionner_instructions(instructions_projet: str | None, cible: str | None,
                           registre) -> str | None:
    """Combine instructions de projet et contexte de ciblage pour `converser`.

    Le routeur n'a qu'une ligne à appeler ; la logique reste ici, testable à sec.
    Renvoie None si ni projet ni cible (comportement d'avant S165 inchangé)."""
    ctx = contexte_de(cible, registre)
    if not ctx:
        return instructions_projet
    if instructions_projet and instructions_projet.strip():
        return instructions_projet.rstrip() + "\n\n" + ctx
    return ctx


# ── Phase « yeux » : la capture de la zone déposée, lue par la brique vision ─────


async def contexte_capture(capture: dict | None, registre) -> str:
    """Texte des « yeux » à injecter dans l'amorce, ou '' sans capture.

    `capture` = {"data": <base64>, "nom_fichier"?} envoyé par le front après le 👁.
    La brique vision (5960) fait l'OCR ; chaque échec (brique absente, injoignable,
    rien lu) donne une note honnête — l'assistant sait qu'il n'a PAS vu la zone."""
    donnees = ((capture or {}).get("data") or "").strip()
    if not donnees:
        return ""
    try:
        base = orchestrateur._brique_base(registre, "vision")
    except RuntimeError:
        return ("Yeux : l'utilisateur a capturé la zone ciblée pour te la montrer, mais "
                "la brique vision (OCR) est absente du registre — tu n'as PAS pu la lire. "
                "Dis-le-lui simplement s'il s'y réfère.")
    cle = os.environ.get("VISION_KEY")  # clé de service X-API-Key (motif muscle.py)
    entetes = {"X-API-Key": cle} if cle else None
    charge = {"contenu_base64": donnees,
              "nom_fichier": (capture or {}).get("nom_fichier") or "capture-zone.png"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{base}/lire", json=charge, headers=entetes)
        doc = r.json() if r.status_code < 400 else None
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Yeux : brique vision injoignable (%s)", e)
        doc = None
    if doc is None:
        return ("Yeux : l'utilisateur a capturé la zone ciblée pour te la montrer, mais "
                "la brique vision (OCR) n'a pas répondu — tu n'as PAS pu la lire. "
                "Dis-le-lui simplement s'il s'y réfère.")
    texte = (doc.get("texte") or "").strip()
    if not texte:
        note = (doc.get("note") or "").strip()
        return ("Yeux : l'utilisateur a capturé la zone ciblée, mais l'OCR n'y a rien lu"
                + (f" ({note})" if note else "")
                + " — tu ne sais donc PAS ce qui s'y affiche. Dis-le-lui simplement.")
    if len(texte) > MAX_TEXTE_CAPTURE:
        texte = texte[:MAX_TEXTE_CAPTURE].rstrip() + " …[tronqué]"
    return ("Yeux : l'utilisateur t'a montré la zone ciblée — voici ce que l'OCR y a lu "
            "(lecture automatique, il peut y avoir des erreurs) :\n" + texte)


async def fusionner_capture(instructions: str | None, capture: dict | None,
                            registre) -> str | None:
    """Ajoute le texte des « yeux » aux instructions volatiles déjà fusionnées.

    Même contrat que `fusionner_instructions` : une ligne côté routeur, la logique
    testable ici. Sans capture, les instructions repassent strictement inchangées."""
    ctx = await contexte_capture(capture, registre)
    if not ctx:
        return instructions
    if instructions and instructions.strip():
        return instructions.rstrip() + "\n\n" + ctx
    return ctx
