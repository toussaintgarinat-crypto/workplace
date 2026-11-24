# S243 — Briques qui dorment (réveil à la demande, piloté par l'assistant)

**Statut : CODÉ + TESTÉ (40 tests) sur la branche `sprint/s243-sommeil-briques`. Inerte par
défaut (`SOMMEIL_ACTIF=0`). Pas encore déployé ni activé sur le HP.**

## Ce que ça fait

Une brique peu utilisée peut être éteinte après un délai d'inactivité et rallumée à la
première demande. L'assistant le pilote lui-même.

| Pièce | Rôle |
|---|---|
| `core/sommeil.py` | état, réveil (attend `healthy`), endormissement, balayage d'inactivité, garde-fous |
| outils `brique_etat`, `brique_reveiller`, `brique_endormir` | l'assistant voit / réveille / endort |
| `outils._executer` | réveille automatiquement la brique avant l'appel d'un de ses outils |
| `horloge._executer` | idem avant une tâche planifiée |
| `/sante-globale`, `etat_briques` | statut `endormie` (≠ `inaccessible`) |
| manifeste `"sommeil": {"conteneurs": [...], "inactivite_min": 30, "attente_s": 90}` | **opt-in** par brique |

## Garde-fous (et pourquoi)

- **Opt-in** : sans bloc `sommeil`, une brique n'est jamais touchée.
- **Liste noire en dur** : `core, gateway, gateway-sync, keycloak, memoire, agenda,
  sommeil-proxy` ne dorment jamais, même si un manifeste le demandait.
- **`brique_endormir` réservé à l'admin du cerveau** (`droits.RESERVES`) : éteindre une brique
  partagée gêne tous les utilisateurs. Réveiller reste ouvert à tous (inoffensif).
- **« endormie » n'est affirmé que si le conteneur existe et est arrêté.** Un conteneur
  introuvable ou une API Docker muette donne `inconnue`, jamais « endormie » : une panne ne se
  déguise pas en sommeil.
- **Une action non confirmée ne réveille rien** (l'accord de l'utilisateur passe d'abord).
- **Après un redémarrage du Cœur**, le délai d'inactivité repart de zéro : rien n'est éteint d'un coup.
- Pourquoi des outils câblés et pas des capacités de manifeste : ils agissent sur
  l'infrastructure (Docker), pas sur une route HTTP d'une brique — il n'y a pas de brique pour
  les déclarer. (Raison de sécurité/nature nommée, cf. règle « exposer à l'assistant ».)

## Constats qui ont changé le plan

1. **Le Cœur monte déjà le socket Docker complet** (`core/docker-compose.yml`) : il s'en sert
   pour recréer la Gateway et pour la sauvegarde USB (`exec`, `cp`). Un proxy restreint pour la
   seule fonction « sommeil » n'apporte donc presque aucune isolation tant que le Cœur garde ce
   socket. Le backend lit `SOMMEIL_DOCKER_URL` : un proxy peut s'y brancher plus tard sans
   toucher au code. Le vrai gain de sécurité serait de retirer le socket du Cœur (hors périmètre).
2. **La RAM gagnable est modeste.** Sur le HP : 8,4 Go utilisés par les conteneurs sur 23 Go ;
   les briques Python pèsent 35–50 Mo chacune ; les gros consommateurs (Gateway ~1 Go, Keycloak
   ×2, Qdrant, ClamAV ~1 Go, Écoute ~0,5 Go) sont vitaux ou doivent rester éveillés.
3. **Les appels directs brique→brique ne réveillent pas.** `geo` est appelée par
   veille-prospection/forge/atelier-veille, `images`/`video` par studio/atelier-images-video :
   endormies, ces appels échoueraient. Pilote retenu = briques **sans consommateur direct** :
   `synopsis` et `connecteurs` (la tâche `sync-quotidienne` de connecteurs réveille via l'horloge).

## Limites connues

- Une brique qui fait un travail **asynchrone plus long que `inactivite_min`** pourrait être
  coupée (l'activité est notée à l'appel, pas pendant le polling du job).
- Les **interfaces appelées directement par le navigateur** (frontends, liens publics) ne
  réveillent pas la brique : ne pas les déclarer `sommeil`.
- Un `docker compose up -d` (déploiement) rallume les briques endormies ; elles se rendorment
  après leur délai d'inactivité.

## Activer

1. Déployer la nouvelle image du Cœur (build sur le Mac puis `docker save | ssh docker load`,
   cf. note « build pip impossible sur le HP »).
2. Poser `SOMMEIL_ACTIF=1` dans le `.env` **racine** du HP, puis `docker compose up -d --no-build`
   dans `core/`.
3. Vérifier : `brique_etat` (assistant) puis attendre `inactivite_min` ; `/sante-globale` doit
   montrer `endormie` ; appeler un outil de la brique doit la réveiller.

## Tests

`core/test_sommeil.py` (21), `core/test_sommeil_outils.py` (12), `core/test_sommeil_sante.py` (7).
Faux Docker en mémoire : aucun conteneur réel touché.
