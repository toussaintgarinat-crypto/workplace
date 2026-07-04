# Sprint S143 — Guardrails outils : protéger le Cœur contre les boucles

> **But du sprint** : ajouter une couche de protection autour de l'exécution des outils
> dans le Cœur. Quand un outil boucle (même appel répété, résultat identique, outil en
> échec permanent), le Cœur avertit puis bloque au lieu de consommer des tokens à l'infini.
> Inspiré de `tool_guardrails.py` de Hermes Agent (Nous Research, MIT).

- **Sprint** : S143
- **Catégorie** : Robustesse / Cœur
- **Statut** : CODE-COMPLET, LIVE DIFFÉRÉ
- **Date de planification** : 2026-07-04
- **Date de livraison** : 2026-07-04
- **Briques concernées** : `core/` uniquement (`orchestrateur.py` + nouveau `guardrails_outils.py`)

---

## Contexte

Aujourd'hui `core/orchestrateur.py` exécute les outils demandés par le LLM sans vérifier
si le même outil a déjà été appelé à l'identique ou si son résultat n'a pas changé depuis
3 tours. Des cas réels sur Workplace :

- L'assistant tente `recherche_web` en boucle quand SearXNG est down : 10+ appels, 0 résultat.
- Un outil de lecture (ex. `memoire_lire`) appelé avec les mêmes args renvoie la même chose
  en boucle sans que le LLM avance.
- Un outil mal câblé lève toujours la même exception → le Cœur réessaie indéfiniment.

Le fix est un contrôleur **par tour** (pas de persistance entre conversations) : léger,
sans base de données, sans état global — juste un dict en mémoire pour la durée de la
boucle d'inférence.

---

## Architecture

```
orchestrateur.py
    │
    ├── before_call(nom, args) → Decision(action, message)
    │       ↓ allow / warn / block / halt
    ├── [appel outil]
    └── after_call(nom, args, resultat, erreur=None)
```

Un `Decision` porte : `action` (allow/warn/block/halt) + `message` optionnel affiché
dans la réponse LLM comme texte system si warn/block.

---

## Chantiers

### C0 — Créer `core/guardrails_outils.py`

```python
from dataclasses import dataclass, field
from hashlib import sha256
import json

@dataclass
class Config:
    seuil_warn_echecs_identiques: int = 2   # même outil + mêmes args + erreur → warn
    seuil_block_echecs_identiques: int = 4
    seuil_warn_resultat_identique: int = 3   # outil idempotent, résultat inchangé
    seuil_block_resultat_identique: int = 5
    seuil_warn_echecs_meme_outil: int = 3    # même outil, toute erreur
    seuil_block_echecs_meme_outil: int = 6

@dataclass
class Guardrail:
    config: Config = field(default_factory=Config)
    # clé = sha256(nom+args) → compteur échecs identiques
    _echecs_identiques: dict = field(default_factory=dict)
    # clé = nom_outil → compteur total échecs
    _echecs_outil: dict = field(default_factory=dict)
    # clé = sha256(nom+args) → dernier résultat + compteur répétitions
    _resultats: dict = field(default_factory=dict)

    def _cle(self, nom: str, args: dict) -> str:
        return sha256(f"{nom}:{json.dumps(args, sort_keys=True)}".encode()).hexdigest()[:16]

    def before_call(self, nom: str, args: dict) -> tuple[str, str | None]:
        """Retourne (action, message). action ∈ allow|warn|block|halt."""
        cle = self._cle(nom, args)
        n_id = self._echecs_identiques.get(cle, 0)
        n_outil = self._echecs_outil.get(nom, 0)
        c = self.config
        if n_id >= c.seuil_block_echecs_identiques:
            return "block", f"Outil `{nom}` a échoué {n_id}× avec ces arguments — arrêté."
        if n_outil >= c.seuil_block_echecs_meme_outil:
            return "block", f"Outil `{nom}` a échoué {n_outil}× consécutivement — arrêté."
        if n_id >= c.seuil_warn_echecs_identiques:
            return "warn", f"Outil `{nom}` déjà en échec {n_id}× avec ces arguments."
        if n_outil >= c.seuil_warn_echecs_meme_outil:
            return "warn", f"Outil `{nom}` a déjà échoué {n_outil}× — tenter une autre approche."
        return "allow", None

    def after_call(self, nom: str, args: dict, resultat: str, erreur: bool = False):
        cle = self._cle(nom, args)
        if erreur:
            self._echecs_identiques[cle] = self._echecs_identiques.get(cle, 0) + 1
            self._echecs_outil[nom] = self._echecs_outil.get(nom, 0) + 1
        else:
            self._echecs_identiques.pop(cle, None)
            self._echecs_outil.pop(nom, None)
            # détection résultat identique (idempotence stérile)
            prev = self._resultats.get(cle)
            if prev and prev["hash"] == sha256(resultat.encode()).hexdigest():
                prev["n"] += 1
            else:
                self._resultats[cle] = {"hash": sha256(resultat.encode()).hexdigest(), "n": 1}

    def verifier_idempotence(self, nom: str, args: dict) -> tuple[str, str | None]:
        """Appeler avant de retourner le résultat au LLM pour détecter les lectures circulaires."""
        cle = self._cle(nom, args)
        n = self._resultats.get(cle, {}).get("n", 0)
        c = self.config
        if n >= c.seuil_block_resultat_identique:
            return "block", f"`{nom}` retourne le même résultat depuis {n} tours — aucun progrès."
        if n >= c.seuil_warn_resultat_identique:
            return "warn", f"`{nom}` retourne le même résultat depuis {n} tours."
        return "allow", None

    def reinitialiser(self):
        self._echecs_identiques.clear()
        self._echecs_outil.clear()
        self._resultats.clear()
```

