"""Prompt caching conditionnel (Sprint S90b) — rend le préfixe stable BON MARCHÉ selon le
fournisseur EFFECTIF du modèle appelé.

Le préfixe stable posé en S90a (prompt système gelé + outils triés par nom, volatil en
dernier) ne devient économique que si le fournisseur sait le mettre en cache. Or les deux
fournisseurs du parc ne fonctionnent pas pareil :

  • **Anthropic** (`anthropic/*`, via la Gateway LiteLLM) : caching EXPLICITE. Il faut poser
    un « breakpoint » `cache_control: {type: ephemeral}` sur le dernier bloc du préfixe stable
    (ici : le DERNIER message système, juste avant le message volatil de date). Tout ce qui
    précède ce point est alors mis en cache et facturé ~10× moins en relecture.
  • **OpenAI** (`openai/*`, défaut `gpt-4o-mini`) : caching AUTOMATIQUE dès qu'un préfixe de
    ≥ 1024 tokens est stable d'une requête à l'autre. RIEN à poser — on ne touche pas la charge
    (un `cache_control` parasite ferait au mieux un no-op, au pire une erreur de schéma).
  • **Local / forfait** (`ollama/*`, `free/*`, `go/*`, inconnu) : no-op. Pas de facturation au
    call (ou pas de cache serveur) → rien à optimiser, et surtout ne rien casser.

Honnêteté : ce module ne PROMET pas un cache, il rend le préfixe *cacheable*. La preuve se lit
côté réponse Gateway dans `usage.cache_read_input_tokens > 0` — pas ici. No-op si le marquage
échoue (jamais bloquant pour un tour de conversation).
"""


def fournisseur(modele: str) -> str:
    """Famille de fournisseur déduite du préfixe de modèle (`openai/…`, `anthropic/…`)."""
    m = (modele or "").lower()
    if m.startswith("anthropic/") or m.startswith("claude"):
        return "anthropic"
    if m.startswith("openai/") or m.startswith("gpt"):
        return "openai"
    if m.startswith(("ollama/", "free/", "go/")):
        return "local"
    return "autre"


def _dernier_systeme(messages: list[dict]) -> int:
    """Index du DERNIER message `system` — fin du préfixe stable — ou -1 s'il n'y en a pas."""
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "system":
            return i
    return -1


def appliquer(messages: list[dict], modele: str) -> list[dict]:
    """Renvoie les messages prêts pour `modele`, avec un point de cache si — et seulement si —
    le fournisseur est Anthropic.

    Pour tout autre fournisseur on renvoie la LISTE D'ORIGINE telle quelle (même objet) : aucun
    surcoût, aucun risque de schéma. Pour Anthropic, on marque le dernier message système avec
    `cache_control: ephemeral` (le gros préfixe stable est mis en cache), sans muter l'entrée
    de l'appelant (copie superficielle du seul message touché).
    """
    if fournisseur(modele) != "anthropic":
        return messages
    i = _dernier_systeme(messages)
    if i < 0:
        return messages
    msg = dict(messages[i])
    contenu = msg.get("content")
    if isinstance(contenu, str):
        msg["content"] = [{"type": "text", "text": contenu,
                           "cache_control": {"type": "ephemeral"}}]
    elif isinstance(contenu, list) and contenu:
        # Déjà en blocs : marquer le dernier bloc (copie pour ne pas muter l'appelant).
        blocs = [dict(b) if isinstance(b, dict) else b for b in contenu]
        if isinstance(blocs[-1], dict):
            blocs[-1]["cache_control"] = {"type": "ephemeral"}
        msg["content"] = blocs
    else:
        return messages  # contenu vide/inattendu : on ne pose pas de point de cache
    return messages[:i] + [msg] + messages[i + 1:]
