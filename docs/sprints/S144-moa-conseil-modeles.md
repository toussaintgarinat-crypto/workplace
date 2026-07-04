# Sprint S144 — MOA : conseil de modèles en parallèle avant les réponses complexes

> **But du sprint** : implémenter un *Mixture of Agents* (MOA) dans le Cœur.
> Sur les requêtes marquées « complexes », N modèles du Gateway tournent en parallèle
> sur le même contexte en rôle « conseiller analytique » (sans outils), puis un modèle
> agrégateur synthétise leurs avis en une guidance privée injectée avant la réponse finale.
> Inspiré de `moa_loop.py` de Hermes Agent (Nous Research, MIT). S'appuie sur le Gateway
> multi-fournisseurs livré en S93.

- **Sprint** : S144
- **Catégorie** : Qualité IA / Cœur
- **Statut** : CODE-COMPLET, LIVE DIFFÉRÉ
- **Date de planification** : 2026-07-04
- **Briques concernées** : `core/` (`moa.py` nouveau + `llm_pipeline.py` + `orchestrateur.py`)
- **Prérequis** : Gateway S93 opérationnel (plusieurs modèles configurés)

---

## Contexte

Le Cœur appelle aujourd'hui un seul modèle (via `llm_pipeline.completer`). Sur les
décisions complexes (planification, analyse, jugement métier), un seul modèle peut rater
un angle. Le MOA donne le même contexte à plusieurs modèles différents, récupère leurs
avis divergents, puis laisse le modèle principal synthétiser avant de répondre.

Avantage concret de Workplace : le Gateway (S93) expose déjà plusieurs fournisseurs
(OpenRouter, OpenAI, Anthropic, modèles locaux). Le MOA n'ajoute pas de dépendance,
il réutilise l'infrastructure existante.

**Opt-in** : activé uniquement si `MOA_MODELES` est défini dans `.env`. Zéro impact
sur les installations sans la variable.

---

## Architecture

```
requete utilisateur
       │
       ▼
 [détecteur complexité]
 complexe ? ──non──→ llm_pipeline.completer() [chemin normal]
       │
      oui
       │
       ▼
  moa.consulter()
  ┌──────────────────────────────────────┐
  │  Référence 1 (modele_a)  ──┐          │
  │  Référence 2 (modele_b)  ──┼─ async  │
  │  Référence 3 (modele_c)  ──┘          │
  │         ↓ synthese(agregateur)        │
  │  guidance = "…conseil consolidé…"     │
  └──────────────────────────────────────┘
       │
       ▼
  llm_pipeline.completer(
      messages + [{"role":"system","content": guidance}]
  )
       │
       ▼
  réponse finale
```

---

## Chantiers

### C0 — Créer `core/moa.py`

```python
import asyncio, hashlib, json, os
from typing import NamedTuple
import httpx

class ConfigMOA(NamedTuple):
    modeles_reference: list[str]   # ex. ["openrouter/mistral-large", "openai/gpt-4o"]
    agregateur: str                 # ex. "anthropic/claude-sonnet-4-6"
    max_tokens_ref: int = 800
    temperature_ref: float = 0.4

def _depuis_env() -> ConfigMOA | None:
    """Construit la config depuis MOA_MODELES et MOA_AGREGATEUR. None si absent."""
    brut = os.getenv("MOA_MODELES", "")
    if not brut.strip():
        return None
    modeles = [m.strip() for m in brut.split(",") if m.strip()]
    agregateur = os.getenv("MOA_AGREGATEUR", modeles[0] if modeles else "")
    return ConfigMOA(modeles_reference=modeles, agregateur=agregateur)

_cache_guidance: dict[str, str] = {}

def _hash_contexte(messages: list) -> str:
    return hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()[:16]

async def _appeler_reference(modele: str, messages: list, config: ConfigMOA,
                              client: httpx.AsyncClient) -> str:
    """Appelle le Gateway pour un seul modèle référence. Retourne le texte brut."""
    # Les références ne peuvent PAS appeler d'outils — on retire tools du payload
    # et on injecte un system spécifique.
    system_ref = (
        "Tu es un conseiller analytique dans un processus Mixture of Agents. "
        "Analyse la situation et donne un avis synthétique, factuel, sans exécuter d'actions."
    )
    msgs_ref = [m for m in messages if m.get("role") != "system"]
    payload = {
        "model": modele,
        "messages": [{"role": "system", "content": system_ref}] + msgs_ref,
        "max_tokens": config.max_tokens_ref,
        "temperature": config.temperature_ref,
    }
    gateway_url = os.getenv("GATEWAY_URL", "http://gateway:4000")
    gateway_key = os.getenv("GATEWAY_KEY", "")
    try:
        r = await client.post(
            f"{gateway_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {gateway_key}"},
            timeout=30.0,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[référence {modele} indisponible : {e}]"

async def consulter(messages: list, config: ConfigMOA,
                    client: httpx.AsyncClient) -> str:
    """Lance les références en parallèle, synthétise. Retourne la guidance."""
    h = _hash_contexte(messages)
    if h in _cache_guidance:
        return _cache_guidance[h]

    taches = [
        _appeler_reference(m, messages, config, client)
        for m in config.modeles_reference
    ]
    avis = await asyncio.gather(*taches)

    # Agrégation
    blocs = "\n\n".join(
        f"Référence {i+1} — {config.modeles_reference[i]}:\n{texte}"
        for i, texte in enumerate(avis)
    )
    prompt_agregation = (
        "Voici les avis de plusieurs modèles de référence sur la situation :\n\n"
        f"{blocs}\n\n"
        "Synthétise ces avis en une guidance concise (3-5 phrases max) "
        "à destination du modèle principal. Sois direct et actionnable."
    )
    guidance = await _appeler_reference(
        config.agregateur,
        messages + [{"role": "user", "content": prompt_agregation}],
        config,
        client,
    )
    _cache_guidance[h] = guidance
    return guidance
```

