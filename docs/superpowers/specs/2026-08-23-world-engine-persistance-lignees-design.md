# World Engine — Persistance des lignées (Sprint A)

**Date** : 2026-08-23
**Statut** : design approuvé, plan d'implémentation à venir

## Contexte

Suite de [world-engine-genome-cosmique-design](2026-08-22-world-engine-genome-cosmique-design.md).
Le protocole d'évaluation GO/NO-GO a été exécuté le 2026-08-23 (9 croisements :
3 paires de parents contrastées × 3 `mutation_rate`) — voir mémoire
[[backlog-world-engine-genome-cosmique-phases-suivantes]] pour le détail des
observations. Verdict utilisateur : **GO tel quel**. Deux limites structurelles
restent connues (hérédité faible sur les corps lents, `mutation_rate`
majoritairement cosmétique) mais n'empêchent pas de démarrer ce sprint — elles
seront reconsidérées si elles gênent une fois la persistance en place.

`world-engine` est aujourd'hui **stateless** : `POST /genome/croiser` calcule un
enfant à la volée et ne stocke rien. Impossible d'enchaîner des générations
(n+2, arbre généalogique) sans d'abord persister les enfants générés. C'est
l'objet de ce sprint.

## Décisions de conception (issues du brainstorming)

- **Stockage automatique**, pas opt-in. Chaque appel réussi à
  `/genome/croiser` persiste l'enfant — cohérent avec le but du sprint
  (enchaîner les générations sans re-décider à chaque croisement). Diffère du
  motif `personnages/stockage.py` (opt-in strict) délibérément : le stockage
  n'est pas un choix narratif ici, c'est le mécanisme qui rend les générations
  suivantes possibles.
- **Réutilisation par id.** `parent_a`/`parent_b` acceptent soit une fiche
  brute (comportement actuel, inchangé), soit `{"id": "..."}` pointant vers un
  enfant déjà stocké — world-engine relit alors son thème directement en base,
  sans rappeler `personnages`.
- **Cloisonnement par `cle_api`**, même motif que `personnages` : chaque clé ne
  voit que ses propres enfants. En mode ouvert (`API_KEYS` vide) tout tombe
  sous `"public"` — l'isolation existe déjà si des clés sont configurées plus
  tard, rien à migrer.
- **Endpoint d'arbre inclus** dès ce sprint (`GET /genome/arbre/{id}`) — motivé
  explicitement par le besoin de reconstruire une lignée, pas différé.
- **Suppression incluse** (`DELETE /genome/enfants/{id}`) — simple, sans
  cascade.

## Modèle de données

Nouveau module `briques/world-engine/stockage.py`, SQLite (stdlib), motif
`personnages/stockage.py` :

```sql
CREATE TABLE IF NOT EXISTS enfants (
    id TEXT PRIMARY KEY,           -- uuid4().hex
    cle_api TEXT NOT NULL,         -- cloisonnement ("public" en mode ouvert)
    prenoms TEXT, nom TEXT,
    parent_a_id TEXT,              -- NULL si parent_a était une fiche brute
    parent_b_id TEXT,              -- NULL si parent_b était une fiche brute
    donnees TEXT NOT NULL,         -- JSON : {theme_complet, description_genome,
                                    --         heredite, mutation_survenue}
    cree_le TEXT
)
CREATE INDEX idx_enfant_cle ON enfants(cle_api)
```

- `donnees` est un snapshot complet du thème de l'enfant, même forme que la
  réponse `POST /holistique/portrait` de `personnages` — permet de le
  réinjecter tel quel comme `theme_a`/`theme_b` d'un croisement suivant sans
  rappeler `personnages`.
- `parent_a_id`/`parent_b_id` restent `NULL` quand le parent de ce croisement
  était une fiche brute plutôt qu'un enfant stocké. C'est ce qui borne la
  profondeur reconstructible par `GET /genome/arbre/{id}` : il remonte tant
  qu'il trouve un id, s'arrête sur `NULL`.
- Volume Docker dédié (`WORLD_ENGINE_DB`, défaut `/data/world_engine.db`),
  comme `PERSONNAGES_DB` — à ajouter dans `docker-compose.yml`.
- Pas de colonne `categorie`/renommage pour l'instant — YAGNI (personnages l'a
  ajouté après coup, sur besoin confirmé).

## Contrat API

### `POST /genome/croiser` (modifié)

`parent_a`/`parent_b` acceptent deux formes :

```jsonc
// fiche brute — comportement actuel, inchangé
{"prenoms": "...", "date_naissance": "...", "heure_naissance": "...", ...}
// OU référence à un enfant déjà stocké
{"id": "a1b2c3..."}
```

