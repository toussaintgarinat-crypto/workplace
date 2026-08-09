# Décision — Une dizaine de métriques métier, scrutées sur une seule cible

- **Date** : 2026-08-09
- **Statut** : ✅ Adopté (S225)
- **Portée** : le Cœur (`/metrics`) et la pile d'observabilité du parc
- **Fichiers liés** : `shared/metriques.py`, `core/metriques.py`,
  `core/routers/systeme.py`, `outils/observabilite/` (compose, `prometheus.yml`,
  `alertes.yml`, tableau Grafana), `Lancer Workplace.command`, `MIGRATION-HP.md`
- **Origine** : veille sur [LIA-Assistant](https://github.com/jgouviergmail/LIA-Assistant)
  (AGPL-3.0 — **idée reprise, aucun code**). Backlog :
  `docs/sprints/S221-S226-emprunts-lia-assistant.md`

---

## Le problème

On avait de l'**état instantané** — `/sante` par brique, `pouls`, `proprioception`, le
journal JSONL des appels LLM — et aucune **série temporelle**. À 39 briques, ce qui se
dégrade lentement passe inaperçu. Deux cas vécus, tous deux découverts par hasard des
semaines après :

- les modèles gratuits de la Gateway figés **51 jours** ;
- une thématique de veille morte à **100 %** (5 sources sur 5).

Une métrique de fraîcheur aurait crié le deuxième jour.

## Trois décisions, et ce qu'on refuse avec

### 1. Une seule cible à scruter : le Cœur

On n'instrumente **pas** les 39 briques une par une. Le Cœur connaît déjà leur registre,
leur horloge (SQLite des tâches planifiées), leur catalogue de capacités et le journal
d'usage LLM — il agrège tout ça en un `/metrics`. Une cible à scruter est une cible à
maintenir. Ajouter une brique au `prometheus.yml` n'aura de sens que le jour où elle
exposera quelque chose que le Cœur ignore.

### 2. Le scrape ne fait AUCUN appel réseau

Tout vient du disque local ou de la mémoire du processus. Un `/metrics` qui sonderait les 39
briques deviendrait lent, puis timeout, puis **serait la cause de la panne qu'il doit
signaler**. La santé live reste le domaine de `/briques/{nom}/sante` et du pouls.

### 3. Une dizaine de métriques métier, pas 464 techniques

Le critère d'admission, pour une métrique comme pour une alerte : **pouvoir citer la fois où
on a découvert le problème trop tard**. LIA en aligne 464 sur 26 tableaux de bord ; un
tableau de bord que personne ne lit ne vaut pas mieux que pas de tableau de bord.

| Métrique | Question à laquelle elle répond |
|---|---|
| `workplace_tache_age_secondes` | depuis combien de temps cette tâche n'a-t-elle pas tourné ? |
| `workplace_tache_cadence_secondes` | …comparé à quoi ? (l'âge seul ne veut rien dire) |
| `workplace_tache_jamais_executee` | quelle tâche déclarée n'a **jamais** démarré ? |
| `workplace_tache_dernier_succes` | laquelle tourne mais échoue à chaque fois ? |
| `workplace_llm_cout_usd`, `workplace_llm_budget_ratio` | où en est l'argent réel ? |
| `workplace_outil_appels_total` / `_echecs_total` | quelle capacité échoue systématiquement ? |
| `workplace_capacites_jamais_appelees` | à quoi sert vraiment ce catalogue de 254 entrées ? |
| `workplace_validation_ecarts_total` | (S221) le LLM se trompe-t-il d'arguments ou d'enchaînement ? |

Deux refus de complaisance, qui comptent plus que la liste :

- **Une tâche jamais exécutée n'a pas d'âge.** On n'expose pas `0`, qui se lirait « toute
  fraîche » — exactement le contraire de la vérité. La métrique est absente et
  `workplace_tache_jamais_executee` dit pourquoi.
- **Un budget illimité n'a pas de ratio.** `0` se lirait « on ne dépense rien ».

`workplace_tache_dernier_succes` mérite un mot : sans elle, une tâche qui échoue à *chaque*
exécution reste invisible — son âge, lui, est toujours frais.

## Format : pas de `prometheus_client`

Le parc épingle ses dépendances brique par brique (`constraints-workplace.txt`) ; ajouter une
bibliothèque à 39 images pour concaténer des chaînes ne se justifie pas. `shared/metriques.py`
fait cinquante lignes et fait respecter les deux pièges du format écrit à la main :
`# HELP`/`# TYPE` **une seule fois par nom** (Prometheus rejette silencieusement un bloc
dupliqué), et **échappement des valeurs d'étiquette** — un nom de tâche vient d'un manifeste
écrit à la main, un guillemet dedans casserait le parsing de tout le scrape.

## Limites assumées

- **Les compteurs en mémoire repartent de zéro au redémarrage** du Cœur
  (`workplace_outil_*`, `workplace_validation_ecarts_total`). C'est la convention Prometheus
  pour un `counter`, `rate()` sait le gérer, et `workplace_demarrage_timestamp_secondes`
  date la remise à zéro. Conséquence à connaître :
  `workplace_capacites_jamais_appelees` se lit **depuis le dernier démarrage**, pas depuis
  l'installation — c'est une question à poser à Prometheus sur une fenêtre, pas au Cœur.
- **Pas de Loki ni de Tempo.** Logs et tracing distribué attendront ; on prend les métriques
  d'abord et on jugera après.
- **`/metrics` n'est pas authentifié**, comme `/sante` et `/capacites`. Il expose la dépense
  LLM et les noms de briques — rien de secret, mais c'est une surface de plus à ne pas
  publier hors du cercle privé.
- **Rien ne route encore les alertes.** Les règles sont écrites et évaluées par Prometheus,
  mais sans Alertmanager elles ne partent nulle part : elles se lisent dans
  `:9090/alerts`. Brancher une notification (Telegram, la brique `connexion`) est le
  prolongement naturel, pas ce sprint.

## Filet

`core/test_metriques.py` — 14 cas. La moitié porte sur le **format** (entête unique,
échappement, entiers sans décimale) parce que c'est là que se cassent les exportateurs écrits
à la main, et le reste sur les deux refus de complaisance ci-dessus. Le rendu complet est
vérifié contre les 40 manifestes réels du dépôt : 78 points de mesure, 0 ligne non conforme.
