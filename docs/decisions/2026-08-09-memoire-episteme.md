# Décision — Un souvenir porte sa confiance, et le LLM ne peut jamais l'écrire

- **Date** : 2026-08-09
- **Statut** : ✅ Adopté (S224)
- **Portée** : brique `memoire` (5600) et le routage d'outils du Cœur
- **Fichiers liés** : `briques/memoire/main.py`, `briques/memoire/manifest.json`,
  `core/graphe_apprentissage.py`, `briques/memoire/test_episteme.py`
- **Origine** : veille sur [LIA-Assistant](https://github.com/jgouviergmail/LIA-Assistant)
  (AGPL-3.0 — **idée reprise, aucun code**), leur ADR-079 et `docs/technical/JOURNALS.md`.
  Backlog : `docs/sprints/S221-S226-emprunts-lia-assistant.md`

---

## Le problème

Un souvenir était un texte avec un **score de pertinence de recherche**. Rien ne distinguait
« hypothèse jamais vérifiée » de « règle confirmée dix fois ». La conséquence n'était pas
théorique : `core/graphe_apprentissage.py` construit le boost de routage d'outils en
pondérant **tous** les souvenirs à égalité — une note fausse écrite une fois pesait donc
autant qu'un fait établi.

## La décision

Trois champs sur le souvenir : `preuves`, `contradictions`, `confiance`. Et une règle qui
est tout l'intérêt du dispositif :

> **L'appelant ne peut jamais écrire un compteur ni un niveau de confiance.**
> Il n'émet qu'un signal — `preuve` ou `contradiction` — via
> `POST /souvenir/{id}/signal`. Le service incrémente, et `confiance` est une fonction
> **déterministe** des compteurs.

Un LLM ne peut donc pas s'auto-attribuer de la certitude sur un souvenir qu'il vient
d'inventer. `memoire_signaler` n'expose que `signal` (énumération fermée) — un test du
manifeste interdit explicitement qu'un paramètre `preuves`/`contradictions`/`confiance`
y apparaisse un jour, parce que ce seul ajout ferait tomber toute la garantie.

`confiance` est bien **écrite** dans le frontmatter, pour rester lisible à qui l'inspecte à
la main — mais elle n'est **jamais relue** : `_episteme()` la recalcule toujours depuis les
compteurs. Une valeur trafiquée n'a donc aucun effet.

### Le barème, et pourquoi il penche

| Compteurs | Confiance |
|---|---|
| neuf (0/0) | moyenne — un souvenir neuf est une hypothèse |
| contredit ≥ appuyé | **faible** |
| appuyé − contredit ≥ 2 | haute |

Dès qu'un souvenir est contredit au moins autant qu'appuyé, il retombe à « faible ». On
préfère sous-pondérer un fait vrai que sur-pondérer un fait faux.

Dans le graphe de routage : faible ×0,3, moyenne ×1, haute ×1,8. Sous-pondéré, **pas
ignoré** — un souvenir a pu être contredit à tort.

## Stockage : pas de migration

Les trois champs vivent dans le `frontmatter` du nœud Memory, une méta libre déjà en place.
Migration purement additive : aucun changement de schéma, les souvenirs d'avant S224 restent
lisibles et retombent sur le défaut neutre. `_episteme()` est volontairement tolérante
(compteur négatif, texte à la place d'un entier, champ absent) : un frontmatter corrompu ne
lève jamais et ne fabrique jamais de certitude.

## Limites assumées

- **L'incrément n'est pas transactionnel.** Le backend Memory n'expose pas d'incrément :
  le cycle lecture → +1 → écriture passe par deux appels HTTP. Un verrou par identifiant
  sérialise les signaux **dans le processus** de la brique, ce qui couvre le cas réel (une
  brique = un processus), mais ce n'est pas une garantie de base de données. À réviser si
  la brique passe un jour en plusieurs répliques.
- **`/rappeler` n'expose pas la confiance.** La recherche du backend Memory renvoie un
  `SearchResult` qui ne porte pas le `frontmatter` (requête SQL dédiée). L'exposer
  demanderait de modifier le sous-projet Memory vendored ; `/souvenirs` (la liste) le porte,
  et c'est précisément la route qu'utilise `graphe_apprentissage.charger_graphe`, donc le
  chemin qui compte pour la pondération fonctionne.
- **Rien ne produit encore de signal automatiquement.** L'auto-évaluation différée de LIA
  (juger au tour T+1 une directive émise au tour T) n'est pas reprise : la route existe et
  le LLM peut l'appeler quand les faits tranchent, mais aucune boucle ne le fait à sa place.
  C'est le prolongement naturel, pas ce sprint.

## Ce qu'on n'a délibérément pas repris

La stratification L0→L3 complète de LIA, sa consolidation périodique par clustering
thématique, et la compilation d'un « portrait utilisateur » réinjecté dans sept flux. C'est
leur gros morceau et il n'a de sens qu'à leur volume de conversation. Le sous-ensemble
ci-dessus a de la valeur seul.
