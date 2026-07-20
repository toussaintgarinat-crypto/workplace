# S187 — Isolation par personne de la brique `studio` (audio-séries)

Date : 2026-07-20 · Mémoire : [[sprint-s184-s187-isolation-briques-restantes]]
Dernier des 4 trous reportés par l'audit S183 (`docs/rapport-s183-audit-isolation.md`), après
[[sprint-s184-s187-isolation-briques-restantes]] (ecoute S184, mail S185, memoire S186). Réalise
le motif « chacun son espace » (agenda S182) sur `briques/studio/` (port 6060).

## Constat (audit S183 + relecture du code)

`briques/studio/main.py:279` capture déjà `"cree_par": cle` à la création d'une série (`cle` =
identité renvoyée par `cle_api()`), mais **aucune route ne filtre dessus** : `lister_series`
renvoie TOUTES les séries de tout le monde, `charger()` (le wrapper utilisé par ~35 routes —
cycles, tomes, personnages, épisodes, arbre, bible, audio…) ne vérifie aucune appartenance.
Le verdict initial de l'audit ("bundle-client") supposait une vente BYO standalone ; en usage
réel dans le Cœur, la tuile dashboard "Créations" (`core/routers/dashboard.py:3395-3401`)
transporte une **unique** `STUDIO_KEY` pour tout le foyer — même situation que mail avant S185
et memoire avant S186 : tout le cercle privé partage le même `cree_par`.

Brique `statut: a_tester` au manifest (jamais utilisée en LIVE avec de vraies données) : risque
de migration nul en pratique, mais le design reste zéro-rewrite forcé par prudence.

## Décisions de kickoff (confirmées par l'utilisateur le 2026-07-20)

1. **Périmètre complet** : assistant (outils LLM, `core/outils_communs._studio_appel`) ET tuile
   dashboard — comme mail S185 et memoire S186, pas seulement l'assistant.
2. **Isolation par personne** (motif agenda/ecoute/mail/memoire) : chaque série appartient à son
   créateur, invisible aux autres membres du foyer. Pas d'espace partagé "Workplace" par défaut
   (contrairement à memoire) — une série audio est un projet personnel, pas une base de
   connaissance collective.

## Modèle d'auth — deux dialectes coexistants (motif mail S185)

`cle_api()` (`briques/studio/main.py:48-59`) gagne un second chemin :

- Clé présentée == `STUDIO_KEY` (lue fraîche via `os.environ.get`, PAS une constante figée au
  niveau module — pour rester monkeypatchable par les tests, motif `ECOUTE_KEY`/`MAIL_KEY`)
  ⇒ identité = `X-User-Id` transmis par le Cœur, repli `"perso"` si absent.
- Toute AUTRE clé présente dans `API_KEYS` (vente BYO standalone, motif historique inchangé)
  ⇒ identité = la clé elle-même (comportement actuel, zéro régression pour un client qui achète
  la brique seule — sa clé EST déjà son tenant naturel).
- Mode ouvert (aucune clé configurée du tout) ⇒ identité = `"public"` (comportement actuel,
  inchangé — dev/démo, un seul bucket partagé).

`core/outils_communs.BRIQUES_PAR_PERSONNE` (`core/outils_communs.py:51`) gagne `"studio"` :
`{"agenda", "ecoute", "mail", "memoire", "studio"}`.

## Filtrage centralisé via `charger()`

`charger(serie_id: str, identite: str) -> dict` (`briques/studio/main.py:62-67`) prend
désormais l'identité courante et lève **404** (pas 403, motif mail/ecoute — ne pas révéler
l'existence d'une série à quelqu'un d'autre) si `serie.get("cree_par") != identite_effective`
(voir migration ci-dessous). Toutes les ~35 routes qui appellent déjà `charger(serie_id)`
passent simplement `cle` (déjà injecté par `Depends(cle_api)`) en second argument — un seul
point de contrôle, pas de duplication route par route.

`lister_series` filtre par identité (`WHERE cree_par == identite`, en mémoire puisque c'est du
JSON fichier) au lieu de tout renvoyer. `reordonner_series` ignore silencieusement les
`id` qui n'appartiennent pas à l'appelant (même motif que `charger`, sans lever d'erreur pour
ne pas casser un réordonnancement partiel légitime sur le reste de la liste).

## Compatibilité mono-user / migration (zéro rewrite forcé)

Une série existante peut avoir `cree_par` = `"public"` (mode ouvert historique) ou l'ancienne
valeur brute de `STUDIO_KEY` (si elle était déjà configurée avant ce sprint — cas rare vu le
statut `a_tester`). Ces deux valeurs ne correspondent à AUCUNE identité valide sous le nouveau
dialecte per-personne (qui produit toujours soit un `X-User-Id` réel, soit `"perso"`).

`_identite_effective(serie: dict) -> str` : normalise `cree_par` à la lecture — si la valeur
n'est ni un `X-User-Id` connu ni `"perso"` (c'est-à-dire : ancienne valeur brute de clé, ou
`"public"`), elle est traitée comme `"perso"` pour la comparaison. **Pas de rewrite du fichier**
(contrairement à ecoute qui avait une colonne SQL avec `DEFAULT`) : la normalisation est
appliquée à la volée à chaque lecture, dans `charger()` et `lister_series`, jamais persistée —
plus simple et suffisant puisque `cree_par` n'est de toute façon jamais réécrit après création.

