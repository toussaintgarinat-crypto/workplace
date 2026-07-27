# S201 → S209 — Backlog issu de l'audit du 2026-07-27

> **✅ TOUS EXÉCUTÉS le 2026-07-27** — commits `2c9b3b2` (S201), `710dc72`+`8085fcd` (S202),
> `0c00745`+`f85ec01` (S203), `b6b47bd` (S204), `9b9b63b`+`3f43558` (S205/S206), `01255ef`
> (S207), `74135ed` (S208), `7bbc699` (S209).
>
> **Ce que l'exécution a corrigé dans ce document :**
> - **L'ordre S205 → S206 était le mauvais.** Le blocage de S205 (« wheels qui ne compilent
>   pas ») venait de Python 3.14 **en local**, alors que les conteneurs tournent en 3.12/3.13.
>   Tester en conteneur débloquait donc S206 tout seul, et fournissait le filet nécessaire pour
>   bumper les dépendances en sécurité. S206 a été fait en premier.
> - **S208 était mal décrit.** « Extraction par domaine » supposait un monolithe de logique ;
>   `dashboard.py` ne contient qu'UNE route et 3460 lignes de HTML embarqué. Le geste juste
>   était de sortir le gabarit dans un fichier, pas de découper des domaines.
> - **S205 cachait un défaut plus grave que ses 29 écarts** : le regex de `audit_deps.py`
>   ignorait les extras pip, donc 23 briques sur 38 échappaient à l'audit sans que rien ne le
>   signale. Le compte réel était 44.
>
> Le document ci-dessous est conservé **tel qu'écrit avant exécution**, pour garder trace de
> ce qui avait été anticipé — et de ce qui ne l'avait pas été.

Neuf sprints qui soldent la dette relevée pendant le tour de la solution du 2026-07-27.
Trois problèmes trouvés ce jour-là (timeout du digest, modèles gratuits figés, sources RSS
mortes) ont été corrigés et déployés à chaud — commits `1d58233`, `eee78cb`, `f16dabe`. Ce
document couvre **ce qui reste**.

**Ordre = risque décroissant, pas effort croissant.** S201 à S204 corrigent des choses qui
cassent ou qui vont recasser ; S205 à S207 remettent le filet en place ; S208 et S209 sont du
confort. Chaque sprint est indépendant : on peut en sauter un sans bloquer les suivants, sauf
mention explicite.

Un plan d'implémentation détaillé (`docs/superpowers/plans/`) reste à écrire **au moment
d'attaquer** chaque sprint, pas d'avance — c'est le motif du repo.

---

## S201 — Timeouts fantômes des autres proxies du Cœur

**Pourquoi maintenant.** C'est exactement le bug de P1, non corrigé ailleurs. Preuve par
asymétrie, sans avoir à reproduire : `briques/studio/main.py:1021` accorde **180 s** à son
appel aval, mais `core/routers/studio_proxy.py` plafonne à **60 s**. Toute route qui dépasse
la minute rend donc un 500 à l'utilisateur alors que le travail aboutit — silencieusement,
comme le digest pendant des semaines.

**Périmètre.**
- `core/routers/studio_proxy.py` et `core/routers/atelier_images_video_proxy.py` : passer au
  timeout **par chemin**, motif `_timeout_pour()` de `atelier_veille_proxy.py`.
- Inventorier les routes lentes de chaque brique aval (`grep timeout=` dans son `main.py`) et
  aligner le proxy sur la valeur de la brique, jamais l'inverse.
- Vérifier au passage `briques/atelier-images-video/main.py:98` (60 s) : la génération vidéo
  passe-t-elle par là ? Si oui, c'est la brique qu'il faut relever, pas seulement le proxy.

**Critère de sortie.** Pour chaque proxy, un test qui verrouille le timeout choisi par route
(motif `test_routes_lentes_ont_un_timeout_long`). Aucune route lente ne reste sous le timeout
de sa brique aval.

**Effort.** ~2 h. **Dépend de.** Rien.

---

## S202 — Gateway : empêcher la récidive des modèles figés

**Pourquoi maintenant.** P2 a été soldé (liste resynchronisée, `make start` câblé), mais la
cause structurelle demeure : le lanceur racine et le déploiement HP font un
`docker compose up -d` **générique** qui ne passe pas par le Makefile de la brique. Après un
déploiement direct, `make sync` reste manuel — donc oubliable. La liste avait pourri 51 jours
sans que rien ne l'annonce, et 1746 lignes d'erreur / 24 h n'ont alerté personne.

**Périmètre.**
- Rendre le sync effectif quel que soit le chemin de démarrage : entrypoint du conteneur,
  tâche planifiée côté horloge, ou hook dans le runbook HP — à trancher en ADR
  (`docs/decisions/`), les trois ont des contreparties.
- Rendre l'obsolescence **visible** : exposer la date de la dernière synchro (le marqueur
  `AUTO-FREE-MODELS-START` la contient déjà) dans `/sante` de la brique, et alerter au-delà
  d'un seuil.
