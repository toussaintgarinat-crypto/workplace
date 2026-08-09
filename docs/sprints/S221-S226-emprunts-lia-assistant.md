# S221 → S226 — Emprunts à LIA-Assistant (2026-08-09)

> **État au 2026-08-09 — S221 à S225 CODÉS, TESTÉS, COMMITÉS** sur la branche
> `s221-s225-emprunts-lia`. Reste le LIVE HP (régime de preuve différé). S226 reste
> conditionnel et non scopé, par construction : c'est S221 qui doit fournir les chiffres.
>
> | Sprint | État | ADR |
> |---|---|---|
> | S221 | ✅ `683615f` | `docs/decisions/2026-08-09-validation-arguments-avant-appel.md` |
> | S222 | ✅ `d5c1631` | `docs/decisions/2026-08-09-gate-action-structurel.md` |
> | S223 | ✅ `fd8f965` | `docs/decisions/2026-08-09-404-indistinguable.md` |
> | S224 | ✅ `cbdbfe6` | `docs/decisions/2026-08-09-memoire-episteme.md` |
> | S225 | ✅ `c6a5d3d` | `docs/decisions/2026-08-09-observabilite-metriques-metier.md` |
> | S226 | ⏸ conditionnel — lire `/validation/ecarts` après quelques semaines d'usage | — |

Backlog **écrit, rien codé**. Issu de la lecture du dépôt public
[jgouviergmail/LIA-Assistant](https://github.com/jgouviergmail/LIA-Assistant) (README + `docs/technical/PLANNER.md`
+ `docs/technical/JOURNALS.md` — **pas** le code) confronté à l'état réel de `core/` et `briques/`.

## Contrainte de licence — à lire avant d'écrire une ligne

LIA est en **AGPL-3.0**, et l'AGPL se déclenche sur l'usage *réseau* : toutes nos briques sont exposées en
HTTP, donc la contamination serait totale, et elle casserait en plus `app-builder` (dépôt public Apache-2.0,
cf. S213). **Aucun fichier, aucun extrait, aucune traduction ligne à ligne de leur code n'entre dans ce
dépôt.** Ce qu'on reprend, ce sont des *idées d'architecture* documentées publiquement dans leurs ADR —
réimplémentées de zéro sur nos structures à nous (manifestes, registre, guardrails). Chaque sprint ci-dessous
est formulé en termes de nos fichiers, pas des leurs, précisément pour que ça reste vrai à l'écriture.

## Ce qu'on a déjà — ne pas refaire

Vérifié dans le code avant d'écrire ce backlog, pour éviter de payer deux fois :

| Idée LIA | Déjà chez nous | Verdict |
|---|---|---|
| ADR-216 plafond de dépense quotidien | `core/journal_usage.py` : `LLM_BUDGET_JOUR_USD`/`LLM_BUDGET_MOIS_USD`, alerte 80 %, **blocage 95 %** via `peut_appeler_payant()` | Rien à faire |
| ADR-048 routeur sémantique d'outils | `core/routage_outils.py` (S145) + boost par `core/graphe_apprentissage.py` | Rien à faire |
| Compaction / fenêtrage de contexte | `core/trimming.py`, `core/summarisation.py`, `core/cache_semantique.py` (S138) | Rien à faire |
| 217 ADR | `docs/decisions/` — la pratique est déjà posée, c'est le volume qui diffère | Rien à faire |
| Boucles d'outils qui tournent en rond | `core/guardrails_outils.py` (S143) — échecs répétés, lectures circulaires | Rien à faire |
| Psyche Engine (Big Five → 14 humeurs → 22 émotions) | — | **Écarté** : beaucoup de machinerie pour un réglage de ton que le prompt de persona d'Oria couvre déjà (`core/personas.py`, `core/profil_defaut.md`) |

**Ordre = risque décroissant.** S221 et S222 sont petits, autonomes, et ferment des trous qui existent
*aujourd'hui* dans le Cœur. S223 est de la sécurité pure et tient en une session. S224 et S225 sont des
chantiers moyens. S226 (le plan explicite, leur pièce maîtresse) est mis en dernier et conditionnel : il ne
vaut le coup qu'après S221, et seulement si S221 montre que le problème est réel.

