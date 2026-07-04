# Sprint S145 — Graphe d'apprentissage : mémoires ↔ capacités par chevauchement lexical

> **But du sprint** : construire un graphe bipartite qui relie les entrées de mémoire
> (brique 5600) aux capacités du Cœur via chevauchement lexical. Ce graphe sert de second
> signal dans `routage_outils.py` : les capacités co-citées avec des souvenirs pertinents
> remontent dans le top-K avant d'être passées au LLM.
> Inspiré de `learning_graph.py` de Hermes Agent (Nous Research, MIT). Complémentaire
> (non concurrent) au routage par cosinus-embeddings livré en S134.

- **Sprint** : S145
- **Catégorie** : Mémoire / Routage IA / Cœur
- **Statut** : CODE-COMPLET, LIVE DIFFÉRÉ
- **Date de planification** : 2026-07-04
- **Date de complétion** : 2026-07-04
- **Briques concernées** : `core/routage_outils.py` + nouveau `core/graphe_apprentissage.py`
- **Prérequis** : Brique mémoire 5600 opérationnelle, routage embeddings S134

---

## Contexte

`routage_outils.py` filtre les ~143 capacités par cosinus (top-8 + socle statique)
avant de les passer au LLM. Le cosinus capture la similarité sémantique mais ignore
les associations explicites : « la dernière fois que j'ai parlé de restaurant, j'avais
besoin de `paiements_initier` et `commande_envoyer` ». Le graphe lexical capture ces
co-occurrences sans embedding.

**Signal complémentaire** : si la requête contient des termes présents dans des souvenirs
qui mentionnent une capacité, cette capacité reçoit un boost de score avant le tri final.

Le graphe est reconstruit à chaque démarrage du Cœur (chargement des souvenirs de la
brique mémoire) et mis en cache en mémoire vive — pas de persistance ni de base de données.

---

## Architecture

```
Brique mémoire 5600
  GET /entries → liste de souvenirs (texte libre)
       │
       ▼
graphe_apprentissage.py
  construire(souvenirs, specs_capacites)
       │
  graphe = {
    souvenir_id → {capacite_nom, score_lexical}*
    capacite_nom → {souvenir_id, score_lexical}*
  }
       │
       ▼
routage_outils.py
  filtrer_outils(requete)
    1. cosinus embeddings → scores_cos
    2. graphe.boost(requete, specs) → scores_boost
    3. score_final = score_cos + α * score_boost
    4. top-K par score_final
```

---

## Chantiers

### C0 — Créer `core/graphe_apprentissage.py`

```python
import re
from dataclasses import dataclass, field

STOPWORDS = {
    "le", "la", "les", "de", "du", "des", "un", "une", "en", "et", "ou",
    "je", "tu", "il", "nous", "vous", "ils", "que", "qui", "ce", "se",
    "est", "sont", "avec", "pour", "sur", "dans", "par", "au", "aux",
    "the", "a", "an", "of", "in", "to", "and", "or", "is", "are",
}
LONGUEUR_MIN_TERME = 3

def _termes(texte: str) -> set[str]:
    mots = re.findall(r"[a-zàâéèêëîïôùûüç_]+", texte.lower())
    return {m for m in mots if len(m) >= LONGUEUR_MIN_TERME and m not in STOPWORDS}

@dataclass
class GrapheApprentissage:
    # capacite_nom → score de boost accumulé (float)
    _boost: dict[str, float] = field(default_factory=dict)
    # capacite_nom → set de termes co-occurrents (pour debug)
    _termes_lies: dict[str, set] = field(default_factory=dict)
    _construit: bool = False

    def construire(self, souvenirs: list[str], specs_capacites: list[dict]) -> None:
        """
        souvenirs : liste de textes bruts (contenus des souvenirs mémoire)
        specs_capacites : liste de dicts avec au moins {"name": str, "description": str}
        """
        self._boost.clear()
        self._termes_lies.clear()

        # Index inversé : terme → {noms de capacités qui le contiennent}
        index_capacites: dict[str, set[str]] = {}
        for spec in specs_capacites:
            nom = spec.get("name", "")
            desc = spec.get("description", "")
            # Les termes du NOM de la capacité ont un bonus × 2
            for t in _termes(nom):
                index_capacites.setdefault(t, set()).add(nom)
            for t in _termes(desc):
                index_capacites.setdefault(t, set()).add(nom)

        # Pour chaque souvenir, chercher les capacités co-citées
        for souvenir in souvenirs:
            termes_sou = _termes(souvenir)
            for terme in termes_sou:
                for cap in index_capacites.get(terme, set()):
                    # Bonus × 2 si le NOM de la capacité est dans le souvenir
                    bonus = 2.0 if terme in _termes(cap) else 1.0
                    self._boost[cap] = self._boost.get(cap, 0.0) + bonus
                    self._termes_lies.setdefault(cap, set()).add(terme)

        # Normaliser entre 0 et 1
        if self._boost:
            max_score = max(self._boost.values())
            if max_score > 0:
                self._boost = {k: v / max_score for k, v in self._boost.items()}

        self._construit = True

    def boost(self, requete: str, specs_capacites: list[dict]) -> dict[str, float]:
        """
        Retourne un dict {nom_capacite: score_boost} pour les capacités
        dont les termes apparaissent dans la requête ET dans le graphe.
        Scores entre 0 et 1.
        """
        if not self._construit:
            return {}
        termes_req = _termes(requete)
        scores: dict[str, float] = {}
        for spec in specs_capacites:
            nom = spec.get("name", "")
            if nom not in self._boost:
                continue
            # Score final = boost_graphe × proportion de termes liés dans la requête
            termes_lies = self._termes_lies.get(nom, set())
            intersection = termes_req & termes_lies
            if not intersection:
                continue
            couverture = len(intersection) / max(len(termes_lies), 1)
            scores[nom] = self._boost[nom] * couverture
        return scores

    def stats(self) -> dict:
        return {
            "capacites_liees": len(self._boost),
            "top5": sorted(self._boost.items(), key=lambda x: -x[1])[:5],
        }
```