- Décider du sort des `NotFoundError` : un modèle mort doit sortir de la cascade, pas être
  retenté en boucle.

**Critère de sortie.** Un modèle gratuit retiré du catalogue OpenRouter est constaté
automatiquement — sans qu'un humain lise les logs.

**Effort.** ~1 jour (dont l'ADR). **Dépend de.** Rien.

---

## S203 — Veille : réparer les sources et permettre de les rallumer

**Pourquoi maintenant.** Le compteur livré en P3 a révélé que la thématique **Cosmétique est
morte à 100 %** — 5 sources sur 5. La veille cosmétique ne remonte plus rien, et ça ne se
voyait nulle part :

| Source | Panne |
|---|---|
| Annel - Blog Réglementaire | DNS mort (`Name or service not known`) |
| COSMED | certificat SSL invalide (hostname mismatch) |
| CosmeticOBS | 405 Not Allowed |
| Care Europe | 404 |
| Commission Européenne - Cosmétiques | 404 |

**Périmètre.**
- Retrouver les flux RSS actuels de ces cinq sites (ou acter qu'ils n'en publient plus) et
  remplacer les URLs.
- Ajouter un **toggle `enabled` par source** (`PATCH /sources/{id}/actif`) + le bouton dans
  l'atelier. C'est le préalable bloquant à toute désactivation automatique : aujourd'hui
  `enabled` n'est piloté qu'au niveau d'une thématique entière, donc une source éteinte
  automatiquement serait impossible à rallumer, et rallumée à tort au prochain « Reprendre ».
- **Alors seulement**, décider si la mise en veille automatique au seuil est souhaitable.
- Vérifier le cas COSMED : un `verify=False` ciblé est-il acceptable, ou la source est-elle à
  abandonner ? Décision de sécurité, à tracer.

**Critère de sortie.** Un digest « Cosmétique » non vide est produit ; une source peut être
éteinte et rallumée depuis l'atelier.

**Effort.** ~1 jour, dont une part de recherche des flux (non compressible).
**Dépend de.** Rien. Le toggle conditionne la désactivation auto, pas l'inverse.

---

## S204 — `memoire` : configuration qui refuse les variables en trop

**Pourquoi maintenant.** `Settings` de `memoire` est en `extra_forbidden` : la présence de
`memoire_db_password` dans l'environnement fait échouer la validation au démarrage
(`ValidationError: Extra inputs are not permitted`). Les tests de la brique plantent
là-dessus. En production le conteneur tourne, donc la variable n'y est pas — mais **toute var
d'env ajoutée au `.env` racine dont le préfixe correspond ferait crasher le backend au boot**,
et la famille de pièges `env shadow` a déjà mordu deux fois sur ce repo.

**Périmètre.**
- Trancher entre `extra="ignore"` et déclarer explicitement le champ — l'un des deux, pas les
  deux, avec la raison écrite dans le code.
- **Auditer les autres briques** pour le même motif : c'est l'occasion de savoir combien de
  services ont un `Settings` fragile, pas seulement de réparer celui-ci.

**Critère de sortie.** `cd briques/memoire && pytest` passe ; aucune brique ne crashe au boot
sur une variable d'environnement surnuméraire.

**Effort.** ~3 h. **Dépend de.** Rien.

---

## S205 — Aligner les dépendances (`make deps-audit` au vert)

**Pourquoi maintenant.** 29 écarts vs `constraints-workplace.txt`, et la cible sort en erreur —
donc elle n'est vérifiable par personne, ni humain ni CI. `fastapi` s'étale de **0.111.0**
(`audit`, `donnees`, `generateur`) à **0.139.2** (`synopsis`) ; `oria` porte `pydantic` 2.13.4
là où la contrainte dit 2.7.1. Un écart majeur de pydantic entre briques, c'est de la
divergence de comportement de validation à travers le mesh.

**Périmètre.**
- Décider brique par brique : aligner sur la contrainte, ou relever la contrainte parce que la
  brique a une bonne raison d'être en avance (`oria`, `synopsis` semblent volontairement
  récentes — à confirmer, pas à supposer).
- Traiter le paquet contraint mais non épinglé (`audit-fichiers httpx`).
- Rebuild + smoke de chaque brique touchée : un bump de `fastapi` sur 10 briques n'est pas
  gratuit.

**Critère de sortie.** `make deps-audit` sort en 0. Tous les conteneurs touchés healthy.

**Effort.** ~1,5 jour, l'essentiel étant la validation après rebuild.
**Dépend de.** Rien, mais à faire **avant** S206 (les tests de briques ont besoin de
dépendances cohérentes).

---

## S206 — Remettre un filet de test sur les 6 briques orphelines