Le spec détaillé + le plan d'implémentation (`docs/superpowers/specs/`, `docs/superpowers/plans/`) s'écrivent
**au moment d'attaquer**, pas d'avance — motif du repo.

---

## S221 — Valider les arguments d'outil contre le manifeste, avant l'appel HTTP

**Pourquoi maintenant.** Leur `PlanValidator` rejette un plan sur 14 catégories *avant* de l'exécuter. On n'a
pas de plan, mais on a exactement le même angle mort au niveau de l'appel unitaire : `_spec_depuis_capacite()`
(`core/outils.py:345`) fabrique bien un schéma function-calling à partir du manifeste — `type` + `requis` — et
le donne au LLM… puis **plus rien ne revérifie ce que le LLM renvoie**. Les arguments partent tels quels dans
la requête HTTP vers la brique, qui répond 422 ou pire, et la boucle repart pour un tour. C'est un aller-retour
réseau + un tour de LLM payés pour une erreur détectable localement en microsecondes.

Le point de branchement existe déjà et est propre : `Guardrail.before_call()`
(`core/guardrails_outils.py:42`) est **déjà** appelé avant chaque outil et sait déjà répondre
`allow | warn | block`. On ajoute une raison de bloquer, on ne crée pas de plomberie.

Les catégories de LIA qu'on peut couvrir immédiatement, sans toucher aux manifestes : outil inexistant au
catalogue (leur n°2), paramètre requis manquant (n°3), type ≠ manifeste (n°4). Celles qui demandent d'enrichir
le vocabulaire des manifestes : bornes numériques (n°5), regex/enum (n°6) — 6 manifestes en déclarent déjà
(`agenda`, `forge`, `memoire`, `studio`, `synopsis`, `voix`), donc le vocabulaire est à formaliser, pas à
inventer.

**Périmètre.**
- Un validateur pur (sans I/O, testable seul) : `(nom_capacite, args, registre) → (ok, liste d'écarts)`.
- Câblage dans `before_call` : un écart bloquant renvoie `block` avec un message **exploitable par le LLM**
  (« paramètre `expediteur` requis et absent »), pas un 422 opaque venu de la brique. C'est ce message qui
  permet au tour suivant de corriger au lieu de retenter à l'identique.
- Étendre le schéma des manifestes à `minimum`/`maximum`/`pattern`/`enum`, en repartant de ce que les 6
  manifestes concernés écrivent déjà — et propager la contrainte dans `_spec_depuis_capacite` pour que le LLM
  la voie *aussi* en amont (ceinture ET bretelles : le schéma guide, le validateur tranche).
- Compteur d'écarts par catégorie dans `core/journal_usage.py` : sans cette mesure on ne saura pas si S226 se
  justifie.

**Hors périmètre.** Les catégories de LIA qui n'ont de sens que sur un plan multi-étapes (dépendances
circulaires, forward reference, référence `$steps.X` inexistante, condition non-safe) — elles arrivent avec
S226 ou jamais. Pas de vérification de scope OAuth (leur n°7) : nos briques portent l'auth elles-mêmes.

**Critère de sortie.** Un appel d'outil avec un paramètre requis manquant ou d'un type faux est refusé par le
Cœur **sans qu'aucune requête HTTP ne parte vers la brique**, avec un message que le tour suivant du LLM sait
corriger. Test : sur les 253 capacités des 34 manifestes, le validateur accepte tous les appels valides connus
et rejette une batterie d'appels malformés.

**Effort.** ~2 jours. **Dépend de.** Rien.

---

## S222 — Un gate humain structurel, pas un gate de prompt

**Pourquoi maintenant.** C'est le trou le plus sérieux trouvé en confrontant leur doc à notre code, et il
existe aujourd'hui en production.