### C1 — Détecteur de complexité

Dans `core/moa.py`, une heuristique simple (sans LLM) pour ne pas déclencher le MOA
sur les échanges triviaux :

```python
MOTS_COMPLEXES = {
    "planifie", "stratégie", "décide", "compare", "analyse", "choisir",
    "architecture", "implémente", "conception", "évaluer", "risque",
}

def est_complexe(message_utilisateur: str) -> bool:
    """Heuristique légère : longueur > 120 car OU mot-clé de complexité détecté."""
    msg = message_utilisateur.lower()
    if len(message_utilisateur) > 120:
        return True
    return any(mot in msg for mot in MOTS_COMPLEXES)
```

Seuil volontairement généreux — le MOA est opt-in et coûte peu sur des modèles rapides.

### C2 — Brancher dans `core/orchestrateur.py` ou `llm_pipeline.py`

Avant l'appel `llm_pipeline.completer()`, si `_depuis_env()` renvoie une config et
`est_complexe(derniere_msg_user)` est vrai :

```python
from moa import consulter, est_complexe, _depuis_env

config_moa = _depuis_env()
if config_moa and est_complexe(message_utilisateur):
    guidance = await consulter(messages, config_moa, http_client)
    # Injecter comme message system éphémère (non persisté dans le journal)
    messages = messages + [{"role": "system", "content": f"[Conseil MOA]\n{guidance}"]
```

La guidance est **éphémère** : injectée pour ce seul appel, jamais stockée dans
`journal_conversations`.

### C3 — Variable d'env + `.env.example`

```bash
# .env
MOA_MODELES=openrouter/mistral-large,openrouter/deepseek-r1
MOA_AGREGATEUR=anthropic/claude-sonnet-4-6

# Laisser vide = MOA désactivé (comportement par défaut)
```

Ajouter dans `.env.example` avec commentaire explicite.

### C4 — Tests

Fichier `core/test_moa.py` — mocker `_appeler_reference` :

| # | Scénario | Attendu |
|---|---|---|
| 1 | `_depuis_env()` sans MOA_MODELES | None (désactivé) |
| 2 | `est_complexe("ok")` | False |
| 3 | `est_complexe("planifie l'architecture de migration")` | True |
| 4 | `est_complexe("x" * 130)` | True (longueur) |
| 5 | `consulter()` appelle N références en parallèle | N appels HTTP |
| 6 | `consulter()` sur même contexte × 2 | 1 seul appel (cache) |
| 7 | Référence en timeout → texte d'erreur, pas d'exception | avis partiel |
| 8 | Guidance contient les noms des modèles référence | dans le blocs |
| 9 | MOA_MODELES avec 1 modèle | fonctionne (1 référence) |
| 10 | Cache invalidé si messages changent | 2 appels |

---

## Critère d'acceptation

- MOA inactif par défaut (sans `MOA_MODELES`) — zéro régression
- Quand actif, la guidance est injectée avant le LLM principal sur les requêtes complexes
- Les références tournent en parallèle (`asyncio.gather`)
- Le cache évite de re-consulter si le contexte n'a pas changé
- 10 tests verts

---

## Effort estimé

**1 journée**
- C0 (moa.py) : 2h
- C1 (détecteur) : 30 min
- C2 (branchement) : 1h
- C3 (env) : 15 min
- C4 (tests) : 1h30

## Valeur

Améliore la qualité des réponses complexes sans changer le prompt système.
Réutilise l'infrastructure Gateway existante — aucun nouveau fournisseur requis.
Coût marginal faible si on utilise des modèles rapides/économiques comme références.
