"""Actions suggérées — boutons d'action GÉNÉRIQUES pour les surfaces de chat (S76).

Quand l'assistant propose une ACTION, il renvoie aussi des « actions suggérées » : de
petits boutons que l'utilisateur tape au lieu de retaper « oui ». Le tap ne fait
qu'INJECTER un message déjà rédigé dans la conversation — le LLM reprend la main et
rappelle l'outil avec `confirme=true`. Aucun court-circuit du gate humain, aucune action
exécutée sans repasser par le modèle : un bouton = un raccourci de frappe, rien de plus.

Mécanisme GÉNÉRIQUE et surface-agnostique (dashboard web, Mini App Telegram, plus tard le
pont natif) : TOUTE confirmation en produit, et on peut enrichir par outil au besoin sans
toucher aux surfaces. Chaque action = ``{"label": ..., "envoi": ...}`` — `label` s'affiche
sur le bouton, `envoi` est le message soumis quand on tape.
"""

CONFIRMER = {"label": "✅ Confirmer", "envoi": "Oui, confirme."}
ANNULER = {"label": "✖ Annuler", "envoi": "Non, annule, merci."}


def pour_resultat(nom: str, args: dict, resultat: str, *, confirmation: bool) -> list[dict]:
    """Actions suggérées à présenter APRÈS le résultat d'un outil.

    `nom`/`args` : l'outil appelé et ses arguments (pour de futures suggestions ciblées) ;
    `resultat` : la chaîne renvoyée par l'outil ; `confirmation` : un gate est-il en attente ?
    Défaut générique : une confirmation en attente → boutons Confirmer / Annuler. Tout autre
    cas → aucun bouton (on n'invente pas d'action que l'utilisateur n'a pas demandée)."""
    if confirmation:
        return [CONFIRMER, ANNULER]
    return []
