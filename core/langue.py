"""Configuration multilingue du Jarvis — réponses & voix (Sprint S39).

Pendant de `briques/generateur/langues.py` (qui régit la langue des APPS livrées),
mais côté Cœur : ici on règle la langue dans laquelle le **Jarvis** s'exprime — chat
(`assistant.py`), briefing du matin (`briefing.py`), résumé du document (`classer.py`),
condensation d'historique (`summarisation.py`) — et celle de la **voix** (reconnaissance
+ synthèse dans le navigateur, `core/main.py`).

Différence de portée, assumée :
- une app livrée = une langue **fixée à la livraison** (langue de l'entreprise cliente) ;
- le Jarvis = une **préférence de l'utilisateur** (réglage ⚙ Cerveau), persistée dans
  `config_assistant` exactement comme la persona ou le modèle, lue à chaud à chaque tour.

Le français reste le **défaut** ET le **repli** : toute langue inconnue retombe sur `fr`.
L'arabe (`ar`, RTL) arrivera en S44 (sous-chantier dédié au sens droite-à-gauche).
"""

LANGUE_DEFAUT = "fr"

# code ISO 639-1 → nom pour INSTRUIRE le LLM (rédigé en français, comme le reste des
# prompts du Cœur). 'ar' arrivera en S44.
_NOMS = {
    "fr": "français",
    "en": "anglais (English)",
    "es": "espagnol (Español)",
}

# code → libellé NATIF pour le sélecteur du front (ce que l'utilisateur reconnaît).
_LABELS = {
    "fr": "Français",
    "en": "English",
    "es": "Español",
}

# code → locale BCP-47 pour la Web Speech API du navigateur (reco.lang / utt.lang
# + choix de la voix de synthèse). On vise une variante répandue par langue.
_LOCALES_VOIX = {
    "fr": "fr-FR",
    "en": "en-US",
    "es": "es-ES",
}


def normaliser(langue) -> str:
    """Ramène une entrée libre à un code supporté ; repli `fr` si inconnu/vide."""
    code = (str(langue or "").strip().lower())[:2]
    return code if code in _NOMS else LANGUE_DEFAUT


def nom(langue) -> str:
    """Nom de la langue pour instruire le LLM (ex. « anglais (English) »)."""
    return _NOMS[normaliser(langue)]


def consigne_reponse(langue) -> str:
    """Directive de langue à AJOUTER au prompt système du Jarvis.

    Le Jarvis répond TOUJOURS dans la langue choisie — y compris si l'utilisateur
    écrit dans une autre langue (c'est une préférence de compte, pas une détection
    au coup par coup). Remplace l'ancien « Réponds toujours en français » codé en dur.
    """
    return (f"Réponds toujours en {_NOMS[normaliser(langue)]}, de façon concise et "
            f"concrète, quelle que soit la langue du message de l'utilisateur.")


def consigne_resume(langue) -> str:
    """Fragment « en {langue} » pour les prompts de synthèse (briefing, résumé,
    condensation) où la langue est inscrite au fil de la phrase."""
    return f"en {_NOMS[normaliser(langue)]}"


def locale_voix(langue) -> str:
    """Locale BCP-47 pour la reconnaissance et la synthèse vocale du navigateur."""
    return _LOCALES_VOIX[normaliser(langue)]


def catalogue() -> list[dict]:
    """Liste publique pour peupler le sélecteur de langue du front.

    Renvoie aussi la locale voix : le front règle `reco.lang`/`utt.lang` sans
    redemander au serveur."""
    return [{"code": c, "label": _LABELS[c], "locale_voix": _LOCALES_VOIX[c]}
            for c in _NOMS]