### C1 — Charger les souvenirs depuis la brique mémoire

Dans `core/` (probablement `registre.py` ou au démarrage du Cœur), ajouter :

```python
import httpx, os
from graphe_apprentissage import GrapheApprentissage

_graphe = GrapheApprentissage()

async def charger_graphe(specs_capacites: list[dict]) -> None:
    """Appelle la brique mémoire pour récupérer les souvenirs et construit le graphe."""
    memoire_url = os.getenv("MEMOIRE_URL", "http://memoire:5600")
    memoire_key = os.getenv("MEMOIRE_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{memoire_url}/entries",
                headers={"Authorization": f"Bearer {memoire_key}"},
            )
            r.raise_for_status()
            souvenirs = [e.get("content", "") for e in r.json().get("entries", [])]
    except Exception:
        souvenirs = []   # pas de mémoire = graphe vide, pas de crash
    _graphe.construire(souvenirs, specs_capacites)
```

Appeler `charger_graphe()` au démarrage du Cœur, après l'indexation des embeddings.
Exposer `_graphe` pour `routage_outils.py`.

### C2 — Brancher dans `core/routage_outils.py`

Dans `selectionner()` ou `filtrer_outils()`, après avoir calculé les scores cosinus :

```python
from graphe_apprentissage import _graphe

ALPHA_BOOST = float(os.getenv("GRAPHE_ALPHA", "0.3"))  # poids du boost lexical

async def filtrer_outils(requete, toutes_capacites, *, top_k=TOP_K, ...):
    # 1. Scores cosinus existants
    vec = await _embed(client, requete)
    scores_cos = {spec["name"]: _cos(vec, v) for spec, v in zip(...)}

    # 2. Boost graphe lexical
    boosts = _graphe.boost(requete, toutes_capacites)

    # 3. Score combiné
    scores_final = {
        nom: scores_cos.get(nom, 0.0) + ALPHA_BOOST * boosts.get(nom, 0.0)
        for nom in scores_cos
    }

    # 4. Tri et top-K (logique existante, juste changer le dict de scores)
    ...
```

`ALPHA_BOOST = 0.3` : le boost lexical compte pour 30% max du score cosinus.
Réglable par env sans toucher au code.

### C3 — Rafraîchissement périodique (optionnel)

Le graphe est statique après le démarrage. Option : le reconstruire toutes les N heures
via la tâche `horloge.py` existante.

Capacité à ajouter au manifest du Cœur (niveau-0) : `graphe_rafraichir` — déclenche
`charger_graphe()` à la demande (ex. après avoir ajouté des souvenirs importants).

### C4 — Tests

Fichier `core/test_graphe_apprentissage.py` :

| # | Scénario | Attendu |
|---|---|---|
| 1 | `_termes("Hello le monde")` | {"hello", "monde"} (stopword filtré) |
| 2 | Souvenir mentionne "restaurant" + capacité "commande_envoyer" | boost > 0 |
| 3 | Requête sans terme commun | boost vide |
| 4 | Nom de capacité dans souvenir → bonus × 2 | score plus élevé |
| 5 | Normalisation → tous les scores ≤ 1 | True |
| 6 | 0 souvenir → `boost()` retourne {} | True |
| 7 | `construire()` deux fois → reconstruit proprement | pas de cumul |
| 8 | ALPHA=0 → score_final = score_cos pur | True |
| 9 | Brique mémoire indisponible → graphe vide, pas d'exception | True |
| 10 | `stats()` retourne top-5 non vide après construction | len == 5 |

---

## Critère d'acceptation

- Graphe construit au démarrage, silencieux si brique mémoire absente
- `routage_outils.filtrer_outils()` utilise le score combiné cosinus + boost lexical
- `GRAPHE_ALPHA=0` désactive le boost (rétrocompatibilité parfaite)
- 10 tests verts
- Aucune base de données ajoutée — tout en mémoire vive

---

## Effort estimé

**1 journée**
- C0 (graphe_apprentissage.py) : 1h30
- C1 (chargement souvenirs) : 1h — trouver le bon point de démarrage dans le Cœur
- C2 (branchement routage) : 1h
- C3 (rafraîchissement) : 30 min
- C4 (tests) : 1h

## Valeur

Le routage devient « conscient de l'expérience passée » sans retrainer de modèle.
Exemple concret : après plusieurs sessions restaurant, les capacités resto remontent
automatiquement sur les requêtes liées à « table », « commande », « menu » — même
si le cosinus brut ne les aurait pas dans le top-8.
