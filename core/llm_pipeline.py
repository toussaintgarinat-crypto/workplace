"""Pipeline d'appel LLM unifié du Cœur (Sprint S138, chantier 0 — fondation).

Avant ce module, TROIS call-sites (`assistant.py`, `classer.py`, le test cerveau
de `config_assistant.py`) recopiaient la même boucle « POST /v1/chat/completions
+ bascule de modèles ». Aucun ne comptait les tokens ni le coût. On centralise ce
chemin ici pour que la **gestion du coût** soit codée UNE fois et profite à tous.

Ordre appliqué dans `completer()` :

    trimming → garde-fou budget → appel gateway (bascule de modèles)
             → mesure usage/coût → journal

Les couches plus lourdes du sprint S138 (qui demandent pgvector / un classifieur)
ne sont pas implémentées mais ont leur crochet balisé pour s'y brancher sans
toucher aux call-sites :
  * `# [S138-1]` routage dynamique par complexité (chantier 1)
  * `# [S138-2]` cache sémantique pgvector (chantier 2)
  * `# [S138-4]` shadow routing dans le governor (chantier 4)
"""

import json
import logging
import os
from dataclasses import dataclass, field

import httpx

import cache_semantique
import journal_usage
import routage
import shadow
import summarisation
import trimming

logger = logging.getLogger(__name__)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://host.docker.internal:4001")
GATEWAY_KEY = os.environ["GATEWAY_KEY"]  # requis — défini dans le .env racine (plus de défaut public)

# Tarifs indicatifs en USD par MILLION de tokens (entrée, sortie). Ils ne servent
# que de repli : si la Gateway (LiteLLM) renvoie l'en-tête `x-litellm-response-cost`,
# c'est LUI qui fait foi. Les modèles `free/*` et `ollama/*` (locaux) coûtent 0.
PRIX_PAR_MTOK = {
    "openai/gpt-4o": (2.5, 10.0),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "anthropic/claude-sonnet-4-6": (3.0, 15.0),
    "google/gemini-2.5-flash-preview": (0.15, 0.60),
}


@dataclass
class Resultat:
    """Issue d'un appel LLM, enrichie pour le suivi des coûts."""
    message: dict | None = None        # message OpenAI complet (content + tool_calls)
    modele_utilise: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cout_usd: float = 0.0
    trimmed_tokens: int = 0
    cache_hit: bool = False            # [S138-2]
    routed_to: str | None = None      # [S138-1] modèle économe si rétrogradé
    complexite: str | None = None
    erreur: str | None = None
    modeles_essayes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.message is not None and self.erreur is None

    @property
    def contenu(self) -> str:
        return (self.message or {}).get("content") or ""


def _sans_cout_marginal(modele: str) -> bool:
    """Vrai si un appel à ce modèle ne coûte rien « au call ».

    - `free/*` et `ollama/*` : gratuits (cloud free ou local).
    - `go/*` : forfait OpenCode Go déjà payé (limite en $-équivalent, pas de
      facturation par appel) → à coût marginal nul, donc jamais bloqué par le
      garde-fou budget (qui ne vise que le payant au call) ni « shadowé ».
    """
    return (modele.startswith("free/") or modele.startswith("ollama/")
            or modele.startswith("go/"))


def _cout(modele: str, tokens_in: int, tokens_out: int, entete_cost: str | None) -> float:
    """Coût de l'appel : en-tête LiteLLM si présent, sinon table de repli, sinon 0."""
    if entete_cost:
        try:
            valeur = float(entete_cost)
            if valeur >= 0:
                return valeur
        except (TypeError, ValueError):
            pass
    if _sans_cout_marginal(modele):
        return 0.0
    prix = PRIX_PAR_MTOK.get(modele)
    if not prix:
        return 0.0  # modèle inconnu de la table : coût non chiffré (mieux que faux)
    p_in, p_out = prix
    return (tokens_in / 1_000_000) * p_in + (tokens_out / 1_000_000) * p_out


