# Sprint S36 — Forge : course de provisioning (S19) + propagation d'identité (S20)

**Objectif** : solder deux dettes du core Forge, glissées dans le premier sprint qui le
retouche.
1. **Bug de concurrence (S19)** : au tout premier login, deux requêtes concurrentes du même
   utilisateur provisionnaient deux fois → violation d'unicité → 500 « auto-réparé » au
   retry. On rend le provisioning **idempotent sous course**.
2. **Dette d'identité (S20)** : l'adaptateur s'authentifie au core avec un **token de
   service**, si bien que l'identité réelle de l'utilisateur ne traverse jamais. On rend
   l'adaptateur **capable de propager** le token utilisateur quand il est fourni.

**Statut** : ✅ LIVRÉ CODE + **tests verts** le 2026-06-11 — course prouvée dans l'image
**réelle du core** (174 passés, dont 3 nouveaux S36 ; 0 régression), propagation prouvée
offline (3/3) contre le vrai adaptateur. Reste LIVE pour S20 : rejouer avec un **2ᵉ
utilisateur réel** (le câblage côté Cœur — envoyer `X-Forge-User-Token` — et la preuve
multi-tenant restent gated, cf. dettes).

---

## 1. Course de provisioning (S19)

`_provision_user` (et `_ensure_personal_org`) faisaient un *select-puis-insert* : deux
1ers logins simultanés passaient tous deux le `select` (aucun user), puis inséraient →
`IntegrityError` sur `users_keycloak_sub_unique` / `users_email_unique` → 500.

**Correctif** (`briques/forge/forge/core/app/auth.py`) : l'insert est isolé dans un
**savepoint** (`session.begin_nested()`). Si l'unicité saute, c'est que la transaction
concurrente a gagné → on **récupère l'utilisateur déjà créé** (re-select par `sub` puis
`email`) au lieu de propager le 500. Même protection pour l'org personnelle (collision de
slug / org déjà créée). Si l'`IntegrityError` n'est pas résolue par un re-select (autre
cause d'unicité), on **ne la masque pas**.

## 2. Propagation d'identité (S20)

L'adaptateur (`briques/forge/main.py`) présentait **toujours** le token de service
(choix S16/S17). **Correctif rétrocompatible** : un middleware capte un token utilisateur
optionnel dans l'en-tête `X-Forge-User-Token` (préfixe `Bearer` toléré) et le range dans
un `ContextVar` ; `_appel_protege` **propage ce token** s'il est présent — le core
provisionne et scope alors par l'**utilisateur réel** — sinon **repli** sur le token de
service (flux S17/S24 **inchangés**). Via le `ContextVar`, **aucune signature de route à
modifier**, et `_resoudre_pole_crm` (qui rappelle `_appel_protege`) en bénéficie aussi.

## Décisions d'architecture

- **Idempotent plutôt que verrou.** Le savepoint + re-select résout la course sans
  sérialiser les logins ni ajouter de verrou applicatif — on laisse la base arbitrer
  (sa contrainte d'unicité) et on s'aligne sur le gagnant.
- **Ne pas masquer les vraies erreurs.** Une `IntegrityError` qu'aucun re-select
  n'explique est re-levée : on corrige la course, pas on avale les bugs.
- **Propagation opt-in, zéro régression.** Le token de service reste le défaut ; la
  propagation ne s'active que si l'appelant fournit explicitement `X-Forge-User-Token`.
  Les flux prouvés LIVE en S17/S24 (service) ne changent pas.
- **En-tête dédié, pas `Authorization`.** Un en-tête distinct rend la propagation
  explicite et évite toute confusion avec l'auth de service de l'adaptateur.

## Tests

```
# Core Forge (image réelle, asyncpg présent)
docker exec forge-forge-1 pytest tests/ -q
  → 174 passed, 2 skipped (live-gated)   [dont test_s36_provision_race.py : 3/3]
  ✅ course → récupère le gagnant (pas de 500)
  ✅ IntegrityError non résolue → re-levée (pas masquée)
  ✅ chemin nominal → un seul insert

# Adaptateur (offline, vrai main.py)
python3 test_propagation_identite.py
  ✅ 1. sans token utilisateur → token de service (S17 inchangé)
  ✅ 2. token utilisateur présent → propagé, service non sollicité
  ✅ 3. middleware : X-Forge-User-Token capté (Bearer toléré), reset après requête
  3/3 scénarios OK
```
Non-régression : `test_auth.py` + toute la suite core verte (le seul échec,
`test_parity_harness`, est dû à `respx` absent de l'image — sans rapport avec S36).

## Dettes / suites

- **Preuve LIVE multi-tenant (S20)** : reste gated (`FORGE_LIVE_URL` + 2 tokens d'orgs
  réelles, cf. `test_s18_isolation`). À rejouer **avant le 2ᵉ utilisateur Workplace réel**.
- **Câblage côté Cœur** : l'assistant/Cœur doit **émettre** `X-Forge-User-Token` avec le
  JWT de l'utilisateur quand il en a un (aujourd'hui il appelle en « perso »/service). La
  capacité existe désormais côté adaptateur ; l'émission reste à brancher.
- **Org personnelle en double** : le savepoint évite le 500 sur collision de slug ; un
  index d'unicité `(owner_id, plan='personal')` interdirait formellement deux orgs perso.