### C1 — Brancher dans `core/orchestrateur.py`

Localiser la boucle d'exécution des tool_calls (probablement dans `executer_outils` ou
équivalent). Ajouter :

```python
from guardrails_outils import Guardrail

# Au début de chaque conversation / inférence :
guardrail = Guardrail()

# Avant chaque appel outil :
action, msg = guardrail.before_call(nom_outil, args)
if action in ("block", "halt"):
    # Injecter msg comme résultat synthétique côté tool_result
    return {"role": "tool", "content": f"[GUARDRAIL] {msg}"}
if action == "warn":
    # Ajouter msg en note dans le tool_result qui suit
    ...

# Après l'appel :
guardrail.after_call(nom_outil, args, resultat, erreur=bool(exception))

# Après avoir obtenu le résultat (avant de le repasser au LLM) :
action, msg = guardrail.verifier_idempotence(nom_outil, args)
```

Le `Guardrail` est **instancié par requête** (ou par session de boucle d'inférence),
pas en global — pas de fuite entre conversations.

### C2 — Exposer les seuils par variable d'env (optionnel)

```bash
# .env
GUARDRAIL_SEUIL_BLOCK_ECHECS=4    # défaut 4
GUARDRAIL_SEUIL_BLOCK_IDENTIQUE=5 # défaut 5
```

Dans `Config`, lire avec `os.getenv` et int(). Permet d'affiner sans toucher au code.

### C3 — Tests

Fichier `core/test_guardrails_outils.py` :

| # | Scénario | Attendu |
|---|---|---|
| 1 | Même outil + mêmes args, 1 échec | allow |
| 2 | Même outil + mêmes args, 3 échecs | warn |
| 3 | Même outil + mêmes args, 5 échecs | block |
| 4 | Outil différent même nom, 4 échecs variés | block (meme_outil) |
| 5 | Résultat identique × 2 | allow |
| 6 | Résultat identique × 3 | warn idempotence |
| 7 | Résultat identique × 6 | block idempotence |
| 8 | Succès après échec remet les compteurs à zéro | allow |
| 9 | reinitialiser() vide tout | allow |
| 10 | Deux args différents pour le même outil → compteurs indépendants | allow |

---

## Critère d'acceptation

- `Guardrail.before_call()` bloque avant le 5ème échec identique
- `Guardrail.verifier_idempotence()` avertit au 3ème résultat identique
- Le `Guardrail` est instancié **par requête**, jamais en global
- 10 tests verts
- Aucun impact sur les appels normaux (tout passe en `allow` si pas de répétition)

---

## Effort estimé

**½ journée**
- C0 (guardrails_outils.py) : 1h
- C1 (branchement orchestrateur) : 1h — localiser le bon endroit dans orchestrateur.py
- C2 (env vars) : 15 min
- C3 (tests) : 45 min

## Valeur

Stoppe les boucles d'outils sans toucher au prompt système.
Applicable dès que la brique recherche est down ou qu'un outil externe flanche.