def _ordonner_selon_budget(modeles: list[str]) -> tuple[list[str], bool]:
    """Si le budget est en blocage, on ne garde que les modèles gratuits. Sinon on
    laisse l'ordre voulu par l'appelant. Renvoie (modeles, budget_force_gratuit)."""
    if journal_usage.peut_appeler_payant():
        return modeles, False
    gratuits = [m for m in modeles if _sans_cout_marginal(m)]
    logger.warning("Budget LLM atteint : appels payants bloqués, repli sans coût (%s).",
                   ", ".join(gratuits) or "aucun")
    return gratuits, True


async def completer(
    messages: list[dict],
    *,
    modeles: list[str],
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
    temperature: float = 0.2,
    max_tokens: int | None = None,
    response_format: dict | None = None,
    etiquette: str = "chat",
    trim_contexte: bool = True,
    cache: bool = False,
    conf: dict | None = None,
    timeout: float = 120,
    client: httpx.AsyncClient | None = None,
) -> Resultat:
    """Appel LLM unique, économe et journalisé.

    `modeles` : modèle principal puis fallbacks (déjà dédupliqués par l'appelant).
    `etiquette` : catégorie d'usage pour le journal (chat | classement | test…).
    `cache` : autorise le cache sémantique (S138-2). Ignoré si `tools` (effet de
    bord) ; à réserver aux appels déterministes (température basse).
    `conf` : config assistant ({routage_actif, modele_econome, resume_actif…}) qui
    pilote le routage dynamique (S138-1) et la summarization à froid (S138-3b).
    None → ni routage ni résumé.
    Renvoie un `Resultat` ; ne lève pas pour une erreur réseau/modèle (champ `erreur`).
    """
    conf = conf or {}
    proprietaire = client is None
    if proprietaire:
        client = httpx.AsyncClient(timeout=timeout)
    essayes: list[str] = []
    derniere_erreur = None
    try:
        # [S138-3b] summarization à froid : condense l'historique ancien (appel LLM
        # bon marché) AVANT le trim, pour ne pas perdre l'info en coupant la fenêtre.
        if conf.get("resume_actif"):
            messages = await summarisation.condenser(client, messages, conf)

        trimmed = 0
        if trim_contexte:
            messages, trimmed = trimming.trim(messages)

        # [S138-1] routage dynamique : rétrograde une requête triviale vers l'économe.
        routed_to = complexite = None
        if conf:
            modeles, routed_to, complexite = routage.router(messages, modeles, conf, tools)

        # Cache jamais utilisé pour les tours à outils (la réponse a un effet de bord).
        cacheable = cache and not tools and bool(modeles)
        scope = cache_semantique.scope_hash(messages, modeles[0], tools) if cacheable else None

        payload = {"model": None, "messages": messages, "temperature": temperature}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = response_format

        # [S138-2] cache sémantique : lookup → si hit, réponse à 0 token.
        if cacheable:
            hit = await cache_semantique.chercher(client, messages, scope)
            if hit is not None:
                journal_usage.enregistrer(
                    modele=hit.get("modele"), etiquette=etiquette, tokens_in=0,
                    tokens_out=0, cout_usd=0, cache_hit=True, trimmed_tokens=trimmed,
                    complexite=complexite)
                return Resultat(message=hit["message"], modele_utilise=hit.get("modele"),
                                cache_hit=True, trimmed_tokens=trimmed,
                                complexite=complexite)

        # Garde-fou budget : si plafond atteint, ne garder que le gratuit.
        modeles_effectifs, budget_force_gratuit = _ordonner_selon_budget(modeles)
        if not modeles_effectifs:
            msg = "Budget LLM atteint et aucun modèle gratuit configuré."
            journal_usage.enregistrer(modele=None, etiquette=etiquette, tokens_in=0,
                                       tokens_out=0, cout_usd=0, trimmed_tokens=trimmed,
                                       erreur=msg)
            return Resultat(erreur=msg, trimmed_tokens=trimmed)

        for modele in modeles_effectifs:
            essayes.append(modele)
            try:
                payload["model"] = modele
                r = await client.post(
                    f"{GATEWAY_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GATEWAY_KEY}"},
                    json=payload,
                )
                if r.status_code >= 400:
                    derniere_erreur = f"HTTP {r.status_code}"
                    logger.warning("Gateway %s sur %s — modèle suivant", r.status_code, modele)
                    continue
                corps = r.json()
                message = corps["choices"][0]["message"]
                usage = corps.get("usage") or {}
                tokens_in = int(usage.get("prompt_tokens") or 0)
                tokens_out = int(usage.get("completion_tokens") or 0)
                cout = _cout(modele, tokens_in, tokens_out,
                             r.headers.get("x-litellm-response-cost"))
                # Le modèle effectif n'est « rétrogradé » que s'il diffère du 1er voulu.
                routed = routed_to if (routed_to and modele == routed_to) else None
                journal_usage.enregistrer(
                    modele=modele, etiquette=etiquette, tokens_in=tokens_in,
                    tokens_out=tokens_out, cout_usd=cout, trimmed_tokens=trimmed,
                    routed_to=routed, complexite=complexite)
                # On ne met en cache qu'une vraie réponse texte (pas un appel d'outil).
                if cacheable and not message.get("tool_calls"):
                    await cache_semantique.stocker(client, messages, scope, message, modele)
                # [S138-4] shadow : sur une réponse texte, rejoue un candidat moins
                # cher en tâche de fond (n'affecte ni la latence ni la réponse servie).
                texte = message.get("content")
                if texte and not message.get("tool_calls") and not _sans_cout_marginal(modele) \
                        and shadow.echantillonne(conf):
                    shadow.planifier(messages, conf, texte, modele, cout, etiquette)
                return Resultat(message=message, modele_utilise=modele,
                                tokens_in=tokens_in, tokens_out=tokens_out,
                                cout_usd=cout, trimmed_tokens=trimmed,
                                routed_to=routed, complexite=complexite,
                                modeles_essayes=essayes)
            except (httpx.HTTPError, KeyError, IndexError) as e:
                derniere_erreur = str(e)
                logger.warning("Gateway injoignable (%s) sur %s — modèle suivant", e, modele)
                continue

        suffixe = " (budget : repli gratuit only)" if budget_force_gratuit else ""
        erreur = f"Aucun modèle disponible ({derniere_erreur}){suffixe}."
        journal_usage.enregistrer(modele=None, etiquette=etiquette, tokens_in=0,
                                  tokens_out=0, cout_usd=0, trimmed_tokens=trimmed,
                                  erreur=erreur)
        return Resultat(erreur=erreur, trimmed_tokens=trimmed, modeles_essayes=essayes)
    finally:
        if proprietaire:
            await client.aclose()


