"""Cahier des charges (S229) — assemble un document markdown à partir d'un audit complet.

La section ROI est un littéral CODE, jamais généré par le LLM (même logique que
`briques/audit/chiffrage.py`) — le LLM ne produit QUE les 12 sections qualitatives.
"""
import logging

from gateway import appeler_llm
from prompts import prompt_cahier_des_charges, _SECTIONS_CDC

logger = logging.getLogger(__name__)

AVERTISSEMENT = "Estimation à valider avec le client — non contractuelle."


def _section_roi_markdown(roi: dict | None) -> str:
    if not roi or not isinstance(roi.get("problemes"), list) or not roi["problemes"]:
        return "_Chiffrage non disponible — relancer `POST /audits/{id}/chiffrer`._"
    lignes = [roi.get("synthese", "")]
    for p in roi["problemes"]:
        cout = p.get("cout_actuel_estime") or {}
        gain = p.get("gain_potentiel_estime") or {}
        lignes.append(
            f"- **{p.get('probleme', '—')}** ({p.get('pole', '—')}) — "
            f"coût actuel estimé {cout.get('bas', '?')}–{cout.get('haut', '?')} €/mois, "
            f"gain potentiel {gain.get('bas', '?')}–{gain.get('haut', '?')} €/mois "
            f"[{p.get('statut', 'hypothese_llm')}]. {p.get('avertissement', AVERTISSEMENT)}"
        )
    return "\n\n".join(lignes)


async def generer_cahier_des_charges(audit: dict, langue: str = "fr") -> str:
    """Retourne le markdown complet (12 sections LLM + section ROI déterministe)."""
    prompt = prompt_cahier_des_charges(audit, langue)
    sections: dict = {}
    for tentative in range(2):
        try:
            sections = await appeler_llm(prompt, langue)
            break
        except Exception as e:
            logger.warning(f"Cahier des charges tentative {tentative + 1} échouée : {e}")

    corps = "\n\n".join(
        f"## {titre}\n\n{sections.get(cle) or '_Non disponible._'}"
        for cle, titre in _SECTIONS_CDC
    )
    roi_md = f"## ROI\n\n{_section_roi_markdown(audit.get('roi'))}"
    return f"{corps}\n\n{roi_md}"


def construire_diapositives(audit: dict) -> list[dict]:
    """5-8 diapositives 'points clés' à partir de l'audit déjà chiffré — AUCUN appel LLM
    supplémentaire (réutilise problemes/priorites/roi déjà en base, coût marginal nul)."""
    nom = audit.get("nom_entreprise") or "Entreprise"
    problemes = audit.get("problemes") or {}
    priorites = audit.get("priorites") or {}
    roi = audit.get("roi") or {}
    pareto = (problemes.get("pareto") or [])[:5]
    must = ((priorites.get("moscow") or {}).get("must") or [])[:5]
    chemin_critique = (priorites.get("chemin_critique") or [])[:5]

    return [
        {"titre": nom, "points": ["Cahier des charges — points clés"]},
        {"titre": "Problèmes majeurs",
         "points": [p.get("probleme", "—") for p in pareto] or ["Aucun problème majeur identifié."]},
        {"titre": "ROI estimé",
         "points": [roi.get("synthese")] if roi.get("synthese")
                   else ["Chiffrage non disponible — relancer POST /audits/{id}/chiffrer."],
         "notes": AVERTISSEMENT},
        {"titre": "Solution proposée", "points": must or ["À définir."]},
        {"titre": "Priorités",
         "points": [f"{t.get('id', '?')} — {t.get('duree_jours', '?')}j" for t in chemin_critique]
                   or ["Aucune priorité chiffrée."]},
    ]