Notre gate d'action fonctionne ainsi : une capacité marquée `action: true` reçoit un paramètre `confirme` ; sans
lui, la brique renvoie le JSON de `_confirmation()` (`core/outils_communs.py:14`), dont le contenu est un
**texte qui demande poliment au LLM d'attendre l'accord de l'utilisateur**. Côté Cœur, `core/assistant.py:368`
se contente de `confirmation = '"confirmation_requise": true' in resultat` — un drapeau posé sur l'événement
SSE. Rien, structurellement, n'empêche le LLM de rappeler immédiatement le même outil avec `confirme=true`
dans le même tour, sans que l'humain ait jamais vu la question. **Le seul rempart est l'obéissance du modèle
au prompt.** Sur 253 capacités, **133 sont marquées `action: true`** — dont les envois de mail de la brique
prospection/démarchage (S169/S170).

LIA a exactement le même contrat mais le rend structurel : des seuils typés selon la nature de l'action, avec
une asymétrie qui est le vrai enseignement — **mutation en masse : seuil 1** (approbation obligatoire dès le
premier élément), lecture en masse : 5 (avis) puis 10 (obligatoire). Ils sont d'ailleurs honnêtes sur leur
propre dette : leur niveau « approbation de plan » est *actuellement auto-approuvé* (ADR-106), donc leurs 6
niveaux annoncés en font 5 réels.

**Périmètre.**
- Le Cœur tient l'état « accord donné » **côté serveur**, par conversation et par (capacité, cible) — pas dans
  l'historique de messages où le LLM est seul juge. Un appel avec `confirme=true` sans accord enregistré est
  refusé par le Cœur, pas par la brique.
- Seuils typés, réglables par env comme le reste de `guardrails_outils` : mutation → obligatoire dès 1 ;
  lecture en lot → avis puis obligatoire. Le manifeste porte déjà `action: true` ; y ajouter la distinction
  mutation/lecture est un enrichissement mineur du vocabulaire, cohérent avec S221.
- L'accord expire (fin de conversation, ou délai) — sinon on a juste déplacé le trou.

**Hors périmètre.** Pas de nouveau composant d'UI : le drapeau `confirmation` circule déjà dans le flux SSE et
`core/suggestions.py` sait déjà produire les boutons (S76, qui pose explicitement que les actions suggérées
« ne court-circuitent jamais le gate » — ce sprint rend cette phrase vraie autrement que par convention).
Pas de reprise des 6 niveaux de LIA : deux suffisent (mutation / lecture en lot).

**Critère de sortie.** Un test où le LLM appelle une capacité `action: true` avec `confirme=true` **sans que
l'utilisateur ait jamais répondu** : l'action ne part pas. Aujourd'hui, elle part.

**Effort.** ~3 jours. **Dépend de.** Rien (indépendant de S221, mais les deux touchent le même point d'entrée
`before_call` — les enchaîner évite un conflit).

---

## S223 — Fuite d'existence : 404 indistinguable

**Pourquoi maintenant.** Leur ADR-180 (« silent blocking ») pose la règle : une ressource qu'on n'a pas le
droit de voir renvoie **404 sur toutes les requêtes**, jamais 403 — sinon le code de statut confirme
l'existence de la ressource et l'identité de son propriétaire. On vient de brancher l'identité réelle
multi-tenant sur jeu-factions (S217) et l'isolation de 28 briques a été auditée (S183, cf.
`docs/rapport-s183-audit-isolation.md`) — mais cet audit vérifiait *qu'on ne lit pas les données d'autrui*,
pas *qu'on ne peut pas déduire leur existence du code de retour*. C'est le bon moment : le réflexe se grave
maintenant ou il faudra repasser sur 34 briques plus tard.

**Périmètre.**
- Passer en revue les routes multi-tenant : un accès à une ressource appartenant à un autre `cle_api`/tenant
  doit être indistinguable d'un accès à une ressource inexistante (même statut, même corps, même latence
  d'ordre de grandeur).
- Ajouter le cas au filet d'isolation existant plutôt que d'en créer un nouveau.

