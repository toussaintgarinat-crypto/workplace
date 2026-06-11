# Sprint S32 — « Appliquer l'incrément » (régénération enrichie post-revue)

**Objectif** : franchir le dernier pas de « l'app vivante ». S31 **mesure** l'usage
consenti et **propose** un incrément ; l'humain le **valide**. S32 **applique** la
proposition validée : les modules proposés sont réinjectés dans le plan livré et l'app est
**régénérée** (même gabarit). L'app livrée cesse d'être un coup unique — du one-shot au
**revenu récurrent** (contrat d'évolution rendu mécanique).

**Statut** : ✅ LIVRÉ CODE + **5 tests offline verts** + **PROUVÉ LIVE (dev)** le
2026-06-11 (vraie stack `donnees` 5500 + Gateway 4001 + `generateur` 5400).

Suite directe de **S31** (cf. `S31-app-vivante.md`, dette « Appliquer l'incrément »).
S'appuie sur le gabarit existant (`generer_html`) et la brique `donnees` (CRUD générique
multi-tenant) : aucun nouveau service, aucun re-audit.

---

## Ce qui a été construit

| Pièce | Rôle |
|---|---|
| `briques/generateur/appliquer.py` | Cœur du sprint. **Fonction pure** `construire_plan_enrichi(plan, proposition)` → `(plan_enrichi, modules_ajoutes)` : ajoute les `modules_proposes` validés comme **vraies entités CRUD** (id slugifié, champs génériques, `description=raison`, `origine="increment"`). **Idempotent** (un id déjà présent n'est pas dupliqué), ne lève jamais. Aucun réseau, aucun secret. |
| `briques/generateur/main.py` | `POST /apps/{id}/revue/appliquer` : refuse si la revue n'est pas `validee` (**409**), construit le plan enrichi, **régénère** l'app (`generer_html`, messagerie préservée via `_oria_cfg_depuis_app`), met à jour `plan` + `html`, trace l'application (`statut: appliquee`, `applique_le`, `modules_ajoutes`). Proposition sans nouveau module → `200 {applique:false}` (on n'invente rien). |
| `briques/generateur/test_appliquer.py` | 5 scénarios offline (fonction pure + branchement réel sur le gabarit). |

## Décisions d'architecture

- **La chaîne complète : proposer ≠ valider ≠ appliquer.** Trois portes distinctes.
  `/revue` propose (S31, aucune génération), `/revue/valider` est la **décision humaine**
  (S31), `/revue/appliquer` (S32) n'agit **que** sur une revue `validee`. On ne régénère
  jamais dans le dos de personne.
- **Idempotent.** Un module dont l'id (slug du nom) existe déjà dans le plan est ignoré :
  ré-appliquer n'introduit pas de doublon. Combiné au passage `validee → appliquee`,
  une revue ne peut pas être appliquée deux fois (la 2ᵉ tentative tombe en 409).
- **Non destructif.** Les modules **dormants** (S31) ne sont **pas supprimés** :
  supprimer une entité détruirait les données déjà saisies. Leur retrait éventuel reste
  une décision humaine séparée, hors de ce sprint. S32 **ajoute** la valeur, il ne retire
  rien.
- **Honnêteté technique.** Si la proposition ne porte aucun module (repli heuristique de
  S31, ou incrément déjà appliqué), `appliquer` n'invente rien : `applique:false` avec la
  raison. Le schéma des nouveaux modules est **générique** (libellé/statut/date/montant/
  notes) : le LLM n'a donné qu'un nom + une raison ; l'affinage fin du schéma par le LLM
  est une amélioration future assumée, pas un faux-semblant.
- **Fidèle au générateur.** Régénération via le **même** `generer_html` que la livraison
  initiale — l'incrément n'est pas un chemin parallèle. La messagerie Oria existante
  (world + salons) est préservée en réinjectant la config navigateur stockée.

## Le flux (bout en bout)

1. `POST /apps/{id}/revue` → mesure consentie + proposition (S31), `statut: propose`.
2. `POST /apps/{id}/revue/valider?decision=valider` → `statut: validee` (humain).
3. `POST /apps/{id}/revue/appliquer` → plan enrichi des modules proposés, **app
   régénérée**, `statut: appliquee`. Avant `validee` : 409. Après `appliquee` : 409.

## Tests

```
cd briques/generateur && python3 test_appliquer.py
  ✅ 1. ajout : module proposé → entité CRUD (champs défaut, origine=increment), plan enrichi
  ✅ 2. idempotence : module déjà présent ignoré, pas de doublon
  ✅ 3. honnêteté : proposition sans module → aucun ajout, plan inchangé
  ✅ 4. robustesse : nom vide / non-dict / plan vide tolérés, aucune exception
  ✅ 5. gabarit : plan enrichi régénéré, le nouveau module apparaît dans l'app
  5/5 scénarios OK
```
Non-régression : `test_revue.py` (5/5, `GATEWAY_KEY` requis à l'import) + `test_pont_crm.py`
(6/6) verts. `py_compile` OK sur `appliquer.py`, `main.py`, `test_appliquer.py`.
Aucune nouvelle dépendance.

## Preuve LIVE (dev) — 2026-06-11

Rejouée contre la **vraie stack** (conteneurs réels, contrats HTTP) : `donnees` (5500) +
Gateway LiteLLM (4001) + `generateur` (5400). Scénario (`/tmp/s32_live.sh`) : app réelle
« Cabinet Kiné Lefèvre » importée (S6), consentement `{planning, devis}`, usage semé
(planning=5, devis=0).

| Vérité prouvée | Observé LIVE |
|---|---|
| Proposition réelle | `POST /revue` → `source=llm`, modules proposés : **« Gestion des paiements »**, **« Rapports d'activité »** |
| **Garde-fou avant validation** | `POST /revue/appliquer` sur `statut: propose` → **HTTP 409** (refus) |
| Application après validation | `valider` → `validee` ; `appliquer` → `applique:true`, **2 modules ajoutés**, plan passe à **5 entités** |
| Plan enrichi persisté | `GET /apps/{id}` → entités `[planning, devis, factures, gestion-des-paiements, rapports-d-activit]`, les 2 nouvelles portent `origine:"increment"` |
| App **réellement régénérée** | `GET /apps/{id}/html` → « Gestion des paiements » présent (4 occurrences) dans le HTML servi |
| **Anti double-application** | ré-`appliquer` (statut désormais `appliquee`) → **HTTP 409** |

Conclusion : la chaîne **mesure → proposition → validation → application régénérée** tourne
de bout en bout sur la vraie stack ; les deux garde-fous (avant validation, anti
double-application) tiennent, et le module proposé par le LLM se retrouve **réellement
utilisable** dans l'app livrée.

## Dettes / suites

- **Schéma fin des modules ajoutés** : aujourd'hui générique (CRUD passe-partout) ; un
  second appel LLM pourrait dériver des champs spécifiques au module proposé.
- **Retrait des modules dormants** : volontairement hors périmètre (destructif) ; un
  futur sprint pourrait l'offrir en option explicite + archivage des données.
- **Versioning de l'app** : l'application écrase `plan`/`html` ; tracer un historique de
  versions (et un retour arrière) serait fidèle au principe SemVer du projet.
- **Déclenchement par l'horloge S29** : revue + application restent manuelles (HTTP) ;
  la revue pourrait être périodique (comme le briefing S30), l'application restant
  **toujours** sous décision humaine.
