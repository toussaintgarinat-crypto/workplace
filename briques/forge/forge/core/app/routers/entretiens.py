"""Router entretiens (S228) — entretien guidé IA, greffé sur Forge à côté de Ventures.

Squelette de sections FIXE (garde-fou) : deux familles jamais mélangées dans le
traitement d'une réponse.
- « qualitatif » : les 9 catégories du profil_entreprise (S227) — extraction LLM
  ciblée, patch direct (fusion non destructive, jamais d'écrasement).
- « processus » : les 4 zones de la vision (Commercial/Production/Administratif/
  Communication) — accumulées en transcript brut, analysées par briques/audit
  (aucune écriture incrémentale là-bas, décision actée S228).

Dans chaque section, le LLM décide de la relance (réponse courte → question de
suivi ciblée) ; il ne quitte une section que si elle est jugée suffisamment
couverte. Pause/reprise obligatoire : l'état est persisté à chaque tour.
"""

from __future__ import annotations

SECTIONS: list[dict] = [
    {"id": "qualitatif.organisation", "famille": "qualitatif", "categorie": "organisation",
     "premiere_question": "Comment votre entreprise est-elle organisée (statut juridique, effectif, structure) ?"},
    {"id": "qualitatif.activites", "famille": "qualitatif", "categorie": "activites",
     "premiere_question": "Quelles sont vos activités principales ?"},
    {"id": "qualitatif.clients", "famille": "qualitatif", "categorie": "clients",
     "premiere_question": "Qui sont vos clients types ?"},
    {"id": "qualitatif.fournisseurs", "famille": "qualitatif", "categorie": "fournisseurs",
     "premiere_question": "Quels sont vos principaux fournisseurs ou partenaires ?"},
    {"id": "qualitatif.outils_utilises", "famille": "qualitatif", "categorie": "outils_utilises",
     "premiere_question": "Quels outils ou logiciels utilisez-vous au quotidien ?"},
    {"id": "qualitatif.personnel", "famille": "qualitatif", "categorie": "personnel",
     "premiere_question": "Parlez-moi de votre équipe : effectif, rôles clés."},
    {"id": "qualitatif.contraintes", "famille": "qualitatif", "categorie": "contraintes",
     "premiere_question": "Quelles contraintes fortes pèsent sur votre activité (réglementaires, saisonnières...) ?"},
    {"id": "qualitatif.objectifs", "famille": "qualitatif", "categorie": "objectifs",
     "premiere_question": "Quels sont vos objectifs pour les 12 prochains mois ?"},
    {"id": "qualitatif.problemes_connus", "famille": "qualitatif", "categorie": "problemes_connus",
     "premiere_question": "Quels problèmes avez-vous déjà identifiés dans votre organisation ?"},
    {"id": "processus.commercial", "famille": "processus", "zone": "commercial",
     "premiere_question": "Comment arrive une demande client, de la prospection jusqu'au devis ?"},
    {"id": "processus.production", "famille": "processus", "zone": "production",
     "premiere_question": "Comment se déroule une intervention, du planning au compte rendu ?"},
    {"id": "processus.administratif", "famille": "processus", "zone": "administratif",
     "premiere_question": "Comment gérez-vous la facturation et les documents administratifs ?"},
    {"id": "processus.communication", "famille": "processus", "zone": "communication",
     "premiere_question": "Quels canaux utilisez-vous pour communiquer (email, téléphone, SMS, réseaux sociaux) ?"},
]

_PAR_ID = {s["id"]: s for s in SECTIONS}


def _section(section_id: str) -> dict | None:
    return _PAR_ID.get(section_id)


def _prochaine_section(couvertes: list[str]) -> dict | None:
    """Première section du squelette pas encore dans `couvertes`, ou None si complet."""
    deja = set(couvertes or ())
    for s in SECTIONS:
        if s["id"] not in deja:
            return s
    return None
