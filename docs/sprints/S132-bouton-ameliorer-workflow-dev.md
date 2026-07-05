# S132 — Bouton « 🛠️ Améliorer » : workflow dev guidé dans l'assistant

**Date** : 2026-07-02  
**Statut** : ✅ LIVRÉ (2026-07-02 — commits bef2eb1, d24a8e0, 4ae66ac)

## Problème

Pour déclencher le workflow d'amélioration via la brique dev (5955), l'utilisateur doit
connaître des phrases magiques (`"améliore la solution : ..."`, `"valide et lance"`,
`"fusionne sur git"`). C'est opaque et peu intuitif.

## Objectif

Ajouter dans l'interface de l'assistant un bouton fixe **[🛠️ Améliorer]** qui guide
l'utilisateur à travers le cycle complet :

```
[🛠️ Améliorer]  (toujours visible dans le dashboard)
       ↓
Assistant demande : "Décris ce que tu veux ajouter ou changer"
       ↓
Échange libre (l'utilisateur précise)
       ↓
Brique dev 5955 planifie + code + tests
       ↓
Boutons SSE (S76) : [✅ Valider & tester]   [❌ Annuler]
       ↓
Tests verts
       ↓
Boutons SSE : [🚀 Pousser en prod]   [👀 Voir le diff]
```

## Tâches

### P1 — Bouton fixe dans le dashboard (Cœur)

**Fichier** : `core/templates/` ou fichier HTML du dashboard  
**Quoi** : Un bouton `[🛠️ Améliorer]` toujours visible (pas un bouton SSE dynamique),
qui injecte dans le chat le message :
```
Je veux améliorer la solution.
```
Le prompt système du Cœur reconnaît cette phrase et répond par une question ouverte
("Décris ce que tu veux ajouter ou changer") avant d'appeler `dev_demander`.

### P2 — Signal dans le prompt système du Cœur

**Fichier** : `core/prompts/` (fichier addendum ou base)  
**Quoi** : Ajouter une instruction :

> Quand l'utilisateur dit « Je veux améliorer la solution » ou clique [🛠️ Améliorer] :
> 1. Demande-lui de décrire la fonctionnalité souhaitée (une question courte).
> 2. Une fois qu'il a décrit, appelle `dev_demander` avec sa description.
> 3. Après le retour de la brique dev, propose les boutons SSE :
>    `[✅ Valider & tester]` → message injecté `"valide et lance les tests"`
>    `[❌ Annuler]` → message injecté `"annule le chantier dev"`
> 4. Si les tests sont verts, propose :
>    `[🚀 Pousser en prod]` → message injecté `"fusionne sur git et redémarre sur le HP"`
>    `[👀 Voir le diff]` → message injecté `"montre-moi le diff"`

### P3 — Boutons SSE après chaque étape clé

**Mécanisme existant** : S76 — événement SSE `actions` dans `/assistant/chat`  
**Quoi** : Le Cœur émet les boutons automatiquement après les réponses de `dev_demander`
et `dev_lancer` (déjà câblé via le mécanisme S76, il suffit que le LLM les génère).

### P4 — Tests

- `test_bouton_ameliorer.py` dans `core/` :
  - Le dashboard HTML contient le bouton `🛠️ Améliorer`
  - Le message injecté déclenche la bonne séquence (mock `dev_demander`)
  - Les boutons SSE `[✅ Valider & tester]` et `[🚀 Pousser en prod]` sont émis

## Mots clés reconnus (mapping → outils)

| Ce que dit / clique l'utilisateur | Outil appelé |
|-----------------------------------|--------------|
| *"Je veux améliorer la solution"* | → question ouverte de l'assistant |
| *"[description de la feature]"* | → `dev_demander(description=...)` |
| *"valide et lance les tests"* | → `dev_plan_valider(confirme=true)` |
| *"annule le chantier dev"* | → `dev_jeter(confirme=true)` |
| *"fusionne sur git et redémarre"* | → `dev_fusionner` + outil HP |
| *"montre-moi le diff"* | → `dev_diff()` |

## Fichiers à toucher

```
core/
  templates/ ou static/     ← bouton HTML [🛠️ Améliorer]
  prompts/addendum*.txt     ← instruction workflow amélioration
  test_bouton_ameliorer.py  ← nouveaux tests P4
```

## Dépendances

- Brique dev 5955 LIVE sur le HP (S92, CODE-COMPLET, LIVE DIFFÉRÉ)
- Mécanisme boutons SSE S76 opérationnel
- Outils `dev_demander`, `dev_plan_valider`, `dev_fusionner`, `dev_jeter`, `dev_diff`
  déjà au manifest de la brique 5955

## Définition de DONE

- [ ] Bouton `[🛠️ Améliorer]` visible dans le dashboard
- [ ] Cliquer → l'assistant pose une question ouverte
- [ ] Répondre → `dev_demander` appelé, plan affiché
- [ ] Boutons `[✅ Valider]` / `[❌ Annuler]` apparus automatiquement
- [ ] `[✅ Valider]` → tests lancés, résultat affiché
- [ ] `[🚀 Pousser]` → commit + push + redémarrage HP
- [ ] Tests P4 verts
