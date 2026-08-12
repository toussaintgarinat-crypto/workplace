"""Orchestration de la génération d'app : plan LLM → HTML."""
import json

from gateway import appeler_llm
from gabarit import generer_html
from prompts import prompt_plan_app
from langues import normaliser_langue


_PLAN_FALLBACK = {
    "nom_app": "Dashboard Workplace",
    "sous_titre": "Tableau de bord stratégique",
    "secteur": "Non déterminé",
    "couleur_principale": "#4F46E5",
    "couleur_secondaire": "#7C3AED",
    "resume_executif": "Analyse de l'entreprise réalisée automatiquement par Workplace.",
    "navigation": [],
    "entites": [],
    "glossaire": [],
    "kpis": [],
    "actions_immediates": [],
    "message_introduction": "Bienvenue dans votre tableau de bord.",
}


async def generer_app_complete(audit: dict, app_id: str = "", api_base: str = "",
                               oria: dict | None = None, langue: str = "fr",
                               cahier_des_charges: str | None = None) -> tuple[dict, str]:
    """Retourne (plan, html) à partir d'un audit complet.

    Si `app_id` + `api_base` sont fournis → app en mode hébergé (persistance serveur) ;
    sinon → mode autonome (localStorage). `oria` (optionnel) = config de la messagerie
    interne (espace + salons) à embarquer dans l'app. `langue` = langue de l'app livrée
    (contenu LLM + châssis) ; défaut/repli `fr`. `cahier_des_charges` (S229, optionnel) =
    markdown du CDC déjà généré pour cet audit — remplace l'assemblage informel si présent."""
    langue = normaliser_langue(langue)
    try:
        prompt = prompt_plan_app(audit, langue, cahier_des_charges)
        plan = await appeler_llm(prompt, langue)
    except Exception:
        # Repli heuristique : le LLM est indisponible. Le plan reste en français
        # (on n'a pas de contenu traduit hors LLM), mais le CHÂSSIS suit la langue.
        plan = _PLAN_FALLBACK.copy()
        plan["nom_app"] = f"Dashboard {audit.get('nom_entreprise', 'Entreprise')}"

    html = generer_html(audit, plan, app_id=app_id, api_base=api_base, oria=oria, langue=langue)
    return plan, html
