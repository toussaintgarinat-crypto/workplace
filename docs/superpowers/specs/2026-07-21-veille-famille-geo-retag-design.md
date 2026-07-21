# Design — Famille « Veille » (parent) + retag `geo`

**Date** : 2026-07-21
**Statut** : validé, prêt pour plan d'implémentation

## Contexte

Décision d'architecture actée le 2026-07-21 (mémoire `veille-brique-parente-sous-briques`) :
le user veut une brique **« veille » parente qui héberge des sous-briques** activables/
désactivables indépendamment, plutôt qu'une fusion plate. Deux sous-briques envisagées à
terme :
1. **Prospection géo-scrapée** — déjà largement implémentée dans `briques/geo` (Sirene,
   `enrichissement.py`, pipeline S169/S170 `geo_prospecter_lot`→`forge_crm_importer_lot`→
   `mail_demarchage_preparer`, LIVE HP).
2. **Veille informationnelle** — RSS→résumé→audio, aujourd'hui du code basique (CRUD
   sources/articles + fetch manuel) dans `briques/forge/forge/core/app/routers/veille.py`,
   sans planification ni résumé ni audio.

Ce spec couvre **uniquement** la première brique du parcours : le regroupement logique
« veille » + le retag de `geo` dans cette famille. L'extraction de la veille informationnelle
(nouvelle brique RSS avec résumé+audio) est un spec séparé, à faire ensuite.

Clarifications actées avec l'utilisateur :
- **Portée de l'absorption** : `geo` entre dans son intégralité (cartographie générique +
  prospection) sous la famille `veille` — pas seulement la partie prospection.
- **Modèle technique du « togglable »** : `geo` et la future brique RSS restent chacune leur
  propre service Docker/port/manifest, comme toutes les briques actuelles. « Veille » n'est
  **pas** un nouveau service qui absorbe du code — c'est un regroupement logique (famille de
  manifest) + un point d'entrée visuel dans le dashboard. Activer/désactiver une sous-brique =
  démarrer/arrêter son conteneur (rejoint l'idée déjà en mémoire du "Sprint Sablier").
- **Découpage** : ce spec ne touche à rien d'autre que le regroupement + retag. Aucune
  modification du code fonctionnel de `geo` (LIVE, ne pas risquer de régression).

## État constaté du code (vérifié, pas supposé)

- `core/familles.py` (S142) est déjà **entièrement générique** : une liste `FAMILLES` (slug,
  label, icone, ordre) + `grouper(briques)` qui répartit n'importe quelle liste de briques par
  `famille`, avec repli automatique (icône 📦, label capitalisé) pour tout slug non enregistré.
  Contrairement à ce qu'indiquait une mémoire plus ancienne ("S142 catégories — PLANIFIÉ"),
  cette fonctionnalité est **déjà livrée et utilisée** par `core/routers/systeme.py`
  (`/briques?grouper=famille`) et rendue dans `core/routers/dashboard.py` (JS front, groupes
  affichés avec icône+label).
- Aucune autre partie du code ne teste ou ne dépend de la valeur `"metier"` du champ `famille`
  de `geo` (vérifié par recherche sur tout le repo) — retagger `geo` est donc un changement de
  donnée pur, sans effet de bord fonctionnel.

## Changements

1. **`core/familles.py`** — ajouter une entrée à la liste `FAMILLES` :
   ```python
   {"slug": "veille", "label": "Veille", "icone": "🔭", "ordre": 6},
   ```
   Les familles dont l'`ordre` est ≥ 6 aujourd'hui (`metier`: 6, `dev`: 7) glissent d'un cran
   (`metier` → 7, `dev` → 8) pour garder `veille` juste avant les applications métier dans
   l'ordre d'affichage du dashboard.

2. **`briques/geo/manifest.json`** — `"famille": "metier"` → `"famille": "veille"`. Seul ce
   champ change ; aucune capacité, route, port ou dépendance n'est modifiée.

## Effet attendu

- `GET /briques?grouper=famille` renvoie un groupe `veille` (label « Veille », icône 🔭)
  contenant `geo`, et un groupe `metier` qui ne contient plus `geo`.
- Le dashboard affiche automatiquement une nouvelle section « 🔭 Veille » (le rendu JS itère
  déjà sur le résultat groupé — aucune modification du template nécessaire).
- Le futur spec « brique RSS veille informationnelle » n'aura qu'à déclarer
  `"famille": "veille"` dans son propre manifest pour rejoindre ce même groupe.
- Aucun changement de comportement de `geo` lui-même (capacités, routes, tests) — la brique
  continue de tourner exactement comme avant sur le HP.

## Tests / vérification

Pas de nouveau test unitaire : la logique de groupement (`familles.grouper`) est générique et
déjà exercée par l'usage existant des autres familles. Vérification manuelle après
implémentation :
- `curl http://localhost:5100/briques?grouper=famille` (ou l'équivalent HP) : le groupe
  `veille` existe et contient `geo` ; le groupe `metier` ne contient plus `geo`.
- Dashboard : la section « 🔭 Veille » apparaît, la tuile `geo` y est cliquable comme avant.

## Hors périmètre (explicitement)

- Extraction de la veille informationnelle (RSS→résumé→audio) hors de Forge en nouvelle
  brique — spec séparé à venir.
- Tout mécanisme de démarrage/arrêt à la demande des sous-briques (« Sprint Sablier ») — idée
  encore non planifiée, mentionnée ici seulement comme direction cohérente.
- Toute modification du code fonctionnel de `briques/geo`.
