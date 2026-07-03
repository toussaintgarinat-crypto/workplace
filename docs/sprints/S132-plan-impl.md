# S132 — Bouton « 🛠️ Améliorer » : workflow dev guidé dans l'assistant

> **Pour agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un bouton fixe `[🛠️ Améliorer]` dans l'onglet Assistant du dashboard qui guide l'utilisateur pas-à-pas à travers le cycle complet `dev_demander → gate → fusionner`.

**Architecture:** Le bouton est un élément HTML statique (pas un bouton SSE) dans `DASHBOARD_HTML` qui réutilise la fonction JS existante `taperAction()`. Le prompt système du Cœur gagne une section expliquant le workflow. `suggestions.py` émet des boutons SSE contextuels (labels dev-specifiques) en lieu et place des génériques Confirmer/Annuler pour les outils `dev_*`.

**Tech Stack:** Python · FastAPI · HTML/JS inline dans `dashboard.py` · pytest

## Global Constraints

- Aucune nouvelle dépendance Python.
- Les boutons SSE ne court-circuitent JAMAIS le gate humain (S76 invariant).
- `taperAction(envoi)` déjà disponible en JS : injecte `envoi` dans le chat-input et soumet le formulaire.
- Tous les tests dans `core/test_bouton_ameliorer.py`.
- TDD : écrire le test avant l'implémentation.

---

## Fichiers touchés

| Fichier | Action | Rôle |
|---|---|---|
| `core/routers/dashboard.py` | Modifier | Ajouter le bouton `[🛠️ Améliorer]` dans DASHBOARD_HTML |
| `core/assistant.py` | Modifier | Ajouter section workflow améliorer dans PROMPT_SYSTEME |
| `core/suggestions.py` | Modifier | Boutons SSE contextuels pour outils `dev_*` |
| `core/test_bouton_ameliorer.py` | Créer | Tests P4 : HTML + suggestions |

---

### Tâche 1 : Bouton `[🛠️ Améliorer]` dans le dashboard

**Fichiers :**
- Modifier : `core/routers/dashboard.py` (la constante `DASHBOARD_HTML`, section `.asst-tete`)
- Créer : `core/test_bouton_ameliorer.py`

**Interfaces :**
- Consomme : `taperAction(str)` déjà défini en JS dans le même fichier (ligne ~2406)
- Produit : `id="btn-ameliorer"` visible dans le HTML rendu par `GET /dashboard`

- [ ] **Étape 1 : Écrire le test qui échoue**

```python
# core/test_bouton_ameliorer.py
"""Tests S132 — bouton [🛠️ Améliorer] + suggestions dev_*."""
import os
os.environ.setdefault("VAULT_SECRET", "test-secret-0123456789")
os.environ.setdefault("GATEWAY_KEY", "test")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)


def test_bouton_ameliorer_present_dans_dashboard():
    html = client.get("/dashboard").text
    assert 'id="btn-ameliorer"' in html
    assert "🛠️" in html
    assert "Améliorer" in html


def test_bouton_ameliorer_injecte_le_bon_message():
    """Le bouton appelle taperAction avec la phrase déclencheur exacte."""
    html = client.get("/dashboard").text
    assert "Je veux améliorer la solution." in html
    assert "taperAction" in html
```

- [ ] **Étape 2 : Lancer le test pour vérifier qu'il échoue**

```bash
cd /Users/garinat_t/Desktop/Workplace/core
python -m pytest test_bouton_ameliorer.py::test_bouton_ameliorer_present_dans_dashboard -v
```

Expected : FAIL — `AssertionError: assert 'id="btn-ameliorer"'`

- [ ] **Étape 3 : Ajouter le bouton dans DASHBOARD_HTML**

Dans `core/routers/dashboard.py`, trouver le bloc toolbar de l'assistant (dans la section `asst-tete`, le div avec les boutons `btn-rappels`, `btn-voix`, `btn-cerveau`) et ajouter le bouton **en premier** dans ce div.

