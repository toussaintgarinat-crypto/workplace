# Décision — Back-office pilotable à la voix : « surface de service » + rôle admin en base

- **Date** : 2026-07-13
- **Statut** : ✅ Adopté (S167 — T1)
- **Portée** : câblage Cœur → briques à tenant (restaurant en tête ; studio/personnages en clé fusionnée) ; sécurité de la surface `/service/*`
- **Fichiers liés** : `core/outils_communs.py` (`_entetes_brique`), `briques/restaurant/auth.py` (`service_garde`), `briques/restaurant/stockage.py` (`role`, `ensure_admin`)

> **But de ce document** : consigner *comment* l'assistant pilote tout le back-office
> des grosses briques par la voix, *pourquoi* l'accès total est un privilège lié à
> l'identité admin (et non à la simple possession d'une clé), et **quand** ce modèle
> devra être durci avant le multi-utilisateur.

---

## En bref (l'état cible)

- Une action back-office devient pilotable quand : (1) un endpoint est joignable avec la
  **clé de service `{BRIQUE}_KEY`** (le Cœur l'injecte en `X-API-Key` via
  `_entetes_brique`), et (2) elle est déclarée comme `capacite` au manifest. Côté Cœur :
  **rien à changer** (`catalogue.collecter_capacites` + `_appel_dynamique` + gate de
  confirmation `action:true`).
- L'accès total n'est plus donné par la clé seule : il est un **privilège du rôle
  `admin`**, lu **en base** dans chaque brique. Un tenant normal reste **cloisonné à ses
  ressources**. Le Cœur transmet l'identité de l'appelant via `X-Compte-Id`.

## Contexte & objectif

L'assistant savait déjà *lire* et *commander* (S103, S166), mais pas gérer le back-office :
créer un restaurant, générer une carte, passer une commande en cuisine, activer le rail
de paiement, créer un tome de studio, caster des personnages. But de S167 : **tout gérer
par conversation**.

Deux styles d'intégration préexistent et coexistent :

| Style | Briques | Auth | Ce qu'il faut faire |
|---|---|---|---|
| **`/service/*` séparé** | restaurant | back-office gardé par login utilisateur (`Depends(compte_actuel)`) ; surface `/service/*` distincte gardée par `service_ok` (`RESTAURANT_KEY`, 503 si clé absente) | **écrire** les jumeaux `/service` (T2) |
| **clé fusionnée** | studio, personnages | `STUDIO_KEY` simplement ajoutée aux `API_KEYS` acceptées sur les endpoints normaux | **déclarer** la capacité au manifest (endpoint + auth déjà là) |

**Cible privilégiée** : le style `/service/*` séparé (meilleure isolation, prépare le
multi-tenant). On ne réécrit pas studio/personnages qui marchent en clé fusionnée — on
étend leur couverture par manifest.

## Le problème de sécurité résolu ici

Avant décision, `/service/*` était gardé par une **clé de service unique** : quiconque la
détient pouvait viser n'importe quel `restaurant_id` (`_compte_de_service` dérive le
propriétaire depuis le resto ciblé). Acceptable en mono-utilisateur, **inacceptable en
multi-utilisateur** (création de resto + onboarding financier ouverts à tous).

## Décision

**Modèle à deux niveaux, décidé par le rôle du compte lu en base :**

1. **Champ `role` sur la table `comptes`** de chaque brique à tenant
   (`role TEXT DEFAULT 'tenant'`, migration douce). Extensible à plusieurs admins.
2. **Le Cœur transmet l'identité de l'appelant** : `_entetes_brique` ajoute
   `X-Compte-Id` (= `ADMIN_COMPTE_ID`, défaut `admin`) à côté de `X-API-Key`.
   Aujourd'hui (mono-user) c'est toujours l'admin ; demain (multi-user) ce sera l'id de
   l'utilisateur courant. **Même fil, même logique côté brique → zéro réécriture.**
