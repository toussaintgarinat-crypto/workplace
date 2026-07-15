# S173 — Routage S2S par utilisateur réel

Sous-sprint 3/3 (dernier) de [[epopee-identite-multiutilisateur-coeur]]
(`docs/sprints/S171-S173-epopee-identite-multiutilisateur-coeur.md`), préalable bloquant
du roadmap agenda `docs/sprints/S174-S180-roadmap-agenda-best-in-class.md`.

## But

Faire en sorte que lorsque l'assistant (web ou Telegram) crée un événement/rappel
d'agenda, il sache **pour qui**, au lieu d'écrire systématiquement `"perso"`. Le cadrage
initial de l'épopée visait « remplacer le pinning en dur (`AGENDA_USER_ID="perso"`,
`ADMIN_COMPTE_ID="admin"`) ». En creusant, ce périmètre se réduit beaucoup : S172 a déjà
réglé le cas du dashboard/agenda direct (accès via `/app`, vraie identité Keycloak
`calendar-app`) ; il ne reste que le chemin **assistant → agenda**.

## Découverte de contexte — la plomberie existe déjà presque entièrement

- **`core/contexte_tenant.py`** (S121) porte déjà l'identité de l'appelant via des
  `ContextVar`s. `core/routers/assistant.py` (ligne ~95-100) accepte déjà un champ
  optionnel `corps.utilisateur` et appelle déjà
  `contexte_tenant.definir_contexte(utilisateur=utilisateur)` s'il est fourni.
  `core/agenda.py::_entetes()` lit déjà cette identité pour construire `X-User-Id` à
  chaque appel S2S vers la brique agenda.
- **Telegram est déjà câblé de bout en bout.** `briques/connexion/correspondance.py`
  résout déjà « qui écrit » (`resoudre(reseau, id_externe, nom)`) vers un `utilisateur`
  Workplace, avec consentement (code de liaison, `POST /correspondances` pour lier un
  interlocuteur côté admin). `briques/connexion/pont.py::traiter()` appelle déjà
  `client_assistant.converser(..., utilisateur=corr.get("utilisateur"))`, qui atteint
  `/assistant/chat`. **Aucun nouveau code n'est nécessaire pour Telegram** — le seul
  travail restant est opérationnel : lier chaque interlocuteur à son **vrai sub
  Keycloak `calendar-app`** plutôt qu'à une étiquette libre.
- **Ce qui manque réellement** : le chat web du dashboard. `assistant.router` n'exige
  aucune session (accessible aussi bien depuis Telegram, un script, ou le navigateur) et
  ne lit jamais le cookie de session posé par S171 — donc même connecté au dashboard, un
  message envoyé depuis le chat web tombe sur le défaut `"perso"`.
- **Simplification clé** : le `sub` Keycloak est **le même compte** qu'on se connecte via
  `assistant-app` (dashboard, S171) ou `calendar-app` (agenda, S172) — deux clients du
  même realm `forge`, un seul utilisateur Keycloak. Le pont `lier_compte_perso.py` (S172)
  et la nouvelle dépendance de ce sprint pointent donc naturellement vers la même
  identité, sans table de correspondance à construire.
- **Risque croisé découvert avec S172** : `core/agenda.py::_entetes()` n'envoie un
  `Authorization: Bearer` que si `CALENDAR_SERVICE_TOKEN` est configuré. Or S172 a déjà
  noté qu'il faut passer `AUTH_ENABLED=true` côté agenda pour que `/app` authentifie
  réellement (`briques/agenda/backend/README.md`). Une fois ce flag activé,
  `get_current_user` exigera un token pour toute requête — si `CALENDAR_SERVICE_TOKEN`
  n'est pas *aussi* configuré à ce moment-là, **le chemin assistant/Telegram vers
  l'agenda casse silencieusement (401)**.

## Décisions actées avec l'utilisateur

- **Unification d'identité** : un seul espace d'identité (le sub Keycloak), pas de table
  de correspondance séparée. Quand un admin relie un interlocuteur Telegram
  (`POST /correspondances`), il doit utiliser le vrai sub `calendar-app` de la personne
  (obtenu après sa 1ʳᵉ connexion à `/app`) — pas un nom libre.
- **Chat web** : nouvelle dépendance légère qui lit le cookie de session S171
  automatiquement si présent, sans rien changer côté JS du dashboard. Le corps de
  requête explicite (`utilisateur`, déjà utilisé par Telegram/S2S) garde la priorité.
