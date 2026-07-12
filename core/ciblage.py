"""Ciblage de l'assistant (S165) — « pose-le où il doit travailler ».

L'utilisateur saisit le jeton assistant du dashboard et le dépose sur une tuile,
un onglet ou une carte de brique : le front envoie alors `cible` (le nom de la
brique) avec chaque message du tour. Ce module fabrique le CONTEXTE volatile
correspondant — ce que fait la brique et ses capacités appelables — injecté dans
l'amorce à côté des instructions de projet (zone volatile S90a, après le préfixe
stable mis en cache).

Le ciblage donne du CONTEXTE, jamais un pouvoir : les gates de confirmation des
actions restent strictement inchangés. Honnêteté : une brique inconnue du registre
n'est pas inventée — on le dit à l'assistant tel quel.
"""
import logging

import catalogue

logger = logging.getLogger(__name__)

# Les capacités listées dans le contexte sont plafonnées : une brique très riche
# (ex. Forge, 15 capacités) ne doit pas gonfler la zone volatile (coût LLM, S138).
MAX_CAPACITES = 12


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