3. **Amorçage déterministe** : chaque brique garantit au boot un compte `role=admin`
   d'id fixe (`ADMIN_COMPTE_ID`, défaut `admin`, email `ADMIN_EMAIL`) via un
   `INSERT … ON CONFLICT DO NOTHING`. Les deux côtés calculent le même id **sans jamais
   se copier d'identifiant** → aucun setup manuel.
4. **`service_garde`** (dépendance brique) remplace `service_ok` sur `/service/*` : vérifie
   la clé de service **puis** résout `X-Compte-Id → role → périmètre`, et renvoie un
   contexte `{compte_id, role, est_admin}`.

**Comportement de `/service/*` :**

| `X-Compte-Id` reçu | Décision |
|---|---|
| compte `role=admin` | **bypass** — peut viser n'importe quel `restaurant_id` (comportement historique) |
| compte `role=tenant` | restreint à ses ressources (`_possede`) ; toute création scopée à lui |
| absent | **repli déprécié** : traité admin + log d'alerte pendant le rollout, puis fail-closed |

Toute écriture reste `action:true` (gate de confirmation du Cœur) ; le destructif
(supprimer table/plat, annuler commande, supprimer distribution) = gate ferme.

## Alternatives considérées

| Identité de l'appelant | Retenu ? | Pourquoi |
|---|---|---|
| **`X-Compte-Id` + amorçage déterministe** (choisi) | ✅ | ferme réellement le trou, mono→multi sans refonte, aucun id à copier |
| Clé de service = admin implicite | ⚠️ repli seulement | ne ferme pas le trou, documente une intention ; gardé comme filet de transition |
| `ADMIN_COMPTE_ID` configuré à la main | ❌ | fragile : ids à copier par brique, compte admin à créer manuellement |

## Contrainte multi-tenant (HARD — bloquante avant multi-user)

Tant que le repli « absent = admin » existe, une clé de service valide sans `X-Compte-Id`
reste god-mode. **Avant d'ouvrir le multi-utilisateur** (l'un suffit) :
1. **retirer le repli** (`X-Compte-Id` obligatoire, fail-closed si absent) ;
2. **scoper `role`/tenant** sur les autres briques à données propres ;
3. relier `X-Compte-Id` à l'utilisateur **réellement authentifié** côté Cœur (aujourd'hui
   constant = admin). Dépendance : voir mémoire `sprint-memoire-auth-multitenant`.

## Runbooks

### A. Vérifier que l'admin existe et pilote (restaurant)
```bash
# La clé de service doit être posée, sinon /service = 503 (fail-closed).
curl -s -H "X-API-Key: $RESTAURANT_KEY" -H "X-Compte-Id: admin" \
     http://localhost:6010/service/restaurants | head
```

### B. Promouvoir un compte existant en admin (multi-admin)
```sql
UPDATE comptes SET role='admin' WHERE email='qqn@exemple.fr';
```

### C. Retirer le repli avant multi-user (durcissement)
Dans `service_garde` : si `X-Compte-Id` absent → `raise HTTPException(401)` au lieu de
traiter admin. Retirer aussi le log de dépréciation.

## Limites connues

- `role` vit **par brique** (pas d'identité centrale : chaque brique a sa table
  `comptes` SQLite). Un même humain = un compte par brique. Acceptable mono-user ;
  l'unification est l'épopée multi-tenant.
- studio/personnages n'ont pas (encore) de modèle tenant : le rôle admin n'y change rien
  aujourd'hui (espace unique). Le modèle ne s'applique qu'aux briques à propriété de
  données (restaurant).

## Références

- Mémoire `sprint-s167-backoffice-pilotable-voix` (cadrage + découpage T1→T5)
- `core/outils_communs.py::_entetes_brique` (injection `X-API-Key` + `X-Compte-Id`)
- `briques/restaurant/main.py` (surface `/service/*`, `_compte_de_service`)
