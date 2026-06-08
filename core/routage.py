"""Routage dynamique par complexité (Sprint S138, chantier 1).

Un agent configuré sur un modèle puissant reçoit parfois « Bonjour, t'as fini ? ».
Inutile de payer Sonnet pour ça. Ce module estime la **complexité** d'une requête
par des **heuristiques locales (coût 0, aucun appel réseau)** et, si elle est
triviale/simple, propose de rétrograder *cette requête précise* vers un modèle
économe — SANS toucher au modèle configuré (qui reste le plafond).

Workplace n'a pas la hiérarchie de presets de workspace/forge : le routeur se
contente donc de **descendre** vers `modele_econome` (un `free/*`/`ollama`) quand
c'est sûr. Garde-fous : jamais de rétrogradation si des outils sont requis (les
`free/*` n'ont pas tous le function-calling), et kill-switch par config.

L'étage 2 du plan (classifieur LLM ultra-léger en cas d'ambiguïté) est laissé en
crochet `# [S138-1b]` : on ne paie pas un classifieur tant que les heuristiques
suffisent à trancher la majorité des cas.
"""

import re

TRIVIAL, SIMPLE, STANDARD, COMPLEXE = "trivial", "simple", "standard", "complexe"

# Rétrogradation autorisée seulement pour ces niveaux (les autres gardent le modèle).
NIVEAUX_RETROGRADABLES = {TRIVIAL, SIMPLE}

_SALUTATIONS = re.compile(
    r"^\s*(bonjour|salut|coucou|hello|hi|merci|ok|oui|non|d'accord|ça va|cool|"
    r"parfait|super|à plus|au revoir|bonne (journée|soirée))\b",
    re.IGNORECASE)
_CODE = re.compile(r"```|</?\w+>|def |class |import |\bSELECT\b|\bFROM\b|[{}\[\]]{2,}")
_QUESTION_COURTE = re.compile(r"^\s*(c'est quoi|quelle?|qui|où|quand|combien)\b", re.IGNORECASE)


def _dernier_message_utilisateur(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            return m["content"]
    return ""


def complexite(messages: list[dict], tools: list[dict] | None = None) -> str:
    """Estime la complexité d'une requête : trivial | simple | standard | complexe.

    Heuristiques (du moins cher au plus coûteux à servir) :
    - présence de code/JSON, ou requête longue → complexe ;
    - plusieurs tours d'historique → au moins standard ;
    - salutation / oui-non / question courte → trivial ;
    - sinon → simple ou standard selon la longueur.
    """
    texte = _dernier_message_utilisateur(messages).strip()
    nb_tours = sum(1 for m in messages if m.get("role") in ("user", "assistant"))

    # Signaux « lourds » : on ne rétrograde jamais.
    if _CODE.search(texte) or len(texte) > 600:
        return COMPLEXE
    if nb_tours >= 6 or len(texte) > 300:
        return STANDARD

    # Signaux « légers ».
    if len(texte) <= 40 and (_SALUTATIONS.search(texte) or texte.endswith("?") and len(texte) <= 25):
        return TRIVIAL
    if _SALUTATIONS.search(texte) or _QUESTION_COURTE.search(texte) or len(texte) <= 80:
        return SIMPLE
    # [S138-1b] cas ambigu : ici, classifieur LLM léger (Groq/free) → label + cache.
    return STANDARD


def router(messages: list[dict], modeles: list[str], conf: dict,
           tools: list[dict] | None = None) -> tuple[list[str], str | None, str]:
    """Renvoie (modeles_effectifs, routed_to, niveau).

    Si le routage est actif, la requête rétrogradable et qu'aucun outil n'est requis,
    on PRÉPOSE le modèle économe en tête (le modèle configuré reste en fallback :
    sécurité si l'économe échoue). Sinon on renvoie la liste inchangée."""
    niveau = complexite(messages, tools)
    if not conf.get("routage_actif"):
        return modeles, None, niveau
    if tools:                      # outils requis → pas de rétrogradation (garde-fou)
        return modeles, None, niveau
    if niveau not in NIVEAUX_RETROGRADABLES:
        return modeles, None, niveau

    econome = (conf.get("modele_econome") or "").strip() or _premier_gratuit(modeles, conf)
    if not econome or econome in modeles[:1]:
        return modeles, None, niveau
    # Économe en tête, le reste en filet de sécurité (sans doublon).
    effectifs = [econome] + [m for m in modeles if m != econome]
    return effectifs, econome, niveau


def _premier_gratuit(modeles: list[str], conf: dict) -> str | None:
    """À défaut de modèle économe configuré, prend un `free/*` parmi les fallbacks."""
    for m in modeles + conf.get("fallback_models", []):
        if m.startswith("free/") or m.startswith("ollama/"):
            return m
    return None