**Pourquoi maintenant.** 6 briques sur 38 n'ont pas de test exécutable localement : `donnees`,
`ecoute`, `export`, `forge`, `memoire`, `standard-telephonique`. Le `best-effort` du Makefile
masque le trou — dont **forge**, la plus grosse brique du repo. Causes réelles :
`numpy`, `markdown`, `asyncpg`, `livekit` absents, et `/data` en lecture seule hors conteneur
pour `donnees`.

**Périmètre.**
- `requirements-dev.txt` par brique, ou exécution des tests **dans** le conteneur — trancher
  une fois pour toutes plutôt que brique par brique.
- Motif `core/conftest.py` (isolation de `/data`, déjà résolu pour le Cœur) à porter sur
  `donnees`.
- `make test-briques` doit **échouer** quand une brique casse, au lieu de l'avaler en
  « [ECHEC ou deps manquantes] » : aujourd'hui un vrai échec et une dépendance absente sont
  indiscernables.

**Critère de sortie.** `make test-all` distingue échec réel et environnement incomplet, et
passe au vert sur les 38 briques.

**Effort.** ~2 jours. **Dépend de.** S205 (S204 aussi pour `memoire`).

---

## S207 — Unifier la convention de santé

**Pourquoi maintenant.** Le Cœur répond sur `/health`, les briques sur `/sante`, et `gateway`
(4001) comme `agenda` (8400) ne répondent ni à l'un ni à l'autre. Toute sonde écrite de bonne
foi tombe à côté — c'est ce qui m'a fait croire le Cœur muet pendant l'audit.

**Périmètre.**
- Choisir la convention (`/sante` est majoritaire : 36 briques) et l'écrire dans
  `GUIDE-ajouter-une-brique.md`.
- Ajouter l'alias manquant partout, **sans retirer l'ancien chemin** : `oria-stack` et les
  healthchecks Docker pointent sur `/health`, une bascule sèche casserait les conteneurs.
- Étendre le smoke `tests/` pour vérifier la convention sur les 38 manifests.

**Critère de sortie.** `curl <brique>/sante` répond 200 sur les 38, y compris Cœur, gateway et
agenda.

**Effort.** ~4 h. **Dépend de.** Rien.

---

## S208 — Découper `core/routers/dashboard.py`

**Pourquoi maintenant.** 3527 lignes, soit **66 % de tout `core/routers/`** (5338 lignes sur
14 fichiers). Même famille que le monolithe `forge` (65 routers / 16k lignes) déjà acté comme
différé. C'est le fichier que tout sprint touchant l'UI du Cœur doit ouvrir.

**Périmètre.** Extraction par domaine, à iso-comportement, en s'appuyant sur les tests
existants (`core/test_dashboard.py`) comme filet. **Aucun changement fonctionnel** dans ce
sprint — sinon on ne saura pas ce qui a cassé.

**Critère de sortie.** Aucun fichier de `core/routers/` au-dessus de ~800 lignes ; les 503
tests du Cœur passent sans modification.

**Effort.** ~2 jours. **Dépend de.** Rien, mais à faire quand aucune feature n'est en vol sur
le Cœur — les conflits de merge seraient pénibles.

---

## S209 — Hygiène du dépôt et de l'infra

**Pourquoi maintenant.** Rien d'urgent, mais ça s'accumule et ça brouille la lecture.

**Périmètre.**
- `workplace_searxng` tourne sans healthcheck (seul conteneur du HP dans ce cas) — service
  secondaire de `briques/recherche/docker-compose.yml`.
- `.stale-pre-worktree-drafts-2026-07-15/` non suivi depuis 12 jours : archiver ou supprimer.
- 12 branches locales, plusieurs déjà mergées (`s181-acces-distant-cercle-prive`,
  `s182-chacun-son-agenda`, worktrees S171/S174/S186…) : élaguer.
- 358 Mo de `.venv-test` dans `briques/` (gitignorés, mais lourds) : les rattacher au choix
  fait en S206.

**Critère de sortie.** `docker ps` sans conteneur non-healthy ; `git branch` lisible.

**Effort.** ~2 h. **Dépend de.** S206 pour le point `.venv-test`.

---

## Récapitulatif

| Sprint | Objet | Effort | Bloque / dépend |
|---|---|---|---|
| S201 | Timeouts fantômes des proxies | 2 h | — |
| S202 | Gateway : récidive des modèles figés | 1 j | ADR à écrire |
| S203 | Veille : sources mortes + toggle par source | 1 j | — |
| S204 | `memoire` : Settings fragile | 3 h | — |
| S205 | Alignement des dépendances | 1,5 j | avant S206 |
| S206 | Filet de test des 6 briques | 2 j | après S204, S205 |
| S207 | Convention de santé | 4 h | — |
| S208 | Découpe de `dashboard.py` | 2 j | Cœur au calme |
| S209 | Hygiène dépôt & infra | 2 h | après S206 |

**Total ≈ 9 jours-homme.** S201 + S203 + S204 font une première salve courte (~1,5 j) qui
solde tout ce qui est visible par l'utilisateur.
