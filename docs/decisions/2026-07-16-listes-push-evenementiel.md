# Décision — Push des listes : la brique agenda émet directement (événementiel)

- **Date** : 2026-07-16
- **Statut** : ✅ Adopté (S176 — T5)
- **Portée** : notifications par personne sur ajout/cochage d'un article de liste de
  courses/tâches. Comment la brique agenda notifie les autres membres d'une liste.
- **Fichiers liés** : `briques/agenda/backend/services/notifications.py` (émission),
  `briques/agenda/backend/routers/list_items.py` (déclencheurs), `config.py`
  (`CONNEXION_URL`, `CONNEXION_KEY`).

> **But** : consigner *pourquoi* la brique agenda émet **elle-même** un push vers le pont
> `connexion` sur un événement de liste, au lieu de laisser le Cœur pousser sur une base
> temporelle comme il le fait pour les rappels d'événements (S174).

---

## Contexte

En S174, les rappels d'agenda sont poussés par le Cœur : `core/proactif.py::_check_agenda`
boucle périodiquement sur les événements à venir et, quand un rappel est **dû dans le temps**
(N minutes avant le début), POST vers `connexion /pousser` pour chaque participant. Le modèle
est **temporel** : le Cœur interroge l'agenda à intervalle régulier et décide quoi pousser.

S176 introduit un signal d'une autre nature : un article ajouté ou coché dans une liste
partagée. Ce signal est **événementiel et instantané** — il n'a pas d'échéance ; il se produit
au moment exact d'une action utilisateur, et l'on veut prévenir les autres membres **tout de
suite** (« Marina a ajouté du lait »).

## Alternatives considérées

1. **Poll du Cœur (comme S174)** — le Cœur interrogerait périodiquement l'agenda pour repérer
   les nouveaux articles/cochages et pousser. Problèmes : (a) latence liée à la cadence du
   poll (un cochage n'est pas « dû à une heure », il est immédiat) ; (b) il faudrait un
   curseur d'état « dernier article vu par personne » côté Cœur pour savoir *quoi* est
   nouveau — de l'état à maintenir, absent du modèle temporel actuel ; (c) couplage
   supplémentaire du Cœur à un détail de la brique.

2. **La brique émet directement** (choisi) — sur ajout/cochage, `list_items.py` appelle
   `services/notifications.py::notifier_membres`, qui POST **best-effort** vers
   `connexion /pousser` pour chaque autre membre. Réutilise **le même contrat** `/pousser`
   que le Cœur (le pont résout les canaux liés de chaque personne). Pas d'état, pas de poll,
   latence nulle.

## Décision

La brique agenda émet directement vers `connexion /pousser` sur les événements de liste
(`item.added`, `item.checked`). C'est une **dépendance sortante optionnelle et config-gatée** :

- Activée seulement si `CONNEXION_URL` est défini (repli honnête : no-op silencieux sinon,
  exactement comme `_pousser_messagerie` du Cœur quand la brique `connexion` est absente).
- `CONNEXION_KEY` fournit l'`X-API-Key` du pont si nécessaire.
- **Best-effort, ne lève jamais** : un push KO (pont injoignable) n'échoue pas la mutation.
- L'acteur n'est jamais notifié de sa propre action ; le nom affiché vient de `UserProfile`
  (S174), repli sur l'`user_id` brut.

## Conséquences

- La brique agenda gagne une dépendance **sortante** vers `connexion` — nouvelle par rapport
  à son statut de pure « surface de service » (cf. [ADR agenda-surface-de-service](2026-07-14-agenda-surface-de-service.md)),
  mais optionnelle, best-effort et sans état, donc sans compromettre l'isolation ni le boot.
- Le canal de notification reste **unique** (`connexion /pousser`), partagé avec les rappels
  du Cœur : une seule surface à faire évoluer (ex. push web S178).
- À documenter au déploiement : `CONNEXION_URL` / `CONNEXION_KEY` dans l'environnement de la
  brique agenda (README brique).
- Divergence assumée avec S174 (temporel côté Cœur) : les deux modèles coexistent car ils
  répondent à deux natures de signal (échéance vs action).
