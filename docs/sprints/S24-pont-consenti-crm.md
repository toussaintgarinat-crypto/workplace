# Sprint S24 — Pont consenti app livrée → CRM du Forge

> **Statut** : ✅ **CODE LIVRÉ + PROUVÉ OFFLINE (6/6) + PROUVÉ LIVE** (2026-06-08)
> contre la stack réelle (briques `donnees` 5500, `forge` 5700, `generateur` 5400).

## Objectif

Par design (souveraineté), les données d'une app livrée à un client **ne remontent pas**
dans le Forge du cabinet. Ce sprint ajoute un **pont CONSENTI** : si le client **accepte**,
les enregistrements des entités **qu'il choisit** remontent comme prospects dans le CRM du
cabinet ; s'il **refuse** (défaut), **rien ne sort**. Le tout articulé avec le décrochage/
reprise (S6) et révocable (RGPD, S18).

## Décisions actées (arbitrage 2026-06-08)

- **Consentement opt-in** : partage = **Non par défaut** (posture RGPD).
- **Périmètre = liste blanche d'entités** configurable (le client choisit quoi partager).
- **Révocation / décrochage** : le pont **s'arrête** ; la **purge** des données déjà
  remontées se fait **sur demande explicite uniquement** (`purger=true`).
- **Aucun secret ne vit dans le pont** : l'écriture passe par la brique `forge`, qui
  détient déjà l'identité de service du cabinet (`forge-service`) et résout le pôle Sales.

## Ce qui a été livré (code)

### Nouveau module `briques/generateur/pont_crm.py`
- `pousser(app_id, config)` : si `config.actif`, lit la source via le contrat
  `GET {donnees}/apps/{app_id}/export`, filtre par **liste blanche d'entités**, mappe
  chaque enregistrement en lead (heuristique tolérante : `nom/name`, `email/mail`,
  `telephone/tel`, `entreprise/societe`, `notes/...`, repli `nom←entreprise←email`),
  pousse via `POST {forge}/crm`, et **trace la provenance** dans les notes
  (`[pont:{app_id}/{entite}]`). **Idempotent** via un registre local `pont_crm`
  (rec_id → lead_id) dans la base du générateur. Best-effort, ne lève jamais.
- `revoquer(app_id, purger=False)` : arrête le pont ; si `purger`, supprime du CRM les
  leads déjà remontés (`DELETE {forge}/crm/{lead_id}`) et vide le registre. Sans purge,
  les données restent côté cabinet (registre conservé, plus aucune remontée).

### Câblage générateur (`briques/generateur/main.py`)
- **Nouvelle colonne `partage_forge`** sur `apps` (`{actif, entites:[...]}`), migration
  `ALTER TABLE` douce (même motif que `client_onboarding` en S23).
- `PUT /apps/{app_id}/partage-forge` `{actif, entites}` → persiste le consentement et
  **applique immédiatement** la remontée (best-effort) ; renvoie le rapport.
- `POST /apps/{app_id}/partage-forge/revoquer?purger=bool` → désactive + (option) purge.
- `GET /apps/{app_id}` expose `partage_forge` ; `GET /apps/{id}/export` et
  `POST /apps/import` le **transportent** → le consentement voyage avec le dossier portable.

### Articulation cycle de vie (`core/cycle_de_vie.py`)
- Au **décrochage**, `partage_forge` part dans le dossier (via l'export générateur déjà
  appelé) ; la suppression de l'app **arrête naturellement** le pont ; **aucune purge**
  automatique du CRM (décision : explicite seulement).
- À la **reprise**, `POST /apps/import` **ré-arme** le pont si le consentement était actif.

### Adaptateur forge (`briques/forge/main.py`)
- Nouveau proxy `DELETE /crm/{lead_id}` → `DELETE /api/crm/{id}` du core (sert la purge).

## Preuve offline (6/6) — `briques/generateur/test_pont_crm.py`
Briques `donnees` + `forge` simulées par un `httpx.MockTransport`, registre isolé :
1. **consentement Oui** → seules les entités en liste blanche remontent (2 leads, mapping
   + repli `nom←société`, provenance tracée) ;
2. **idempotence** → 2ᵉ remontée : 0 créé, 2 ignorés (registre) ;
3. **consentement Non** → **rien ne sort, aucun appel réseau** (souveraineté) ;
4. **révocation sans purge** → pont arrêté, données **conservées** côté CRM ;
5. **révocation avec purge** → leads **supprimés** du CRM (DELETE), registre vidé ;
6. **Forge injoignable** → best-effort, 0 remonté, erreurs comptées, **aucune exception**.

`python3 -m py_compile` OK sur les 4 fichiers touchés. Aucune nouvelle dépendance (httpx déjà présent).

## Preuve LIVE (end-to-end, stack réelle — 2026-06-08)
Données réelles semées dans `donnees`, app réelle côté générateur :
1. **PUT consentement actif** (`entites:["clients"]`) → `remontee.pousses=2` ; le **vrai
   CRM Forge** (`GET :5700/crm`) montre **2 prospects** (« Camille Live » avec email+tél,
   « ACME LIVE » via repli société + `mail→email`), notes `[pont:pont-live-s24/clients]`.
   L'entité `factures` (hors liste blanche) **n'est pas remontée**.
2. **Idempotence LIVE** : 2ᵉ PUT → `pousses=0, ignores=2`, CRM toujours à 2 (pas de doublon).
3. **Révocation avec purge LIVE** : `supprimes=2`, **CRM revenu à 0**.
   (1ʳᵉ tentative de purge échouée car l'adaptateur forge tournait encore sans la route
   `DELETE` → rebuild de `forge-adapter` → purge OK. Honnêteté technique.)

## Notes d'honnêteté technique
- **Le pont n'invente pas de schéma CRM** : il projette des enregistrements métier
  quelconques sur le modèle `lead` du Forge par heuristique. Un mapping plus fin
  (par type d'entité) reste une évolution.
- **Cloisonnement** : l'écriture passe par l'identité de service unique du cabinet
  (`forge-service`) ; les leads atterrissent dans le pôle Sales résolu par l'adaptateur.
  Le cloisonnement multi-cabinet (un realm/identité par cabinet) reste lié à la
  souveraineté du bundle — cf. `sprint-pont-consenti-crm`, `sprint-compte-client-auto`.
- **Purge = explicite** : conforme à la décision ; à la révocation simple ou au
  décrochage, les données déjà partagées restent côté cabinet jusqu'à demande de purge.

> Voir aussi `sprint-pont-consenti-crm` (mémoire), modules `briques/generateur/pont_crm.py`
> et l'extension de `briques/forge/main.py` (`DELETE /crm/{id}`).
