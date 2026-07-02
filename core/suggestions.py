"""Actions suggérées — boutons d'action GÉNÉRIQUES pour les surfaces de chat (S76).

Quand l'assistant propose une ACTION, il renvoie aussi des « actions suggérées » : de
petits boutons que l'utilisateur tape au lieu de retaper « oui ». Le tap ne fait
qu'INJECTER un message déjà rédigé dans la conversation — le LLM reprend la main et
rappelle l'outil avec `confirme=true`. Aucun court-circuit du gate humain, aucune action
exécutée sans repasser par le modèle : un bouton = un raccourci de frappe, rien de plus.

Mécanisme GÉNÉRIQUE et surface-agnostique (dashboard web, Mini App Telegram, plus tard le
pont natif) : TOUTE confirmation en produit, et on peut enrichir par outil au besoin sans
toucher aux surfaces. Chaque action = {"label": ..., "envoi": ...} — `label` s'affiche
sur le bouton, `envoi` est le message soumis quand on tape.
"""

CONFIRMER = {"label": "✅ Confirmer", "envoi": "Oui, confirme."}
ANNULER = {"label": "✖ Annuler", "envoi": "Non, annule, merci."}

# Boutons contextuels pour le workflow améliorer (S132)
_DEV_VALIDER_CHANTIER = {"label": "✅ Valider & lancer le chantier", "envoi": "Oui, confirme."}
_DEV_VALIDER_PLAN = {"label": "✅ Valider le plan & coder", "envoi": "Oui, confirme."}
_DEV_ANNULER = {"label": "❌ Annuler le chantier", "envoi": "Non, annule, merci."}
_DEV_VOIR_DIFF = {"label": "👀 Voir le diff", "envoi": "montre-moi le diff"}
_DEV_FUSIONNER = {"label": "🚀 Fusionner en prod", "envoi": "fusionne sur git et redémarre sur le HP"}
_DEV_JETER = {"label": "❌ Jeter le chantier", "envoi": "annule le chantier dev"}
_DEV_VOIR_DIFF_AVANT = {"label": "👀 Voir le diff d'abord", "envoi": "montre-moi le diff"}


def pour_resultat(nom: str, args: dict, resultat: str, *, confirmation: bool) -> list[dict]:
    """Actions suggérées à présenter APRÈS le résultat d'un outil.

    `nom`/`args` : l'outil appelé et ses arguments ; `resultat` : la chaîne renvoyée par
    l'outil ; `confirmation` : un gate est-il en attente ?
    Défaut générique : une confirmation en attente → boutons Confirmer / Annuler.
    Tout autre cas → aucun bouton."""
    # Workflow améliorer (S132) : boutons contextuels par outil dev_*
    if nom == "dev_demander" and confirmation:
        return [_DEV_VALIDER_CHANTIER, _DEV_ANNULER]
    if nom == "dev_plan_valider" and confirmation:
        return [_DEV_VALIDER_PLAN, _DEV_ANNULER]
    if nom == "dev_lancer" and not confirmation:
        return [_DEV_FUSIONNER, _DEV_VOIR_DIFF, _DEV_JETER]
    if nom == "dev_fusionner" and confirmation:
        return [_DEV_FUSIONNER, _DEV_VOIR_DIFF_AVANT, _DEV_ANNULER]
    # Générique : gate en attente → Confirmer / Annuler
    if confirmation:
        return [CONFIRMER, ANNULER]
    return []