Remplacer :
```python
          <div style="display:flex;gap:8px;flex-shrink:0">
            <button class="btn ghost" id="btn-rappels" onclick="basculerRappels()" title="Rappels">🔔<span id="rappels-pastille" class="pastille" style="display:none">0</span></button>
            <button class="btn ghost" id="btn-voix" onclick="basculerLectureVocale()" title="Lire les réponses à voix haute">🔊 Voix : off</button>
            <button class="btn ghost" id="btn-cerveau" onclick="toggleCerveau()">⚙ Cerveau</button>
          </div>
```

Par :
```python
          <div style="display:flex;gap:8px;flex-shrink:0">
            <button class="btn" id="btn-ameliorer" onclick="taperAction('Je veux améliorer la solution.')" title="Ouvrir le workflow de développement guidé — planifier, coder, valider, pousser en prod.">🛠️ Améliorer</button>
            <button class="btn ghost" id="btn-rappels" onclick="basculerRappels()" title="Rappels">🔔<span id="rappels-pastille" class="pastille" style="display:none">0</span></button>
            <button class="btn ghost" id="btn-voix" onclick="basculerLectureVocale()" title="Lire les réponses à voix haute">🔊 Voix : off</button>
            <button class="btn ghost" id="btn-cerveau" onclick="toggleCerveau()">⚙ Cerveau</button>
          </div>
```

- [ ] **Étape 4 : Lancer les tests pour vérifier qu'ils passent**

```bash
cd /Users/garinat_t/Desktop/Workplace/core
python -m pytest test_bouton_ameliorer.py -v
```

Expected : PASS (2 tests)

- [ ] **Étape 5 : Commit**

```bash
git add core/routers/dashboard.py core/test_bouton_ameliorer.py
git commit -m "feat S132 : bouton fixe [🛠️ Améliorer] dans l'onglet Assistant"
```

---

### Tâche 2 : Addendum workflow améliorer dans PROMPT_SYSTEME

**Fichiers :**
- Modifier : `core/assistant.py` (constante `PROMPT_SYSTEME`, fin de la chaîne)

**Interfaces :**
- Consomme : `dev_demander`, `dev_diff`, `dev_plan_valider`, `dev_fusionner`, `dev_jeter` (outils découverts via manifest brique dev 5955)
- Produit : le LLM sait poser UNE question ouverte au déclencheur "Je veux améliorer la solution.", puis appeler `dev_demander`

- [ ] **Étape 1 : Ajouter la section workflow à PROMPT_SYSTEME**

Dans `core/assistant.py`, trouver la fin de `PROMPT_SYSTEME` (ligne ~90) :
```python
    "- Si un outil échoue, explique-le simplement et continue."
    # La langue de réponse est ajoutée à chaud (cf. converser → langue.consigne_reponse) :
    # c'est une préférence d'utilisateur (S39), pas un choix codé en dur.
)
```

Remplacer par :
```python
    "- Si un outil échoue, explique-le simplement et continue.\n\n"
    "Workflow AMÉLIORER : quand l'utilisateur dit « Je veux améliorer la solution » ou clique"
    " [🛠️ Améliorer], pose-lui UNE seule question courte (« Qu'est-ce que tu veux ajouter"
    " ou changer ? »), attends sa réponse, puis appelle `dev_demander(intention=<sa réponse>)`."
    " Pour la suite : `dev_diff(cid=...)` quand il demande le diff ;"
    " `dev_plan_valider(cid=..., confirme=true)` pour valider le plan ;"
    " `dev_fusionner(cid=..., confirme=true)` pour pousser en prod ;"
    " `dev_jeter(cid=...)` pour annuler. Les boutons de navigation apparaissent automatiquement"
    " dans le chat après chaque outil — ne les liste pas dans ta réponse texte."
    # La langue de réponse est ajoutée à chaud (cf. converser → langue.consigne_reponse) :
    # c'est une préférence d'utilisateur (S39), pas un choix codé en dur.
)
```