## Tuile dashboard — proxy Cœur `/studio-app/*` (motif mail S185)

Nouveau `core/routers/mail_proxy.py`-like : `core/routers/studio_proxy.py`. Studio a UN AVANTAGE
sur mail ici : son frontend (`front.html`) a déjà un point d'entrée HTTP unique pour tous ses
appels — la fonction JS `api(path, method, body)` (`front.html:159-163`). Au lieu de préfixer 37
sites d'appel comme mail (13 `fetch()` absolus dispersés), une seule ligne change dans `api()` :

```js
const API = (window.STUDIO_API_BASE || '');
async function api(path, method='GET', body=null){
  const r = await fetch(API + path, {method, headers: HDR, ...});
  ...
}
```

`core/routers/studio_proxy.py` :
- `GET /studio-app/` et `/studio-app/atelier` : sert `front.html` (proxié depuis la brique, pas
  lu localement — motif mail, une seule source de vérité) avec injection
  `<script>window.STUDIO_API_BASE='/studio-app';</script>` avant `</head>`, et réécriture du
  `src="/manipulation_directe.js"` en `src="/studio-app/manipulation_directe.js"` (même piège
  que `purify.min.js` côté mail).
- `api_route("/studio-app/{chemin:path}", methods=[GET,POST,DELETE,PATCH,PUT])` : proxy
  générique du reste (API + `/manipulation_directe.js` + `/workplace.css`), identité TOUJOURS
  dérivée de `outils_communs._entetes_brique("studio")` (session Cœur, `exiger_session` +
  `lire_contexte_tenant` posés sur le router dans `core/main.py`, motif mail/agenda) — les
  en-têtes du navigateur (X-API-Key, Authorization) sont ignorés, jamais forwardés tels quels.

`core/routers/dashboard.py:3395-3401` : remplace `?api_key=STUDIO_KEY` par un pointage direct de
l'iframe sur `/studio-app/` (même origine, session déjà posée) — même changement que mail
(`chargerMail()` pointant `/mail-app/`). Le comportement `?api_key=` du front reste dans
`front.html` pour l'usage BYO standalone (démo hors Cœur) — inchangé, juste plus utilisé par la
tuile.

## Cas limite : `personnages-holistiques` et autres routes SANS `serie_id`

`GET /personnages-holistiques`, `GET /voix`, `GET /cibles`, `GET /langues`, `GET /equipe` ne
touchent aucune série — restent inchangées (juste gardées par `Depends(cle_api)`, déjà le cas).

## Tests

- `briques/studio/test_isolation_personne.py` (nouveau, motif `test_isolation.py` d'ecoute/mail) :
  deux identités (`X-User-Id` A et B sous `STUDIO_KEY`) → série de A invisible pour B
  (`GET /series/{id}` par B → 404, absente de `GET /series` de B, toutes les sous-routes —
  cycles/tomes/personnages/épisodes — 404 pour B) ; clé BYO (`API_KEYS`) inchangée (tenant =
  la clé, comme avant) ; mode ouvert inchangé (`"public"`) ; série legacy (`cree_par="public"`
  ou ancienne clé brute) visible sous l'identité `"perso"` seulement.
- `core/test_studio_proxy.py` (nouveau, motif `core/test_mail_proxy.py`) : identité de session
  forwardée, en-têtes navigateur ignorés, `STUDIO_API_BASE` injecté dans la page, réécriture
  `manipulation_directe.js`.
- `core/test_contexte_tenant.py` / `core/test_outils_dynamiques.py` : `_entetes_brique("studio")`
  forwarde `X-User-Id` comme les 4 autres briques `BRIQUES_PAR_PERSONNE`.
- `briques/studio/test_auth.py` existant : les 4 tests (mode ouvert, auth BYO 401/200/mauvaise
  clé) restent inchangés — dialecte BYO non touché.
- `make test-core` et la suite `briques/studio/` restent au vert.

## Hors périmètre

- Pas de modèle de partage explicite (une série reste strictement privée à son créateur, pas de
  "co-écriture" à plusieurs dans ce sprint — hors décision de kickoff).
- Pas de migration de données réelles (statut `a_tester`, jamais déployée en LIVE).
- Pas de déploiement LIVE HP dans ce sprint (régime preuve Docker différée, cf.
  [[regime-preuve-docker-differe]]) — code + tests uniquement.

## Risques

- `charger()` change de signature (`serie_id` → `serie_id, identite`) : ~35 call sites à mettre
  à jour mécaniquement — mitigé par le fait que c'est un changement de signature simple, détecté
  immédiatement par pytest si un appel est oublié (le paramètre `identite` sera manquant →
  `TypeError` explicite, pas un bug silencieux).
- `reordonner_series` qui ignore silencieusement des `id` étrangers plutôt que 404 : choix
  délibéré (réordonnancement = opération best-effort sur SA propre liste), à documenter dans le
  docstring de la route pour éviter la confusion en revue.