- `id` fourni mais introuvable (mauvais id, ou appartenant à une autre
  `cle_api`) → **404** explicite (pas 422 — ce n'est pas un problème de forme
  de fiche, c'est une ressource absente).
- Réponse enrichie d'un champ `enfant_id` : id du nouvel enfant stocké.
  Best-effort — si l'écriture SQLite échoue, le croisement est quand même
  retourné (le calcul a réussi) avec `enfant_id: null` et un champ
  `avertissement` ; jamais un 500 sur un calcul par ailleurs correct.

### `GET /genome/enfants` (nouveau)

Liste allégée, cloisonnée par `cle_api` :
`[{id, prenoms, nom, parent_a_id, parent_b_id, cree_le}]` — pas le snapshot
complet, pour rester lisible en liste.

### `GET /genome/enfants/{id}` (nouveau)

Fiche complète stockée (thème, hérédité, description, ids parents).
404 si absent ou appartenant à une autre `cle_api`.

### `GET /genome/arbre/{id}` (nouveau)

```jsonc
{
  "id": "...", "prenoms": "...", "nom": "...",
  "parent_a": { /* même forme, récursif */ } | null,
  "parent_b": { /* même forme, récursif */ } | null
}
```

S'arrête sur une branche dès que `parent_*_id` est `NULL` (fiche brute, pas un
enfant stocké) — pas de rappel à `personnages` pour « compléter » cette
branche. Une branche dont l'id de parent ne résout plus (supprimé entre-temps)
est traitée comme `null`, jamais une erreur qui casserait tout l'arbre. 404 si
l'id racine est absent ou d'une autre `cle_api`.

### `DELETE /genome/enfants/{id}` (nouveau)

204 si supprimé, 404 si absent/autre clé. Pas de cascade — un enfant supprimé
laisse ses descendants avec une branche tronquée (traité comme `null` par
`GET /genome/arbre`, pas une erreur).

## Repli honnête (ajouts à la section existante)

- `id` de parent introuvable/autre clé → 404, jamais confondu avec le 422
  « fiche invalide » du flux existant.
- Échec d'écriture SQLite après un croisement réussi → ne fait jamais échouer
  la requête ; `enfant_id: null` + `avertissement`.
- `GET`/`DELETE .../{id}` sur id absent ou d'une autre `cle_api` → 404, jamais
  403 (ne pas révéler qu'un id existe chez un autre client).

## Tests

- `test_stockage.py` (nouveau) : CRUD SQLite en isolation (tmp DB par test,
  même motif que `personnages`).
- `test_api.py` (étendu) :
  - croisement avec fiche brute → enfant stocké (`enfant_id` présent, ligne en
    base) ;
  - croisement avec `{"id": ...}` en parent → relit le snapshot stocké sans
    rappeler `personnages` (mock qui échouerait si appelé, pour le prouver) ;
  - cloisonnement `cle_api` : deux clés différentes ne voient pas les enfants
    l'une de l'autre (`GET /genome/enfants`, `GET .../{id}`) ;
  - `GET /genome/arbre/{id}` sur 3 générations (grand-parent stocké → parent
    stocké → enfant) ;
  - `DELETE` puis `GET` → 404 ;
  - branche tronquée : suppression d'un grand-parent puis `GET /genome/arbre`
    sur un descendant → branche `null`, pas d'erreur.
- Filet manifeste↔route étendu aux 4 nouvelles capacités (même motif que
  `test_manifest_capacites.py` existant).
- Pas de nouvelle preuve Docker manuelle requise : le stockage est purement
  local à world-engine (testable en mocké côté `personnages`) ; le protocole
  d'intégration réelle existant (thème/hérédité) reste suffisant pour la
  partie qui en dépendait.

## Manifest

- `genome_croiser` passe `"action": true` (persiste désormais un enfant).
- 4 nouvelles capacités : `genome_enfants_lister`, `genome_enfant_lire`,
  `genome_arbre_lire`, `genome_enfant_supprimer` — exposées par défaut à
  l'assistant, conformément à [[feedback-exposer-nouvelles-fonctionnalites-assistant]].

## Hors périmètre de ce sprint

- Renommage/catégorisation des enfants stockés (motif `personnages/fiches`,
  à reconsidérer seulement si le besoin se confirme).
- Correction des deux limites narratives notées au verdict GO (hérédité faible
  sur corps lents, `mutation_rate` cosmétique) — décision utilisateur : les
  garder à l'œil, pas les traiter dans ce sprint.
- Sprint B (maillage spatial), Sprint C (horloge de simulation), Sprint D
  (compilateur de packs) — roadmap inchangée, voir
  [[backlog-world-engine-genome-cosmique-phases-suivantes]].
