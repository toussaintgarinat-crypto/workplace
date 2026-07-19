# S183 — Audit d'isolation « chacun son espace » + fixes évidents

Date : 2026-07-19 · Mémoire : [[sprint-s182-s183-multiutilisateur-espaces]]
Suite de [[sprint-s181-acces-distant-cercle-prive]] (comptes du cercle privé) et
[[sprint-s182-s183-multiutilisateur-espaces]] (agenda multi-user, mergé main 2026-07-19).

## Objectif

L'agenda a été rendu multi-user en S182 : chaque compte Keycloak voit ses propres événements.
S183 vérifie si les **autres briques** ont le même trou que l'agenda avait avant S182 (des
comptes distincts qui, sans le savoir, partagent la même donnée), et corrige ce qui peut l'être
sans risque dans ce sprint.

Le Workplace a **deux notions de tenant distinctes** aujourd'hui, et l'audit couvre les deux :
1. **Cercle privé par personne** — comptes Keycloak (toi + proches), identité transmise en
   `X-User-Id` (motif S182). C'est le prolongement direct de S181/S182.
2. **Bundle client business** — chaque client livré via l'Usine/Forge a son
   `ADMIN_COMPTE_ID`/`X-Compte-Id` propre (épopée bundles solutions par client, S95→S99). Modèle
   différent, déjà en place, mais pas audité pour des trous.

## Méthodologie

1. **Balayage délégué** : un agent Explore lit chaque brique sous `briques/*/` (son `main.py`,
   son `auth.py`/équivalent, son manifest) et relève, pour chacune : quel(s) en-tête(s)
   d'identité elle honore (`X-API-Key`, `X-Compte-Id`, `X-User-Id`, aucun), si un modèle
   multi-tenant existe et est testé (ex. `briques/mail/test_isolation.py`), et comment le Cœur
   la pilote via `core/outils_communs._entetes_brique` (quelle portée d'en-têtes forwardée).
   Aucun fix pendant le balayage — collecte de faits uniquement.
2. **Classification** (faite par moi, pas par l'agent) : chaque brique reçoit un verdict :
   - **Isolée par personne** — comme l'agenda post-S182.
   - **Isolée par bundle-client** — `X-Compte-Id` suffisant et cohérent avec son usage (briques
     business type restaurant/paiements/telephonie, destinées aux clients de l'Usine, pas au
     cercle privé).
   - **Partagée à raison** — pas de notion de « par personne » pertinente (ex. brique
     d'administration/pilotage du Workplace lui-même).
   - **Trou** — accessible sans distinction d'appelant alors qu'elle porte des données qui
     devraient être cloisonnées (par personne ou par bundle).
3. **Décision fix-maintenant vs report**, par trou identifié :
   - **Fix maintenant** si : le motif est déjà établi ailleurs (copier `_entetes_brique` /
     le repli session de `contexte_tenant`), aucune migration de données nécessaire, aucun
     changement de comportement visible pour l'usage actuel (mono-user de fait aujourd'hui sur
     la brique concernée).
   - **Report** sinon (typiquement : la brique a déjà son propre modèle de tenant différent,
     comme `mail` avec ses clés API par boîte — l'aligner sur le motif X-User-Id est un
     changement de comportement, pas un trou à boucher).

## Livrables

- **Rapport d'audit** : `docs/rapport-s183-audit-isolation.md` — tableau brique → verdict →
  en-têtes honorés aujourd'hui → action (fixé dans ce sprint / reporté + raison).
- **Fixes appliqués** : chaque fix trivial a son commit, ses tests (suivant le motif des tests
  d'isolation existants, ex. `briques/agenda/backend/tests/test_auth_service.py`,
  `briques/mail/test_isolation.py`), et `make test-core` (+ suite de la brique touchée) au vert.
- **Mémoire mise à jour** : liste priorisée des sprints de suite (mail en tête si l'audit
  confirme que c'est le candidat mûr le plus impactant — sinon le candidat que l'audit désigne).

## Hors périmètre

- Réécrire le modèle de tenant de `mail` (par clé API → par session Keycloak) : changement de
  comportement, pas un « trou » — sprint dédié si l'audit le confirme prioritaire.
- Auditer le contenu/la sécurité de chaque brique au-delà de la question d'isolation (pas un
  audit de sécurité général — cf. skill `review-infra` pour ça).
- Toute brique qui n'a **aucune** donnée par utilisateur/tenant (stateless, ou données
  globales par design) — pas de verdict "trou" à leur appliquer.

## Risques

- Faux positif : classer « trou » une brique qui est en réalité « partagée à raison » —
  mitigé par le fait que la classification passe par moi (pas l'agent) avec le contexte complet
  du Workplace.
- Fix trop hâtif qui casse un usage existant non testé — mitigé par le critère strict
  fix-maintenant (motif déjà établi + zéro migration + zéro changement de comportement) et par
  `make test-core` après chaque fix.