async def completer_flux(
    messages: list[dict],
    *,
    modeles: list[str],
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
    temperature: float = 0.2,
    max_tokens: int | None = None,
    etiquette: str = "chat",
    trim_contexte: bool = True,
    conf: dict | None = None,
    timeout: float = 120,
    client: httpx.AsyncClient | None = None,
):
    """Variante STREAMING de `completer()` (S60) : émet les tokens au fil de l'eau.

    Générateur asynchrone d'événements :
      • ``{"type":"delta","contenu": <fragment de texte>}``        (0..N fois) ;
      • ``{"type":"fin","message": <message assemblé>, "resultat": Resultat}`` (succès) ;
      • ``{"type":"erreur","erreur": <str>}``                       (aucun modèle).

    Mêmes pré-traitements économes que `completer()` (résumé à froid, trimming, routage,
    garde-fou budget) et même journalisation d'usage. La **bascule de modèle** n'a lieu que
    TANT QU'AUCUN token n'a été émis : une fois le flux commencé, on ne le rejoue pas sur un
    autre modèle (honnêteté — l'utilisateur a déjà vu du texte). Le cache sémantique est
    sauté (chat à outils = effet de bord). Les `tool_calls` arrivent en fragments (par
    `index`) qu'on réassemble avant de rendre le message final."""
    conf = conf or {}
    proprietaire = client is None
    if proprietaire:
        client = httpx.AsyncClient(timeout=timeout)
    essayes: list[str] = []
    derniere_erreur = None
    try:
        if conf.get("resume_actif"):
            messages = await summarisation.condenser(client, messages, conf)
        trimmed = 0
        if trim_contexte:
            messages, trimmed = trimming.trim(messages)
        routed_to = complexite = None
        if conf:
            modeles, routed_to, complexite = routage.router(messages, modeles, conf, tools)

        payload = {"messages": messages, "temperature": temperature,
                   "stream": True, "stream_options": {"include_usage": True}}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        modeles_effectifs, budget_force_gratuit = _ordonner_selon_budget(modeles)
        if not modeles_effectifs:
            msg = "Budget LLM atteint et aucun modèle gratuit configuré."
            journal_usage.enregistrer(modele=None, etiquette=etiquette, tokens_in=0,
                                       tokens_out=0, cout_usd=0, trimmed_tokens=trimmed, erreur=msg)
            yield {"type": "erreur", "erreur": msg}
            return

        for modele in modeles_effectifs:
            essayes.append(modele)
            payload["model"] = modele
            contenu = ""
            tool_frags: dict = {}                 # index -> {id, name, args}
            usage: dict = {}
            emis = False
            try:
                async with client.stream(
                    "POST", f"{GATEWAY_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GATEWAY_KEY}"}, json=payload,
                ) as r:
                    if r.status_code >= 400:
                        derniere_erreur = f"HTTP {r.status_code}"
                        await r.aread()
                        logger.warning("Gateway %s sur %s (flux) — modèle suivant",
                                       r.status_code, modele)
                        continue                  # rien émis → bascule honnête
                    async for ligne in r.aiter_lines():
                        if not ligne or not ligne.startswith("data:"):
                            continue
                        data = ligne[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except ValueError:
                            continue
                        if chunk.get("usage"):
                            usage = chunk["usage"]
                        choix = chunk.get("choices") or []
                        if not choix:
                            continue
                        delta = choix[0].get("delta") or {}
                        frag = delta.get("content")
                        if frag:
                            contenu += frag
                            emis = True
                            yield {"type": "delta", "contenu": frag}
                        for tcd in delta.get("tool_calls") or []:
                            i = tcd.get("index", 0)
                            slot = tool_frags.setdefault(i, {"id": "", "name": "", "args": ""})
                            if tcd.get("id"):
                                slot["id"] = tcd["id"]
                            fn = tcd.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                            if fn.get("arguments"):
                                slot["args"] += fn["arguments"]
                            emis = True
            except httpx.HTTPError as e:
                derniere_erreur = str(e)
                if emis:                          # flux déjà commencé : pas de rejeu honnête
                    yield {"type": "erreur", "erreur": f"Flux interrompu : {e}"}
                    return
                logger.warning("Gateway injoignable (%s) sur %s (flux) — modèle suivant", e, modele)
                continue

            # Flux terminé pour ce modèle → assembler le message complet.
            message: dict = {"role": "assistant", "content": contenu or None}
            if tool_frags:
                message["tool_calls"] = [
                    {"id": s["id"], "type": "function",
                     "function": {"name": s["name"], "arguments": s["args"]}}
                    for _, s in sorted(tool_frags.items())
                ]
            tokens_in = int(usage.get("prompt_tokens") or 0)
            tokens_out = int(usage.get("completion_tokens") or 0)
            cout = _cout(modele, tokens_in, tokens_out, None)
            routed = routed_to if (routed_to and modele == routed_to) else None
            journal_usage.enregistrer(
                modele=modele, etiquette=etiquette, tokens_in=tokens_in,
                tokens_out=tokens_out, cout_usd=cout, trimmed_tokens=trimmed,
                routed_to=routed, complexite=complexite)
            if contenu and not tool_frags and not _sans_cout_marginal(modele) \
                    and shadow.echantillonne(conf):
                shadow.planifier(messages, conf, contenu, modele, cout, etiquette)
            res = Resultat(message=message, modele_utilise=modele, tokens_in=tokens_in,
                           tokens_out=tokens_out, cout_usd=cout, trimmed_tokens=trimmed,
                           routed_to=routed, complexite=complexite, modeles_essayes=essayes)
            yield {"type": "fin", "message": message, "resultat": res}
            return

        erreur = f"Aucun modèle disponible ({derniere_erreur})."
        journal_usage.enregistrer(modele=None, etiquette=etiquette, tokens_in=0,
                                  tokens_out=0, cout_usd=0, trimmed_tokens=trimmed, erreur=erreur)
        yield {"type": "erreur", "erreur": erreur}
    finally:
        if proprietaire:
            await client.aclose()
