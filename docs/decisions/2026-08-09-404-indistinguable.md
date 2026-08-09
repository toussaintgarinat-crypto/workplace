# Décision — Une ressource d'autrui répond 404, jamais 403

- **Date** : 2026-08-09
- **Statut** : ✅ Adopté (S223)
- **Portée** : toutes les routes des briques qui désignent une ressource par identifiant
- **Fichiers liés** : `tests/test_fuite_existence.py` (le filet),
  `briques/memoire/memory/backend/app/dependencies.py`,
  `briques/agenda/backend/routers/{comments,presence}.py`,
  `briques/forge/forge/core/app/routers/{sessions,organizations}.py`
- **Origine** : veille sur [LIA-Assistant](https://github.com/jgouviergmail/LIA-Assistant)
  (AGPL-3.0 — **idée reprise, aucun code**), leur ADR-180 « silent blocking ». Backlog :
  `docs/sprints/S221-S226-emprunts-lia-assistant.md`

---

## La règle

Quand une route répond **404 pour un identifiant inconnu** et **403 pour un identifiant qui
existe mais appartient à quelqu'un d'autre**, le code de retour devient un oracle : on
énumère par balayage ce que possèdent les autres locataires, sans jamais lire une seule
donnée. « Ressource d'autrui » et « ressource inexistante » doivent être **indistinguables
de l'extérieur** : même code, même corps.

Un 403 reste légitime quand il ne désigne aucune ressource — appelant inconnu, mot de passe
incorrect, rôle insuffisant *sur une ressource dont l'accès est déjà établi*, garde SSRF,
chemin hors du bac à sable.

## Ce que l'audit a trouvé

L'audit d'isolation S183 avait vérifié qu'on ne **lit** pas les données d'autrui. Il ne
vérifiait pas qu'on ne peut pas **déduire leur existence** du code de retour. Cinq fuites,
toutes du même motif — un `404` pour l'inconnu suivi d'un `403` pour le non-autorisé :

| Brique | Route | Ce qu'on apprenait sans y avoir droit |
|---|---|---|
| memoire | accès à un espace | l'espace existe |
| agenda | modifier/supprimer un commentaire | le commentaire existe |
| agenda | partager sa présence sur un événement | l'événement existe |
| forge | renommer / lire une session | la session existe |
| forge | organisations | l'organisation existe |

Un cas plus retors dans `forge/organizations.py::remove_member` : la règle métier était
évaluée **avant** l'autorisation, donc un non-membre qui balayait les identifiants recevait
`400 Cannot remove owner` quand il tombait juste et `403` sinon — le code révélait à la fois
l'existence de l'organisation **et** l'identité de son propriétaire. L'autorisation passe
désormais en premier.

Le plus parlant : dans `briques/agenda`, **deux tests voisins encodaient la fuite** —
`test_partage_event_exige_participation` attendait 403 et `test_partage_event_inconnu_404`
attendait 404. Le couple documentait noir sur blanc la distinguabilité. Le premier a été
retourné.

## Le filet, et pourquoi il est manuel

On ne peut pas décider automatiquement si un 403 est légitime : « mot de passe incorrect »
l'est, « pas votre commentaire » ne l'est pas. `tests/test_fuite_existence.py` **inventorie**
donc les 403 du parc : chacun doit figurer dans `JUSTIFIES` avec sa raison. Un 403 ajouté ou
déplacé fait échouer le test tant que quelqu'un ne l'a pas classé — la question se pose au
moment de l'écriture plutôt qu'au prochain audit.

Un second test retire l'inverse : une justification qui ne correspond plus à aucun 403 réel
doit disparaître, sinon l'inventaire devient un décor. C'est lui qui a attrapé, à l'écriture
même de ce filet, **deux trous du scanner** : la forme multi-ligne
(`HTTPException(\n status_code=403,`) et la constante `HTTP_403_FORBIDDEN`, où `\b403\b` ne
matche pas parce que les underscores sont des caractères de mot.

Vérifié en réintroduisant volontairement une fuite corrigée : le filet échoue et nomme le
fichier et la ligne.

## Limite

Ce filet est **statique** : il lit le source, il n'interroge pas les briques en marche. Il
ne dit rien de la latence (une route qui répond plus vite pour l'inexistant reste un oracle
plus fin), ni des fuites par le corps de réponse quand les deux codes sont identiques mais
les messages diffèrent. Les cas corrigés ici alignent les deux, mais rien ne le vérifie
automatiquement.