- [ ] **Étape 2 : Vérifier que les tests existants passent toujours**

```bash
cd /Users/garinat_t/Desktop/Workplace/core
python -m pytest test_bouton_ameliorer.py test_dashboard.py -v
```

Expected : PASS (tous)

- [ ] **Étape 3 : Commit**

```bash
git add core/assistant.py
git commit -m "feat S132 : workflow améliorer dans PROMPT_SYSTEME (question + dev_demander)"
```

---

### Tâche 3 : Boutons SSE contextuels pour outils `dev_*`

**Fichiers :**
- Modifier : `core/suggestions.py`
- Modifier : `core/test_bouton_ameliorer.py` (ajouter les tests suggestions)

**Interfaces :**
- Consomme : `pour_resultat(nom, args, resultat, *, confirmation)` — signature existante
- Produit : labels contextuels pour `dev_demander`, `dev_plan_valider`, `dev_lancer`, `dev_fusionner` au lieu des génériques Confirmer/Annuler

**Règle de mapping :**

| `nom` | `confirmation` | Boutons émis |
|---|---|---|
| `dev_demander` | `True` | `[✅ Valider & lancer le chantier]` + `[❌ Annuler]` |
| `dev_plan_valider` | `True` | `[✅ Valider le plan & coder]` + `[❌ Annuler]` |
| `dev_lancer` | `False` | `[🚀 Fusionner en prod]` + `[👀 Voir le diff]` + `[❌ Jeter le chantier]` |
| `dev_fusionner` | `True` | `[🚀 Fusionner en prod]` + `[👀 Voir le diff d'abord]` + `[❌ Annuler]` |
| autres | `True` | `[✅ Confirmer]` + `[✖ Annuler]` (comportement actuel) |
| autres | `False` | `[]` (comportement actuel) |

Les messages `envoi` suivent les mots-clés de la table de mapping du sprint :
- "Oui, confirme." → ré-appelle l'outil avec `confirme=True`
- "Non, annule, merci." → déclenche l'annulation
- "montre-moi le diff" → appelle `dev_diff`
- "fusionne sur git et redémarre sur le HP" → appelle `dev_fusionner`
- "annule le chantier dev" → appelle `dev_jeter`

- [ ] **Étape 1 : Ajouter les tests dans `test_bouton_ameliorer.py`**

Ajouter à la fin du fichier :

```python
import suggestions  # noqa: E402 (after os.environ setup above)


def test_suggestions_dev_demander_avec_confirmation():
    """dev_demander avec gate → boutons spécifiques, pas les génériques."""
    s = suggestions.pour_resultat("dev_demander", {}, '{"confirmation_requise": true}',
                                  confirmation=True)
    labels = [b["label"] for b in s]
    assert any("Valider" in l for l in labels)
    assert any("Annuler" in l for l in labels)
    # Les envoi doivent rester les phrases reconnues par le prompt
    envois = [b["envoi"] for b in s]
    assert any("confirme" in e.lower() for e in envois)


def test_suggestions_dev_plan_valider_avec_confirmation():
    """dev_plan_valider avec gate → boutons de validation du plan."""
    s = suggestions.pour_resultat("dev_plan_valider", {"cid": "abc"}, '{"confirmation_requise": true}',
                                  confirmation=True)
    labels = [b["label"] for b in s]
    assert any("plan" in l.lower() or "coder" in l.lower() or "Valider" in l for l in labels)
    assert len(s) >= 2


def test_suggestions_dev_lancer_sans_confirmation():
    """dev_lancer sans gate (code terminé) → boutons diff + fusionner."""
    s = suggestions.pour_resultat("dev_lancer", {"cid": "abc"}, '{"statut": "revue"}',
                                  confirmation=False)
    labels = [b["label"] for b in s]
    assert any("Fusionner" in l or "prod" in l.lower() for l in labels)
    assert any("diff" in l.lower() or "Diff" in l for l in labels)
    assert len(s) >= 2


def test_suggestions_dev_fusionner_avec_confirmation():
    """dev_fusionner avec gate → fusionner + voir diff + annuler."""
    s = suggestions.pour_resultat("dev_fusionner", {"cid": "abc"}, '{"confirmation_requise": true}',
                                  confirmation=True)
    labels = [b["label"] for b in s]
    assert any("Fusionner" in l or "prod" in l.lower() for l in labels)
    assert any("diff" in l.lower() or "Diff" in l for l in labels)
    assert any("Annuler" in l for l in labels)


def test_suggestions_outil_generique_inchange():
    """Les outils hors dev_* gardent le comportement générique."""
    s = suggestions.pour_resultat("agenda_creer_evenement", {}, '{"confirmation_requise": true}',
                                  confirmation=True)
    labels = [b["label"] for b in s]
    assert "✅ Confirmer" in labels
    assert "✖ Annuler" in labels


def test_suggestions_sans_confirmation_vide():
    """Sans confirmation et outil non-dev → liste vide."""
    s = suggestions.pour_resultat("lister_entreprises", {}, '{"entreprises": []}',
                                  confirmation=False)
    assert s == []
```

