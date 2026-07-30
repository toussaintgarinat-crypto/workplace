# Brique `jeu-factions` — identité réelle scopée au cercle privé (S217, sous-projet 4/5 partiel)

## Contexte

Le backlog [`S216-S220-jeu-factions-sous-projets-restants.md`](../../sprints/S216-S220-jeu-factions-sous-projets-restants.md)
pose le constat : jeu-factions vient d'être câblé dans le dashboard du Cœur (tuile Atelier,
`core/urls_ui.py:36`) sans reprendre le motif d'identité par personne déjà rodé 3 fois
(Mémoire S186, Studio S187, Atelier Images & Vidéo). Il tourne encore sur `cle_api`, aujourd'hui
un no-op : `API_KEYS` est vide côté brique, donc tout le monde partage le tenant `"public"`
(`briques/jeu-factions/main.py:32-43`).

Deux motifs existent dans le repo pour transporter l'identité Cœur→brique :

- **Jeton signé** (Mémoire, S186) : `core/memoire_jeton.py` émet un HMAC
  `utilisateur:expiration:signature` (secret `MEMOIRE_KEY`), posé en query param `?m=` sur
  l'URL de la tuile ; la brique le vérifie, pose un cookie (8h) pour les navigations
  suivantes.
- **Proxy + `X-User-Id`** (Studio S187, Atelier Images & Vidéo) : le Cœur relaie les requêtes
  HTTP via `core/routers/studio_proxy.py`, injectant `X-User-Id` depuis la session
  (`core/contexte_tenant.py`).

**Décision (tranchée avant ce spec) : motif jeton signé, façon Mémoire.** jeu-factions a une
route WebSocket authentifiée aujourd'hui par un `api_key` en query param
(`_cle_depuis_query`, `main.py:204-209` — motif déjà là car un navigateur ne pose pas de
header custom au handshake WS). Le motif proxy (Studio) ne couvre que du HTTP relayé, aucun
des proxies existants ne proxifie de WebSocket — l'adopter aurait exigé soit un proxy WS
inédit, soit un mécanisme séparé juste pour le WS, donc plus de code que le motif jeton qui
couvre nativement les deux avec un seul mécanisme.