**Hors périmètre.** Les fonctionnalités de partage entre utilisateurs de LIA (peer connections, partage
libre/occupé d'agenda, relais assistant→assistant) — c'est une *fonctionnalité* qu'on n'a pas et dont rien
n'indique qu'on la veuille. Seule leur règle de sécurité est reprise.

**Critère de sortie.** Sur les briques multi-tenant, un test paramétré prouve que « ressource d'autrui » et
« ressource inexistante » sont indiscernables de l'extérieur.

**Effort.** ~1 jour + le temps de correction de ce qu'on trouve. **Dépend de.** Rien.

---

## S224 — Mémoire épistémique : confiance, preuves, contradictions

**Pourquoi maintenant.** Leurs journaux L0→L3 sont surdimensionnés pour nous, mais il y a dedans un mécanisme
petit et transposable tel quel. Chaque entrée porte `confidence` ∈ {low, medium, high}, `evidence_count`,
`contradiction_count`, et **le LLM ne peut jamais écrire ces compteurs** — il ne renvoie qu'un signal
(`evidence` | `contradiction`), que le service incrémente atomiquement. S'y ajoute l'évaluation différée : la
consigne émise au tour T n'est jugée qu'au tour T+1, quand on peut observer si elle a marché.

Chez nous, un souvenir (`briques/memoire/main.py:341`, `class Souvenir`) est un texte avec un score de
pertinence de recherche — rien qui distingue « hypothèse jamais vérifiée » de « règle confirmée dix fois ».
Conséquence directe et déjà visible : `core/graphe_apprentissage.py` construit son boost de routage en pondérant
**tous** les souvenirs à égalité, donc une note fausse écrite une fois pèse autant qu'un fait établi.

**Périmètre.**
- Trois champs sur le souvenir : `confiance`, `preuves`, `contradictions`. Migration additive, défaut neutre —
  les souvenirs existants restent lisibles.
- Une route qui n'accepte qu'un **signal** (`preuve` / `contradiction`) sur un id de souvenir, et incrémente
  côté serveur. Jamais d'écriture directe du compteur par un appelant LLM.
- Filtrage des ids inconnus à l'entrée (leur garde anti-hallucination : le LLM invente des UUID plausibles).
- Pondérer le boost de `graphe_apprentissage` par la confiance.

**Hors périmètre.** La stratification L0→L3 complète, la consolidation périodique par clustering, la compilation
d'un « portrait utilisateur » injecté partout. C'est leur gros morceau et il n'a de sens qu'avec leur volume de
conversation. Le sous-ensemble ci-dessus a de la valeur seul ; le reste attendra qu'on ait la preuve d'en avoir
besoin.

**Critère de sortie.** Un souvenir contredit deux fois voit sa confiance baisser sans qu'aucun LLM n'ait écrit
un compteur, et pèse mesurablement moins dans le routage d'outils.

**Effort.** ~3-4 jours (migration + brique + rebranchement du graphe). **Dépend de.** Rien.

---

## S225 — Observabilité : `/metrics` sur les briques + Grafana

**Pourquoi maintenant.** C'est le trou d'exploitation le plus large. On a des healthchecks (sprint hygiène
infra), un `/sante` par brique, `core/pouls.py` et `core/proprioception.py`, et le journal JSONL de
`journal_usage.py` — c'est-à-dire de l'**état instantané**, aucune **série temporelle**. À 39 briques, quand
quelque chose se dégrade lentement, on ne le voit pas : la mémoire du sprint « audit P1-P3 » en donne deux
exemples coûteux (modèles gratuits figés **51 jours** sans que personne le remarque, thématique Cosmétique
morte à 100 %). Une métrique d'âge aurait crié dès le deuxième jour.

Le seul Prometheus/Grafana du dépôt est celui, vendu avec, de `sip-stack/roomkit-visio/` — donc le savoir-faire
de câblage est là, mais rien ne couvre le stack Workplace.

Ce qu'il y a de bon à leur voler, ce n'est pas « 464 métriques et 26 dashboards » (démesuré, et l'inflation de
métriques est un piège en soi) : c'est leur choix de métriques **métier plutôt que techniques**. Leur exemple le
plus parlant : `journal_zero_injection_age_days` — depuis combien de temps un souvenir n'a servi à rien.
Transposé chez nous : depuis combien de temps une source de veille n'a rien remonté, une capacité n'a jamais été
appelée, un modèle de la Gateway n'a pas été resynchronisé.

**Périmètre.**
- Un exporter `/metrics` mutualisé dans le socle partagé (`shared/`), pour ne pas le réécrire 39 fois.
- Prometheus + Grafana dans le stack, avec le motif de compose déjà en place ailleurs dans le dépôt.
- **Une dizaine de métriques métier**, pas plus, choisies pour répondre à des questions qu'on s'est
  effectivement posées trop tard : fraîcheur (âge du dernier succès) par tâche planifiée du manifeste, coût LLM
  par étiquette, taux d'échec par capacité, capacités jamais appelées.
- Quelques alertes, sur la fraîcheur d'abord.

**Hors périmètre.** Loki et Tempo (logs et tracing distribué) : on prend les métriques d'abord, on jugera
ensuite. Pas de dashboard par brique — un seul, transversal.

**Critère de sortie.** Une source de veille qui cesse de produire déclenche une alerte de fraîcheur **avant**
qu'un humain le remarque — le scénario exact qu'on a raté deux fois.

**Effort.** ~1 semaine. **Dépend de.** Rien, mais gagne à passer après S221 (les compteurs d'écarts de
validation deviennent des métriques au lieu de lignes de journal).

---

## S226 — Plan explicite validé (conditionnel — à n'écrire que si S221 le justifie)

**Pourquoi c'est à part.** C'est la pièce maîtresse de LIA : au lieu d'un ReAct où le LLM appelle un outil,
regarde, rappelle, un planificateur émet **un plan JSON typé** (étapes, `depends_on`, références
`$steps.X.champ`, conditionnels, `for_each`), validé intégralement avant exécution, puis exécuté en vagues
parallèles `asyncio.gather()`. Ils annoncent 4 à 8× moins de tokens que ReAct.

Trois raisons de ne pas s'y jeter :

1. **Le chiffre est auto-déclaré.** « 4–8× », « 93 % de réduction » : leurs propres mesures, sans protocole
   publié ni charge de référence. Notre boucle actuelle (`core/assistant.py`, `core/orchestrateur.py`) n'est
   pas leur ReAct, et on a déjà pris une partie du gain autrement (trimming, cache sémantique, routage d'outils
   qui filtre le catalogue — S138/S145).
2. **C'est un changement de nature de la boucle d'inférence**, pas un ajout. Ça touche le streaming SSE, le
   gate humain (S222), les suggestions, le co-agent — c'est-à-dire tout ce qui a été stabilisé sur une
   quinzaine de sprints.
3. **S221 produit la donnée qui tranche.** Si les compteurs d'écarts montrent que le LLM se trompe surtout
   d'*arguments*, S221 suffit et S226 ne sert à rien. S'ils montrent qu'il se trompe d'*enchaînement* — appels
   séquentiels qui auraient pu être parallèles, réutilisation ratée d'un résultat précédent, aller-retours pour
   reconstruire un contexte — alors le plan explicite adresse un vrai problème et mérite son spec.

**Ce sprint n'a pas de périmètre écrit.** Il s'écrit après S221, chiffres en main. Si on l'écrit, la bonne
portée de départ est probablement le seul motif qui paie sûrement : `for_each` avec ses seuils (une collecte
puis N actions dérivées), qui est aussi exactement le cas dangereux visé par S222 — le mailing en lot.

---

## Résumé de l'ordre

| Sprint | Objet | Source LIA | Dépend de | Nature |
|---|---|---|---|---|
| S221 | Validation d'arguments contre le manifeste | PlanValidator (14 catégories, on en prend 5) | Rien | Petit, autonome |
| S222 | Gate humain structurel + seuils typés | Seuils HITL, ADR-106 | Rien (enchaîner avec S221) | Petit, ferme un trou réel |
| S223 | 404 indistinguable | ADR-180 | Rien | Très petit, sécurité |
| S224 | Mémoire épistémique | ADR-079 (sous-ensemble) | Rien | Moyen |
| S225 | Métriques + Grafana | Observabilité (10 métriques, pas 464) | Rien (mieux après S221) | Moyen-gros, infra |
| S226 | Plan explicite validé | PLANNER.md / ExecutionPlan DSL | S221 + décision de portée | Non scopé, conditionnel |