- **Chemin manifest/dynamique** (`core/outils_communs.py::_entetes_brique`,
  `ADMIN_COMPTE_ID`) : **hors périmètre**. Sert toutes les briques pilotables par
  manifest (pas seulement l'agenda) ; le retoucher réouvrirait l'ADR
  `docs/decisions/2026-07-13-surface-de-service-role-admin.md` déjà tranché. Reste pinné
  comme aujourd'hui.
- **Restaurant** (`ADMIN_COMPTE_ID="admin"`) : hors périmètre, reporté (comme prévu par
  le cadrage initial de l'épopée : « restaurant si le temps le permet, sinon reporté »).
- **Risque croisé `AUTH_ENABLED`/`CALENDAR_SERVICE_TOKEN`** : documenté (dans ce sprint
  et le README de la brique agenda), pas corrigé maintenant — fait partie de la liste de
  prérequis pour la vérification LIVE finale (fin de S180, voir
  [[feedback-live-differe-fin-s180]]).

## Architecture

```
Web (dashboard, S171)          Telegram (briques/connexion, déjà câblé)
  |                                |
  | POST /assistant/chat          | pont.traiter() -> client_assistant.converser(
  | corps.utilisateur absent      |   utilisateur=corr.get("utilisateur"))
  | -> lit cookie session         |
  | -> sub Keycloak (NOUVEAU)     | -> déjà correct si lié au vrai sub
  v                                v
      contexte_tenant.definir_contexte(utilisateur=...)  (déjà existant, S121)
                    |
                    v
      core/agenda.py::entetes_agenda() -> X-User-Id: <sub>  (déjà existant)
                    |
                    v
      agenda brique : Calendar/CalendarMember (déjà existant, S172)
```

### Nouveau code

- `core/auth.py` — nouvelle fonction `sub_session_optionnel(request: Request) -> str |
  None` : déchiffre le cookie de session s'il existe (réutilise `dechiffrer_cookie`),
  renvoie son `sub` ou `None`. Volontairement **léger** : pas de vérification de
  fraîcheur du token Keycloak (ce n'est pas un point de sécurité — l'attribution sert à
  savoir « pour qui », le vrai contrôle d'accès reste `require_calendar_access` côté
  agenda, inchangé) — donc rapide, jamais d'exception, jamais de redirection. Cookie
  absent ou corrompu ⇒ `None`, jamais de blocage.
- `core/routers/assistant.py` — le handler `assistant_chat(corps: dict)` n'a
  aujourd'hui aucun paramètre `Request` ; en ajouter un (FastAPI l'injecte
  automatiquement, aucun appelant existant n'est affecté). Remplacer la lecture
  actuelle `utilisateur = corps.get("utilisateur")` par : si absent, essayer
  `auth.sub_session_optionnel(request)` avant de retomber sur le défaut actuel (aucune
  identité posée ⇒ `"perso"` par défaut côté agenda, comportement inchangé).

### Pas de changement

- `core/contexte_tenant.py`, `core/agenda.py`, `briques/connexion/{correspondance.py,
  pont.py,main.py}` — déjà corrects, réutilisés tels quels.
- `core/outils_communs.py::_entetes_brique` — hors périmètre (décision ci-dessus).

## Erreurs & cas limites

- Cookie de session absent/corrompu → `None`, repli sur le comportement actuel (jamais
  de blocage du chat).
- `AUTH_ENABLED=false` côté Cœur (dev local) → pas de vraie session de toute façon,
  comportement inchangé (défaut `"perso"`).
- Message Telegram d'un interlocuteur pas encore lié → déjà géré par
  `correspondance.resoudre()` (statut `en_attente`, message d'accueil avec code) —
  inchangé par ce sprint.
- Corps de requête avec `utilisateur` explicite (Telegram, scripts) → priorité
  inchangée sur la session web.

## Tests

- `core/test_auth.py` : `sub_session_optionnel` — session valide → sub ; pas de cookie →
  `None` ; cookie corrompu → `None`.
- Tests du handler de chat (fichier de test existant de `assistant.router` à
  identifier au moment du plan) : `utilisateur` explicite dans le corps → priorité
  conservée (non-régression) ; pas de corps + session valide → sub de la session
  utilisé (nouveau) ; ni l'un ni l'autre → `"perso"` (non-régression).
- Pas de nouveau test pour Telegram/`correspondance.py`/`pont.py` — code inchangé,
  déjà testé par sa propre suite existante.

## Hors périmètre (S173)

- Chemin manifest/dynamique de l'agenda (`_entetes_brique`/`ADMIN_COMPTE_ID`) — ADR déjà
  tranché, non rouvert.
- Restaurant (`ADMIN_COMPTE_ID`) — reporté.
- Corriger le risque croisé `AUTH_ENABLED`/`CALENDAR_SERVICE_TOKEN` — documenté
  seulement, à traiter au moment de la vérification LIVE finale (fin de S180).
- UI d'administration pour `POST /correspondances` — l'API existante suffit (motif
  identique à l'invitation manuelle de S172 : pas de UI dédiée pour une seule personne
  à lier).
