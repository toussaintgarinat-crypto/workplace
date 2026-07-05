# Sprint S150 — Forge : validation Pydantic sur les endpoints `request.json()`

> **But du sprint** : remplacer les 11 appels `await request.json()` bruts dans les
> routers Forge par des modèles Pydantic, afin qu'un corps de requête invalide retourne
> un 422 clair au lieu d'un 500 avec KeyError.

- **Sprint** : S150
- **Catégorie** : Qualité / Fiabilité / Brique Forge
- **Statut** : CODE-COMPLET
- **Date de planification** : 2026-07-04
- **Date de livraison** : 2026-07-04
- **Briques concernées** : `briques/forge/forge/core/app/routers/`
- **Prérequis** : aucun (Pydantic déjà installé dans Forge)

---

## Contexte

Plusieurs routers de la brique Forge parsent le corps HTTP avec `await request.json()`
brut, sans modèle Pydantic :

```python
# Exemple actuel — briques/forge/forge/core/app/routers/agents.py:46
@router.post("/agents")
async def creer_agent(request: Request):
    body = await request.json()
    nom = body["nom"]          # KeyError si "nom" absent → 500 opaque
    ...
```

**Endpoints concernés** (11 occurrences) :
- `facturation.py:152`
- `agents.py:46`
- `kb.py:108`
- `brief.py:43`
- `llm_config.py:220`
- `agents_factory.py:174`
- `veille.py:64` et `veille.py:108`
- `skills.py:118`
- `connexion.py:128` (brique connexion)
- `netbird.py:49`

D'autres routers Forge utilisent déjà des modèles Pydantic (`class CorpsX(BaseModel)`).
Le pattern est présent, il suffit de l'étendre.

---

## Chantiers

### C0 — Inventaire complet des endpoints concernés

```bash
grep -n "request\.json()" briques/forge/forge/core/app/routers/*.py briques/connexion/main.py
```

Pour chaque occurrence, noter :
- Quels champs sont lus (`body["champ"]`, `body.get("champ")`)
- Si le champ est requis ou optionnel
- Le type attendu

### C1 — Ajouter un modèle Pydantic par endpoint

Pattern cible :

```python
from pydantic import BaseModel

class CorpsCreerAgent(BaseModel):
    nom: str
    description: str | None = None
    forge_url: str = "http://localhost:3001"

@router.post("/agents")
async def creer_agent(body: CorpsCreerAgent):
    # body.nom est garanti non-None, type str
    ...
```

FastAPI gère automatiquement la désérialisation et retourne 422 avec le détail
des champs manquants ou mal typés.

**Règle** : si un champ est actuellement `body.get("champ")` avec une valeur par défaut,
le déclarer optionnel avec cette valeur par défaut dans le modèle.

### C2 — Endpoints à prioriser (impact utilisateur fort)

| Priorité | Endpoint | Risque actuel |
|---|---|---|
| 1 | `agents.py` — créer/modifier agent | Crash si `nom` absent |
| 2 | `facturation.py` — créer facture | Crash si montant absent |
| 3 | `llm_config.py` — changer config LLM | Crash si `model` absent |
| 4 | `kb.py` — ajouter à la base de connaissances | Crash si `contenu` absent |
| 5 | `veille.py` × 2 — lancer veille | Crash si `url` absent |
| 6 | `brief.py`, `agents_factory.py`, `skills.py`, `netbird.py` | Même pattern |

### C3 — Cas particuliers

**`netbird.py:49`** : cet endpoint est un pass-through vers l'API NetBird. Le body
est transmis tel quel. Utiliser `body: dict = Body(...)` plutôt qu'un modèle strict.

**`connexion/main.py:128`** : vérifier si la brique connexion utilise FastAPI ou Flask.
Si Flask : le pattern est `request.get_json()` → utiliser une dataclass ou marshmallow.

### C4 — Tests de validation

Pour chaque router modifié, ajouter un test vérifiant le comportement sur corps invalide :

```python
def test_creer_agent_corps_invalide(client):
    """Corps vide doit retourner 422, pas 500."""
    resp = client.post("/api/agents", json={}, headers=auth_headers)
    assert resp.status_code == 422
    assert "nom" in resp.json()["detail"][0]["loc"]

def test_creer_agent_corps_valide(client):
    """Corps valide crée l'agent."""
    resp = client.post("/api/agents",
        json={"nom": "Test Agent", "description": "Pour test"},
        headers=auth_headers)
    assert resp.status_code in (200, 201)
```

Objectif : au moins 1 test d'invalidation + 1 test de succès par endpoint modifié.

---

## Critère d'acceptation

- Les 11 occurrences de `request.json()` remplacées par des modèles Pydantic (ou `Body(...)` pour les pass-through)
- Un corps invalide retourne 422 avec détail des champs manquants (plus de 500 / KeyError)
- Au moins 6 tests (un par endpoint prioritaire, C2)
- Comportement identique pour les corps valides existants
- `make test` dans `briques/forge/` reste vert

---

## Effort estimé

**Demi-journée (3-4h)**
- C0 (inventaire) : 30 min — lire les 11 endpoints, noter les champs
- C1+C2 (modèles Pydantic, priorités 1-6) : 2h — mécanique mais exhaustif
- C3 (cas particuliers) : 30 min
- C4 (tests) : 1h

## Valeur

Un champ manquant dans l'interface Forge retourne désormais un message d'erreur
précis et actionnable (`"champ 'nom' requis"`) au lieu d'une stack trace 500 invisible
côté utilisateur. Le débogage passe de minutes à secondes.
