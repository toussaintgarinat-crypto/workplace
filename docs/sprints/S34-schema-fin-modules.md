# Sprint S34 — Schéma fin des modules ajoutés (incrément vivant)

**Objectif** : à l'application d'un incrément (S32), un module proposé n'arrivait qu'avec
un **schéma CRUD générique** (libellé/statut/date/montant/notes). S34 demande au LLM de
**concevoir le schéma fin** du module — ses champs typés dans le **vocabulaire de
l'entreprise** — au lieu du passe-partout. Repli sur le générique si le Gateway est KO.

**Statut** : ✅ LIVRÉ CODE + **7 tests offline verts** + **PROUVÉ LIVE (dev)** le
2026-06-11. Affine directement ce que S32 venait de livrer.

S'appuie sur : **S32** (application de l'incrément), le **Gateway** (économe, comme la
génération initiale) et le style `prompts.py`.

---

## Ce qui a été construit

| Pièce | Rôle |
|---|---|
| `briques/generateur/prompts.py` | `prompt_schema_module(nom_entreprise, module_nom, raison, audit)` : à partir du nom du module retenu + le glossaire métier de l'audit, demande un JSON `{icone, champs:[{cle,label,type,options}]}`. |
| `briques/generateur/appliquer.py` | `construire_plan_enrichi_llm(plan, proposition, audit)` (async) : pour chaque nouveau module, schéma fin via LLM, **repli générique** si KO. `_normaliser_champs` (types validés, options seulement pour `statut`). `modules_ajoutes[].schema` = `llm` \| `generique`. La règle d'idempotence est **partagée** avec la version synchrone (`_modules_a_ajouter`). |
| `briques/generateur/main.py` | `POST /apps/{id}/revue/appliquer` : pré-check d'idempotence **sans LLM** (s'arrête avant tout appel s'il n'y a rien à ajouter), puis schéma fin via `construire_plan_enrichi_llm`. |
| `briques/generateur/test_appliquer.py` | +2 scénarios (schéma fin LLM, repli générique) → **7 au total**. |

## Décisions d'architecture

- **Best-effort, jamais bloquant.** Le schéma fin est un **bonus** : si le Gateway est
  indisponible ou renvoie un JSON invalide, on retombe **silencieusement** sur le schéma
  CRUD générique (S32). L'application d'un incrément aboutit **toujours** — l'honnêteté
  technique du projet (comme le repli heuristique de S31).
- **Économie d'abord.** Le pré-check d'idempotence tourne **sans** LLM : si la proposition
  n'apporte aucun nouveau module (déjà appliqué, repli heuristique), on s'arrête avant tout
  appel payant.
- **Déterminisme préservé.** `construire_plan_enrichi` (sync, S32) reste **pure et
  testable** ; la couche LLM est une fonction async distincte. Les deux partagent la même
  règle d'idempotence (`_modules_a_ajouter`) — pas de divergence de comportement.
- **Vocabulaire de l'entreprise.** Le prompt réinjecte le `glossaire_metier` de l'audit :
  les champs parlent la langue du client (cohérent avec `prompt_plan_app`).
- **Traçabilité.** `modules_ajoutes[].schema` dit franchement si le schéma vient du LLM ou
  du repli — pas de faux-semblant.

## Tests

```
cd briques/generateur && python3 test_appliquer.py
  ✅ 1-5 (S32, inchangés)
  ✅ 6. schéma fin LLM : champs spécifiques + icône, type statut normalisé
  ✅ 7. repli générique : LLM KO → schéma CRUD, source=generique, aucune exception
  7/7 scénarios OK
```
Non-régression : `test_balayage.py` (4/4), `test_revue.py` (5/5), `test_pont_crm.py`
(6/6). `py_compile` OK. Aucune nouvelle dépendance.

## Preuve LIVE (dev) — 2026-06-11

Vraie stack `donnees` 5500 + Gateway 4001 + `generateur` 5400. App « Cabinet Kiné
Lefèvre » (plan planning + devis), usage planning=6 → `/revue` → `/valider` →
`/appliquer`.

`POST /revue/appliquer` → `modules_ajoutes` avec **`schema: "llm"`**, et les champs
réellement générés sont **spécifiques au métier** (pas le générique) :

| Module ajouté (icône) | Champs dérivés par le LLM |
|---|---|
| **Rapports d'activité** (`bi-file-earmark-text`) | `date_rapport` [date], `seances_planifiees` [nombre], `seances_realisees` [nombre], `taux_reussite` [montant], `commentaires` [texte] |
| **Gestion des ressources** (`bi-gear`) | `ressource_id` [texte], `type_ressource` [texte], `disponibilite` [statut : Disponible/Occupé/En maintenance], `date_allocation` [date], `seance_associee` [texte] |

Conclusion : l'incrément appliqué n'est plus un module passe-partout mais un module **taillé
pour l'entreprise**, avec ses propres champs et statuts — tout en gardant le repli générique
qui garantit que l'application aboutit même sans LLM.

## Dettes / suites

- **Exemples d'amorçage** : le schéma fin n'inclut pas encore d'enregistrements d'exemple
  (le module arrive vide) ; le LLM pourrait en proposer 2-3 réalistes (comme `prompt_plan_app`).
- **Revue humaine du schéma** : les champs LLM sont appliqués directement ; un aperçu
  avant validation serait plus prudent pour des schémas sensibles.