**En creusant le code exact de Mémoire, simplification trouvée par rapport à l'intuition
initiale** : pas besoin d'un header custom (`X-Jeu-Jeton`) sur les appels JSON. Une fois le
cookie posé par la toute première navigation, le navigateur l'envoie automatiquement sur
toute requête same-origin — HTTP *et* WebSocket. Le jeton en query param ne sert donc que sur
la route `/` (celle qui reçoit l'URL construite par le Cœur) ; toutes les autres routes
(JSON + WS) lisent uniquement le cookie. C'est plus proche du code réel de Mémoire
(`_identite_navigateur` ne regarde que query param + cookie, jamais de header) que de ce que
le premier tour de brainstorming avait esquissé.

## Non-objectifs

- **Aucun hébergement public, aucun compte hors cercle privé.** Explicitement renvoyé à S220
  (non scopé). Ce sprint réutilise l'infra Keycloak/session déjà en place, n'en ajoute pas.
- **`zones`/`scores_zone_guilde`/`zones_archetype`/`competences` restent un monde partagé**,
  non filtré par tenant — design assumé depuis le sous-projet 1, ce spec n'y touche pas.
- **Pas de mode dégradé « accès direct sans passer par le Cœur ».** Décision explicite :
  contrairement à Mémoire (qui retombe sur un compte de service si `MEMOIRE_KEY` est absente
  ou si le jeton/cookie manque — `briques/memoire/main.py:293-299`), jeu-factions **refuse
  tout accès sans identité vérifiée** après ce sprint. Conséquence assumée :
  `JEU_FACTIONS_KEY` devient *obligatoire* en pratique pour que la brique serve à quoi que ce
  soit (à poser au déploiement, pas seulement en dev) — divergence délibérée du motif Mémoire,
  pas un oubli.
- **Pas de jolie identité affichée.** `cle_api` devient le `sub` Keycloak (une chaîne opaque),
  pas un pseudo lisible — `joueurs.pseudo` continue de valoir `cle_api` par défaut
  (`stockage.assurer_joueur`, inchangé). Cosmétique, hors périmètre de ce sprint.
- **Pas de nouvelle table, pas de nouvelle colonne.** `joueurs.cle_api` et
  `personnages_jeu.cle_api` restent des colonnes texte libres — elles contiennent déjà des
  chaînes arbitraires (`"public"`, une clé collée à la main) ; ce sprint change ce qu'on y
  met, pas le schéma.

## Mécanique

### Flux

1. La personne est connectée au Cœur (session Keycloak déjà exigée sur `/dashboard`,
   `core/main.py:88`).
2. `dashboard.py` construit l'URL de la tuile jeu-factions en y ajoutant un jeton HMAC en
   query param `?j=`, exactement comme il le fait pour Mémoire avec `?m=`.
3. `front.html`, chargé via cette URL, ne fait plus rien de spécial pour l'auth — le cookie
   posé par la réponse de `/` est envoyé automatiquement par le navigateur sur tous les
   appels `fetch()` et sur le handshake WebSocket suivants (même origine).
4. Toutes les routes JSON existantes (`Depends(cle_api)`) et la route WS
   (`/zones/{zone_id}/combat`) lisent l'identité depuis ce cookie, jamais depuis un header ou
   un query param custom.

### Vérification et cookie (brique)

Nouveau module `briques/jeu-factions/jeton.py` (miroir de la logique de vérification de
`briques/memoire/main.py:293-311`, extraite dans son propre fichier plutôt que noyée dans
`main.py` — cohérent avec la modularité déjà en place : `archetypes.py`, `groupes.py`,
`stockage.py` sont chacun un fichier dédié) :

```python
COOKIE_NOM = "jeu_factions_utilisateur"

def verifier(jeton: str | None) -> str | None: ...   # None si absent/invalide/expiré
def emettre(utilisateur: str, ttl: int) -> str: ...   # utilisateur:expiration:signature
```

Secret : `JEU_FACTIONS_KEY` (env var, même rôle que `MEMOIRE_KEY`).

- **`GET /`** (`accueil`, aujourd'hui un simple `FileResponse`) devient une route qui lit
  `request.query_params.get("j")`, vérifie (jeton d'URL en priorité, sinon cookie déjà posé),
  et :
  - si une identité est établie : sert `front.html`, pose/rafraîchit le cookie (8h) **si**
    un jeton d'URL valide était présent (même règle que Mémoire — un simple F5 sans repasser
    par le Cœur ne prolonge pas la session au-delà des 8h) ;
  - sinon : répond `401` avec une page HTML minimale invitant à rouvrir la tuile depuis le
    Cœur (statut `401` conservé pour rester cohérent avec le reste de la brique et pour que
    les tests distinguent ce cas, mais corps HTML — pas un `401` JSON nu — puisque c'est ici
    la seule route atteinte par une navigation humaine directe, cf. décision de cadrage).
- **`cle_api()`** (utilisée par toutes les routes JSON) devient : lit uniquement le cookie
  (`jeton.verifier(request.cookies.get(jeton.COOKIE_NOM))`) ; absent/invalide → `401` JSON
  (ces routes sont appelées en `fetch()` par le front, jamais par une navigation directe — un
  401 JSON y est le bon comportement, charge au front de l'afficher proprement, cf. Front
  ci-dessous). Migration (voir plus bas) déclenchée ici.
- **`/zones/{zone_id}/combat`** (WS) : lit `websocket.cookies.get(jeton.COOKIE_NOM)` au lieu
  du query param `api_key`. `_cle_depuis_query` et le paramètre `api_key: str = Query("")`
  disparaissent — plus nécessaires, le cookie est déjà posé par la navigation qui a chargé
  `front_combat.html` avant que le WS ne se connecte.
- **`API_KEYS`** (dict de clés partagées) disparaît entièrement de `main.py` — conséquence du
  non-objectif « pas de mode dégradé ».

### Migration des données sous `"public"`

Décision de cadrage : au premier passage d'une identité réelle, les données existantes sous
`cle_api="public"` sont réattribuées à cette identité (pas de perte des essais déjà faits).
Limite assumée : si deux personnes ouvrent la tuile pour la toute première fois en même temps,
la première gagne la migration, la seconde démarre à vide — acceptable dans un cercle privé de
test, pas un vrai risque de collision de comptes en usage normal (une personne à la fois découvre
la brique).

`groupes`/`membres_groupe` n'ont **pas** de colonne `cle_api` (vérifié dans
`stockage.py:71-76`) — ils référencent des `personnage_id`, donc suivent automatiquement la
réattribution de `personnages_jeu` sans migration propre. Seules deux tables sont concernées :
`joueurs` et `personnages_jeu`.

```python
def migrer_public_si_premiere_connexion(cle_api_reelle: str) -> None:
    """Idempotent : no-op dès que `cle_api_reelle` a déjà une ligne dans `joueurs`
    (le cas courant, à partir de la 2e requête). Ne migre qu'une fois par déploiement —
    une fois les lignes `cle_api='public'` réattribuées, la condition ne se représente plus."""
```

Appelée depuis `cle_api()` (le point de passage de toutes les routes JSON) : un `SELECT` bon
marché une fois la ligne présente, donc négligeable après le premier appel de chaque nouvelle
identité.
Pas un tick, pas une migration au démarrage — calculée à la lecture, motif déjà établi par
S216 (bonus idle).

## Modèle de données

Aucun changement de schéma. `joueurs.cle_api` / `personnages_jeu.cle_api` contiennent
désormais un `sub` Keycloak plutôt que `"public"` ou une clé collée à la main.

## Routes touchées (contrat inchangé, auth changée)

Toutes les routes JSON existantes (`/personnages`, `/personnages/{pid}`,
`/personnages/{pid}/zone`, `/personnages/{pid}/competences`, `/zones`, `/zones/{zid}`,
`/archetypes/{archetype}/etapes`, `/groupes`, `/groupes/{gid}/rejoindre`, `POST /presence`)
gardent leur contrat (entrée/sortie) identique — seule la résolution de `cle: str =
Depends(cle_api)` change de mécanisme. `/sante` reste public (aucune dépendance
d'auth, inchangé). `/zones/{zone_id}/combat` (WS) garde son contrat de messages, seule
l'authentification du handshake change.

## Front (`front.html`, `front_combat.html`)

- Suppression complète de la case « coller ta clé API » et de la lecture/écriture
  `localStorage.getItem("jeu_factions_cle")`.
- Plus aucune gestion d'auth explicite dans le JS : les `fetch()` n'ajoutent plus de header
  `X-API-Key`, le cookie suffit (même origine).
- Un appel `fetch()` qui reçoit `401` affiche un message inline « Session expirée — rouvre
  cette page depuis le tableau de bord du Cœur » à la place du contenu concerné, plutôt qu'une
  erreur JS silencieuse ou une page cassée. Décision de cadrage (jeton expiré à 8h en session
  ouverte → même message que si la tuile n'a jamais été ouverte par le Cœur).
- `front_combat.html` inchangé dans sa logique WS (le cookie est déjà là au moment où il se
  connecte) — seul le retrait du paramètre `api_key` dans l'URL de connexion WS, devenue
  inutile.

## Cœur (`core/`)

- Nouveau module `core/jeu_factions_jeton.py`, copie conforme de `core/memoire_jeton.py`
  (secret `JEU_FACTIONS_KEY`, `TTL_DEFAUT = 120` — juste assez pour charger la page, le
  cookie prend le relais ensuite).
- `core/routers/dashboard.py` : construction de `jeu_factions_ui` sur le même motif que
  `memoire_ui` (lignes 65-73 actuelles) — `?j=` ajouté si `JEU_FACTIONS_KEY` est configurée,
  URL laissée nue sinon (auquel cas la brique refusera tout, cf. non-objectifs).
- Aucun nouveau routeur côté Cœur (pas de proxy — le motif jeton n'en a pas besoin, la brique
  reste jointe directement sur son port 6210 comme aujourd'hui, comme Mémoire sur 5600).

## Configuration (env)

Nouvelle variable `JEU_FACTIONS_KEY` dans `.env.example` (section dédiée, à côté de
`MEMOIRE_KEY`) — secret partagé Cœur↔brique. Aucun changement à
`briques/jeu-factions/docker-compose.yml` ni `core/docker-compose.yml` : les deux services
chargent déjà `.env` racine via `env_file` (`env_file: ../../.env` et `env_file: ../.env`
respectivement) — la déclarer dans l'`environment:` d'un des deux composes la figerait à vide
et écraserait la vraie valeur (piège déjà documenté pour `AGENDA_KEY`/`ECOUTE_KEY`,
`core/docker-compose.yml:35`).

**Rappel opérationnel** (à répéter au moment du déploiement LIVE HP, pas seulement ici) :
sans `JEU_FACTIONS_KEY` posée dans le `.env` racine, la tuile devient inutilisable pour tout
le monde après ce sprint — contrairement aux autres briques « cercle privé » du repo, il n'y a
pas de repli mono-tenant.

## Tests

- `jeton.verifier`/`jeton.emettre` (purs) : jeton valide → identité ; signature invalide →
  `None` ; expiré → `None` ; malformé (pas 3 segments) → `None` ; roundtrip
  émission→vérification.
- `cle_api()` : cookie valide → identité retournée, migration invoquée ; cookie
  absent/invalide → `401` ; jamais de repli `"public"`/service.
- `GET /` : jeton d'URL valide → sert le front + pose le cookie ; cookie déjà valide (sans
  jeton d'URL) → sert le front, ne repose pas le cookie ; ni l'un ni l'autre → page d'invite,
  pas de `front.html`.
- WS `/zones/{zone_id}/combat` : cookie valide → connexion acceptée ; cookie
  absent/invalide → fermeture `4401`, comme le comportement actuel sur clé invalide.
- `stockage.migrer_public_si_premiere_connexion` : lignes `joueurs`/`personnages_jeu` sous
  `"public"` réattribuées à la première identité réelle vue ; rejouée pour la même identité
  (2e appel) → no-op, pas d'erreur ; rejouée pour une 2e identité réelle différente (plus de
  ligne `"public"`) → no-op, ne vole pas les personnages déjà migrés vers la première.
- Non-régression : le contrat JSON de chaque route existante (formes de payload, codes
  d'erreur 404/422 déjà en place) reste identique — seul le mécanisme derrière
  `Depends(cle_api)` change.
