# Décision — Agenda pilotable par manifest : surface de service + identité pinnée

- **Date** : 2026-07-14
- **Statut** : ✅ Adopté (S168 — T1)
- **Portée** : migration de l'agenda du câblage EN DUR (`core/agenda.py` + 8 outils de
  `core/outils.py`) vers le motif « surface de service » + manifest de S167, appliqué à
  une brique à **vraie base** (Postgres, Alembic, coffre OAuth, SSE).
- **Fichiers liés** : `briques/agenda/backend/auth.py` (dialecte S2S), `config.py`
  (`AGENDA_KEY`, `AGENDA_USER_ID`), `briques/agenda/backend/routers/service.py` (T2),
  `briques/agenda/manifest.json` (capacités, T3), `core/agenda.py` / `core/briefing.py` (T4).

> **But** : consigner *comment* l'assistant pilote l'agenda par le manifest comme les
> autres briques, et *pourquoi* l'identité de calendrier reste **pinnée sur « perso »**
> au lieu de suivre `X-Compte-Id` comme le prévoyait le cadrage initial.

---

## Contexte

L'agenda était la dernière grosse brique fonctionnelle encore pilotée **en dur** :
`core/agenda.py` (~420 lignes) n'est pas un passe-plat mais de la vraie orchestration
(calendrier par défaut, agrégation multi-calendriers + jointure étiquettes, enrichissement,
liens d'invitation) que le dispatcher générique `_appel_dynamique` ne sait pas exprimer.
Suite naturelle de [ADR 2026-07-13](2026-07-13-surface-de-service-role-admin.md) (S167).

Deux verrous empêchaient le manifest :
1. **Auth d'un autre dialecte** — la brique accepte JWT Keycloak OU
   `CALENDAR_SERVICE_TOKEN` (Bearer) + `X-User-Id`. Le Cœur générique envoie
   `X-API-Key` + `X-Compte-Id` (motif S167) → **ne matchait pas**.
2. **Orchestration dans le Cœur** — l'agrégation multi-calendriers vit côté noyau.

## Décision

**Pousser l'orchestration dans la brique** (surface `/service/*`, T2) et **ajouter le
dialecte S2S Workplace** à `get_current_user` (T1) :

- `X-API-Key == AGENDA_KEY` (+ `X-Compte-Id`) → identité de service. Vérifié **en premier**,
  indépendamment d'`AUTH_ENABLED`. Mauvaise clé alors qu'`AGENDA_KEY` est configurée → **401**.
- Les dialectes existants (JWT Keycloak frontend, `CALENDAR_SERVICE_TOKEN` + `X-User-Id`)
  restent intacts (rétro-compat).

## Le point délicat : identité PINNÉE sur « perso » (écart assumé vs cadrage)

Le cadrage S168 disait « `sub = X-Compte-Id` ». **On s'en écarte volontairement**, pour une
raison de correction :

> Toutes les données de l'agenda — calendriers, événements — **et le coffre OAuth/TimeTree**
> (`vault.py::get_token_row(db, user_id, provider)`) sont keyés sur `user_id`, qui vaut
> `"perso"` aujourd'hui. Le Cœur envoie `X-Compte-Id = ADMIN_COMPTE_ID` (défaut `"admin"`).

Mapper naïvement `sub = X-Compte-Id = "admin"` ferait lire l'agenda **vide** et
TimeTree/Google **déconnectés** — violation directe de la contrainte HARD du sprint
(« PRÉSERVER le compte TimeTree connecté, pas de re-login »).

**Retenu** : le dialecte S2S pinne l'utilisateur de calendrier sur `AGENDA_USER_ID`
(défaut `"perso"`). `X-Compte-Id` est **accepté et tracé** (champ `compte_id` du contexte)
comme crochet multi-tenant futur, mais ne repartitionne pas encore les données. Résultat :
bascule **ISO-fonctionnelle, zéro migration de base, coffre intact**.

| Option | Retenue ? | Pourquoi |
|---|---|---|
| **Pinner sur `AGENDA_USER_ID`** (choisi) | ✅ | ISO-fonctionnel, préserve TimeTree/Google, aucune migration |
| `sub = X-Compte-Id` + data-migration `perso→admin` (calendriers + événements + membres + **coffre**) | ❌ | migration lourde sur vraie DB, risque de casser la contrainte TimeTree, gain nul en mono-user |

## Gates — divergence produit ASSUMÉE vs S167

L'agenda crée / déplace / rappelle / crée un agenda partagé en **effet immédiat SANS
confirmation** (réversible, choix produit actuel, cf. `assistant.py`). Donc au manifest
(T3) : `agenda_creer_evenement`, `agenda_deplacer_evenement`, `agenda_definir_rappels`,
`agenda_creer_partage` = **`action:false`**. Restent **gardés** (`action:true`), à l'identique
des anciens outils câblés : `agenda_supprimer_evenement` (destructif) et `agenda_inviter`
(donne un accès à un tiers — action sortante).

## Hors périmètre (restent câblés / spéciaux)

- **OAuth Google** (URL de consentement) / **TimeTree** (login mot de passe) : multi-étapes,
  navigateur, porteurs de secret → laissés câblés (le login par mot de passe via LLM est
  sensible et reste HORS manifest).
- **Pièces jointes** (upload/download multipart) : exclues comme vision/synopsis.
- **SSE** : infra temps réel, pas un outil.

## Contrainte multi-tenant (HARD — avant multi-user)

Tant que l'identité est pinnée sur un utilisateur unique, l'agenda reste mono-user. Avant
d'ouvrir le multi-utilisateur : relier `AGENDA_USER_ID` (ou `X-Compte-Id`) à l'utilisateur
**réellement authentifié** côté Cœur, et migrer les données/coffre vers un modèle par
compte. Dépendance : mémoire `sprint-memoire-auth-multitenant`.

## Runbook — vérifier le dialecte S2S

```bash
# AGENDA_KEY doit être posée côté brique ET côté Cœur (même valeur).
curl -s -H "X-API-Key: $AGENDA_KEY" -H "X-Compte-Id: admin" \
     "http://localhost:8400/service/events?debut=2026-07-14T00:00:00&fin=2026-07-21T00:00:00" | head
# Mauvaise clé → 401 ; agenda toujours peuplé (identité pinnée sur perso).
```

## Références

- Mémoire `sprint-s168-agenda-manifest` (cadrage + découpage T1→T5)
- [ADR 2026-07-13](2026-07-13-surface-de-service-role-admin.md) (motif surface de service, S167)
- `core/outils_communs.py::_entetes_brique` (injection `X-API-Key` + `X-Compte-Id`)
