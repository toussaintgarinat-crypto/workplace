# S182 — « Chacun son agenda » (niveau 2 multi-utilisateur)

Date : 2026-07-19 · Branche : `s182-chacun-son-agenda` (sur `main`)
Mémoire : [[sprint-s182-s183-multiutilisateur-espaces]] · réalise [[smarina-multiuser-live-differe]]

## Objectif

Que **deux comptes Keycloak distincts voient deux agendas distincts** (aujourd'hui ils voient
le MÊME agenda, épinglé `perso`), tout en gardant un **login unique au Cœur** (pas de 2e login
dans l'iframe) et **sans réécrire les ~446 events existants**.

Décisions de kickoff (confirmées par l'utilisateur le 2026-07-19) :
1. **Archi = login unique + identité transmise.** Le Cœur forwarde le `sub` Keycloak de
   l'utilisateur connecté ; l'agenda l'honore. `AGENDA_KEY` reste le gage de confiance (seul le
   Cœur, qui détient la clé, peut emprunter une identité).
2. **Migration = alias.** `perso` reste ; mon compte réel devient `owner` des calendriers `perso`
   via `lier_compte_perso.py` (idempotent, **zéro rewrite** des events). Pas de renommage
   `user_id`.

## Ce qui est DÉJÀ en place (on ne repart pas de zéro)

- Modèle multi-user : `Calendar` → `CalendarMember(user_id, role)` → un user voit les calendriers
  dont il est membre. Invitations : `CalendarInvitation` (S172).
- `contexte_tenant` (S121) : porte l'identité du tour de requête dans un `ContextVar`, lu par les
  clients S2S sortants. `entetes_agenda()` → `{"X-User-Id": <utilisateur ou perso>}`.
- `core/agenda.py` (proxy dashboard) transmet **déjà** `X-User-Id` depuis `contexte_tenant`.
- L'agenda honore **déjà** `X-User-Id` dans la branche `(c)` (service-token historique) de
  `briques/agenda/backend/auth.py`.
- La session web est déjà résolue : `core/auth.sub_session_optionnel(request)` (S171).

## Le maillon manquant (la cause racine)

`contexte_tenant.lire_contexte_tenant` (dépendance posée sur le router agenda) ne lit l'identité
que depuis l'en-tête **`X-User-Id`**. Le dashboard, servi au navigateur, s'authentifie par
**cookie de session** et n'envoie **pas** `X-User-Id` → le contexte retombe sur `perso`. D'où :
tous les comptes voient l'agenda `perso`.

En parallèle, la surface `/service` S168 (branche `(a)` de l'agenda) **fige `AGENDA_USER_ID`** et
**ignore** l'identité forwardée — c'est cette surface qu'empruntent les outils de l'assistant
(`agenda_consulter`, `agenda_lister`, …, via `core/outils_communs._entetes_brique`).

## Changements (3 points, chirurgicaux)

### 1. `core/contexte_tenant.py` — `lire_contexte_tenant` : repli sur le `sub` de session
Quand l'en-tête `X-User-Id` est absent, résoudre l'identité depuis la **session web**
(`auth.sub_session_optionnel(request)`). Priorité : `X-User-Id` (S2S/Telegram déjà résolu) >
`sub` de session > défaut `perso`. Non bloquant (session absente ⇒ `perso`, comportement actuel).
→ Le dashboard porte désormais l'identité du compte connecté sur ses appels agenda.

### 2. `briques/agenda/backend/auth.py` — branche `(a)` : honorer l'identité forwardée
Sous `X-API-Key == AGENDA_KEY` (déjà validé dans cette branche = confiance prouvée), si
`X-User-Id` est présent, l'utiliser comme `sub` **au lieu** de figer `AGENDA_USER_ID`. Repli sur
le pin `AGENDA_USER_ID` quand `X-User-Id` absent (jobs de fond / briefing / proactif sans
session). Sécurité : l'identité n'est honorée **que** derrière la clé de service — un client
externe sans clé ne peut pas atteindre cette branche.

### 3. `core/outils_communs.py` — `_entetes_brique("agenda")` : forwarder `X-User-Id`
Ajouter `X-User-Id` = utilisateur du `contexte_tenant` sur les appels `/service` vers l'agenda,
pour que les **outils de l'assistant** agissent aussi au nom du compte connecté (ciblé sur
`agenda` ; les autres briques ignorent cet en-tête). Combiné au point 2, la surface `/service`
honore alors l'identité.

## Migration (étape LIVE, ops, une seule fois)

Après le premier login de l'utilisateur principal au Cœur, récupérer son `sub` Keycloak et le
lier aux calendriers `perso` :
```
cd briques/agenda/backend && python3 lier_compte_perso.py <mon-sub-keycloak>
```
Idempotent, ajoute `CalendarMember(owner)` — mon compte voit alors les 446 events. **Aucun
rewrite.** Backup DB agenda recommandé avant (prudence).

## Coffre OAuth / TimeTree / Google (risque #3) — décision : rester `perso`

Le coffre `OAuthToken` est keyé sur `perso`. Les **jobs de fond** (briefing, proactif, synchro
périodique) tournent **sans session** → `contexte_tenant` retombe sur `perso` → ils lisent/écrivent
le coffre `perso` et déposent les events dans les calendriers `perso`. Comme mon compte est
`owner` de ces calendriers (migration), **je vois les events synchronisés** sans toucher au coffre.
→ **Pas de rewrite du coffre, pas de régression de synchro.** Un NOUVEL utilisateur qui connecte
SON propre Google le keyera sous SON `sub` (comportement multi-user correct). Seul angle mort
cosmétique : le panneau « connecté ? » du dashboard lu sous mon `sub` réel ne « voit » pas la
connexion `perso` — **hors périmètre MVP**, noté pour S183 (aliasing coffre ou reconnexion 1-clic).

## Flux « 2e personne » (aucun code neuf au-delà des 3 points)

Inscription realm `forge` (ouverte) → login Cœur → contexte porte son `sub` → agenda vide (aucun
`CalendarMember`) → je l'invite sur un calendrier partagé (flux S172 `agenda_inviter`).

## Vérification e2e (LIVE, groupée HP)

1. Login compte A (principal) → voit les 446 events (après migration). Login compte B → agenda **vide**.
2. Compte A crée un calendrier, invite B → B le voit ; A et B ne voient PAS les events perso l'un de l'autre.
3. Sécurité : appel `/service` agenda avec `X-User-Id` mais **sans** `AGENDA_KEY` → n'usurpe rien
   (401 / branche non atteinte).

## Tests unitaires (ICI, avant push)

- `contexte_tenant` : `lire_contexte_tenant` sans `X-User-Id` mais session présente ⇒ contexte = `sub`.
  En-tête `X-User-Id` présent ⇒ prioritaire. Ni l'un ni l'autre ⇒ `perso`.
- agenda `auth.py` : branche `(a)` avec `AGENDA_KEY` + `X-User-Id` ⇒ `sub` = `X-User-Id` ;
  sans `X-User-Id` ⇒ `sub` = `AGENDA_USER_ID` ; mauvaise clé ⇒ 401.

## Risques / garde-fous

- **Ne pas perdre les 446 events** : alias (pas de rewrite) + backup DB avant migration.
- **Frontière de sécurité S2S** : l'identité forwardée n'est honorée que derrière `AGENDA_KEY` /
  service-token — vérifié par test.
- **Coffre OAuth** : reste `perso`, synchro inchangée (cf. section dédiée).
