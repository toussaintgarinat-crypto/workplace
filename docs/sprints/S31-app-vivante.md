# Sprint S31 — « L'app vivante » (re-audit post-livraison)

**Objectif** : une app livrée cesse d'être un coup unique. À intervalles, le générateur
**mesure son usage réel** (combien d'enregistrements chaque module reçoit depuis la
livraison), **re-audite** l'entreprise (usage + audit initial + nouveaux documents) et
**propose un incrément** — « le module Planning est utilisé 40×, Devis jamais ; le
Pareto a changé ; je propose X ». La proposition est **toujours à valider avant toute
génération** : c'est un contrat d'évolution, pas une régénération sauvage. Le critère
« ça rapproche d'un euro ? » : du one-shot au **revenu récurrent**.

**Statut** : ✅ LIVRÉ CODE + **5 tests offline verts** + **PROUVÉ LIVE (dev)** le 2026-06-11
(vraie stack `donnees` 5500 + Gateway 4001 + `generateur` 5400 — voir « Preuve LIVE » en bas).

S'appuie sur : **pont consenti S24** (la mesure ne lit que ce que le client a accepté de
partager), **cycle de vie S6** (la revue voyage dans le dossier portable), **audit S7**
(le re-audit réutilise l'audit initial comme référence).

---

## Ce qui a été construit

| Pièce | Rôle |
|---|---|
| `briques/generateur/revue.py` | Cœur du sprint. `mesurer_usage()` lit l'export de la brique `donnees`, compte les enregistrements **par module consenti**, en tire un **Pareto trié** et la liste des **modules dormants** (0 enr.). `proposer_increment()` re-audite via le LLM (économe Gateway) ; **repli heuristique déterministe** si le LLM est indisponible. |
| `briques/generateur/prompts.py` | `prompt_revue()` : usage réel + Pareto initial + must-have + nouveaux documents → JSON `{resume, pareto_commentaire, modules_proposes, modules_sous_utilises}`. |
| `briques/generateur/main.py` | Colonne `revue` (migration douce). `POST /apps/{id}/revue` (mesure + propose, **ne génère rien**), `GET /apps/{id}/revue` (dernière revue), `POST /apps/{id}/revue/valider?decision=valider\|rejeter` (le **garde-fou** humain). `GET /apps/{id}/export` transporte la revue (dossier portable S6). |
| `briques/generateur/test_revue.py` | 5 scénarios offline (brique `donnees` + LLM simulés). |

## Décisions d'architecture

- **Souveraineté d'abord.** La mesure d'usage ne regarde **que les entités que le client
  a consenti à partager** (liste blanche du pont S24). Partage désactivé → **aucune
  mesure, aucun appel réseau**. Une entité hors liste blanche reste **invisible** (elle
  apparaît dans `non_consenties`, jamais dans les comptes). On ne re-audite pas dans le
  dos du client.
- **Proposer ≠ générer.** `/revue` produit une proposition au statut `propose` et
  **n'engage aucune génération**. Rien ne part en production sans `POST /revue/valider`.
  C'est le « à valider avant toute génération » du backlog, rendu mécanique.
- **Honnêteté technique du repli.** Si le Gateway est injoignable, `proposer_increment`
  **n'invente pas de modules** : il retombe sur une heuristique déterministe qui livre le
  **signal factuel** (Pareto réel, modules dormants à confirmer/retirer) et le dit
  franchement (`source: "heuristique"`). La partie créative (nouveaux modules) reste au
  LLM (`source: "llm"`).
- **Fidèle au générateur.** `revue.py` est self-contained comme `pont_crm.py` (lecture
  via le contrat HTTP `donnees`, écriture du résultat dans la base `apps`), réutilise le
  `gateway.appeler_llm` existant et le style `prompts.py`. Aucun secret dans le module.
- **Best-effort.** `mesurer_usage` ne lève jamais ; `donnees` injoignable → mesure vide
  mais `consenti: true` conservé, message d'erreur tracé.

## Le flux (bout en bout)

1. `POST /apps/{id}/revue` → lit le `plan` + le consentement `partage_forge`, **mesure
   l'usage consenti** (Pareto, dormants), recharge l'audit initial (S7), **propose un
   incrément**. Persisté `statut: propose`. Aucune génération.
2. Le cabinet lit `GET /apps/{id}/revue`, juge la proposition.
3. `POST /apps/{id}/revue/valider?decision=valider` → `statut: validee` (l'incrément peut
   être lancé) ou `rejeter` → `statut: rejetee`. Sans revue préalable : 400.

## Tests

```
cd briques/generateur && GATEWAY_KEY=… python3 test_revue.py
  ✅ 1. mesure consentie : Pareto trié, devis dormant, factures invisible (souveraineté)
  ✅ 2. consentement Non : aucune mesure, aucun appel réseau (souveraineté)
  ✅ 3. donnees injoignable : best-effort, mesure vide, aucune exception
  ✅ 4. proposition LLM : source=llm, modules normalisés ({nom, raison})
  ✅ 5. repli heuristique : source=heuristique, Devis dormant signalé
  5/5 scénarios OK
```
Non-régression : `test_pont_crm.py` (6/6) vert. `py_compile` OK sur `revue.py`,
`prompts.py`, `main.py`. Aucune nouvelle dépendance.

## Dettes / suites

- **Appliquer l'incrément** : valider met le statut à `validee` ; la **régénération
  enrichie** (réinjecter les modules proposés dans un nouveau plan puis `/generer`) reste
  le pas suivant — volontairement séparé pour garder l'humain à la manœuvre.
- **Usage = nombre d'enregistrements**, proxy honnête de l'activité d'un module ; une
  vraie télémétrie d'ouverture/clic (« utilisé 40×/**jour** ») serait plus fine et
  demanderait d'instrumenter l'app livrée.
- **Déclenchement par l'horloge S29** : la revue est manuelle (HTTP) ; la déclarer comme
  tâche périodique dans le manifest du générateur la rendrait automatique, comme le
  briefing S30.
- ~~**Preuve LIVE** : à rejouer contre la vraie stack~~ → **fait le 2026-06-11** (section ci-dessous).

## Preuve LIVE (dev) — 2026-06-11

Rejouée contre la **vraie stack** (conteneurs réels) : `donnees` (5500) + Gateway LiteLLM
(4001, clé OpenRouter) + `generateur` (5400). Aucun mock — tout passe par les contrats HTTP.

**Scénario** (`/tmp/s31_live.sh`) : une app réelle « Cabinet Kiné Lefèvre » importée (S6)
avec plan à **3 modules** (`planning`, `devis`, `factures`) et un **consentement actif**
(liste blanche S24 = `{planning, devis}`, **`factures` volontairement hors liste**). Usage
réel semé dans la brique `donnees` via son contrat HTTP : `planning`=5, `devis`=0,
`factures`=3.

| Vérité prouvée | Observé LIVE |
|---|---|
| Mesure consentie contre la **vraie** brique | `POST /revue` → `planning`=5 (100 %), `devis`=0, `total=5` |
| **Souveraineté** (le cœur du sprint) | `donnees` contient bien **3 `factures`** (vérifié via `/resume`), mais la revue en compte **0** : `factures` apparaît dans `non_consenties`, **jamais** dans les comptes. La mesure n'a pas touché les données non consenties. |
| Module **dormant** détecté | `modules_dormants: ["devis"]` |
| Proposition par le LLM (économe) | `proposition.source = "llm"` — vraie synthèse rédigée par le Gateway (modèle gratuit, coût ~0 $), pas le repli heuristique |
| **Proposer ≠ générer** | `/revue` → `statut: propose` (aucune génération) ; `POST /revue/valider?decision=valider` → `statut: validee` + `decide_le` horodaté |
| Persistance | `GET /revue` relit la revue (colonne `revue`, migration douce) |

Conclusion : la chaîne **mesure consentie → re-audit → proposition à valider** tourne de
bout en bout sur la vraie stack, et la garantie de souveraineté (ne mesurer que le
consenti) tient face à des données non consenties réellement présentes dans la source.