- [ ] **Étape 2 : Lancer pour vérifier que les nouveaux tests échouent**

```bash
cd /Users/garinat_t/Desktop/Workplace/core
python -m pytest test_bouton_ameliorer.py -k "suggestions" -v
```

Expected : FAIL sur `test_suggestions_dev_demander_avec_confirmation` (et suivants) — les boutons retournés sont `[✅ Confirmer]` / `[✖ Annuler]` génériques.

- [ ] **Étape 3 : Implémenter les boutons contextuels dans `suggestions.py`**

Remplacer le contenu de `core/suggestions.py` par :

```python
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

    `nom`/`args` : l'outil appelé et ses arguments (pour de futures suggestions ciblées) ;
    `resultat` : la chaîne renvoyée par l'outil ; `confirmation` : un gate est-il en attente ?
    Défaut générique : une confirmation en attente → boutons Confirmer / Annuler. Tout autre
    cas → aucun bouton (on n'invente pas d'action que l'utilisateur n'a pas demandée)."""
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
```

- [ ] **Étape 4 : Lancer tous les tests du fichier**

```bash
cd /Users/garinat_t/Desktop/Workplace/core
python -m pytest test_bouton_ameliorer.py -v
```

Expected : PASS (8 tests)

- [ ] **Étape 5 : Non-régression des tests existants**

```bash
cd /Users/garinat_t/Desktop/Workplace/core
python -m pytest test_bouton_ameliorer.py test_dashboard.py test_amelioration_outils.py -v
```

Expected : PASS (tous)

- [ ] **Étape 6 : Commit**

```bash
git add core/suggestions.py core/test_bouton_ameliorer.py
git commit -m "feat S132 : boutons SSE contextuels pour outils dev_* (workflow améliorer)"
```

---

## Définition de DONE

- [ ] Bouton `[🛠️ Améliorer]` visible dans l'onglet Assistant du dashboard (toolbar de droite)
- [ ] Cliquer injecte "Je veux améliorer la solution." dans le chat
- [ ] Le LLM répond par UNE question ouverte (guidé par PROMPT_SYSTEME)
- [ ] `dev_demander` appelé → boutons `[✅ Valider & lancer le chantier]` / `[❌ Annuler le chantier]`
- [ ] `dev_lancer` terminé → boutons `[🚀 Fusionner en prod]` / `[👀 Voir le diff]` / `[❌ Jeter]`
- [ ] `dev_fusionner` gate → boutons `[🚀 Fusionner en prod]` / `[👀 Voir le diff d'abord]` / `[❌ Annuler]`
- [ ] 8 tests verts dans `core/test_bouton_ameliorer.py`
- [ ] Aucune régression sur `test_dashboard.py`
