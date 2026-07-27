# Décision — Modèles gratuits de la Gateway : API LiteLLM + horloge, plutôt que fichier YAML

- **Date** : 2026-07-27
- **Statut** : ✅ Adopté (S202)
- **Portée** : brique `gateway` (port 4001) et nouvelle brique `gateway-sync` (port 4002) —
  entretien de la liste des modèles gratuits OpenRouter
- **Fichiers liés** : `briques/gateway-sync/`, `briques/gateway/litellm_config.yaml`,
  `core/horloge.py`, `core/config_assistant.py::chaine_modeles`

> **But de ce document** : consigner *pourquoi* la liste des modèles gratuits quitte le
> fichier versionné pour vivre dans LiteLLM, *pourquoi* cela coûte un service de plus, et
> **quand** ce choix devra être remis en cause.

---

## En bref (l'état retenu)

- Les modèles `free/*` ne sont **plus** déclarés dans `litellm_config.yaml` : ils sont créés
  et supprimés à chaud via l'API de LiteLLM (`/model/new`, `/model/delete`), et persistés
  dans sa base Postgres (`gateway-db`) déjà présente.
- Une brique `gateway-sync` expose `POST /sync` et déclare une tâche d'horloge quotidienne
  dans son `manifest.json`. Elle synchronise aussi au démarrage.
- `litellm_config.yaml` ne garde que les modèles **stables** (payants, locaux, `go/*`), qui
  ne bougent pas et méritent d'être versionnés.

## Contexte & objectif

Le 2026-07-27, la Gateway crachait 1746 lignes d'erreur par 24 h, dont 48 `NotFoundError`
sur `qwen/qwen3-coder` : un modèle gratuit retiré du catalogue OpenRouter mais toujours
déclaré chez nous. La cause n'était pas le modèle, c'était le mécanisme d'entretien —
`sync_free_models.py` était **orphelin** : son docstring annonçait « lancé automatiquement
par `make start-gateway` », une cible qui n'a jamais existé. La liste avait figé au
2026-06-06, soit **51 jours**, sans que rien ne le signale.

L'objectif de S202 n'est donc pas de corriger une liste — c'est fait — mais de garantir
qu'elle ne puisse plus pourrir en silence.

## Décision

**Le sync pilote l'API de LiteLLM ; il ne réécrit plus le YAML. Il est déclenché par
l'horloge du Cœur, via une brique dédiée.**

Trois faits vérifiés ont forcé la main, dans cet ordre :

1. **Le montage du YAML est en lecture seule** (`docker inspect` → `rw=false`). Tout mécanisme
   qui écrit dans le fichier suppose de modifier le compose.
2. **LiteLLM expose un CRUD modèles** (`/model/new`, `/model/delete`, `/model/update`,
   `/model/info`) et possède déjà sa base Postgres. La liste peut donc changer **à chaud**,
   sans redémarrage — donc **sans accès au socket Docker**, le bloquant identifié au Sprint
   Sablier.
3. **`core/horloge.py` est déclaratif** : une brique déclare ses `taches` dans son manifest et
   l'horloge appelle un chemin HTTP sur *sa* base, résolue par `orchestrateur._brique_base`
   (donc par le `port` de son manifest). Le fichier pose explicitement que « le Cœur ne code
   en dur AUCUNE tâche métier ». La tâche doit donc être portée par une brique qui expose un
   endpoint — or l'image LiteLLM est officielle et n'expose que ses propres routes.

D'où le service supplémentaire : c'est la conséquence du point 3, pas une préférence.

**Corollaire non optionnel** : la section `AUTO-FREE-MODELS` doit disparaître du YAML. La
laisser ferait cohabiter deux sources de vérité — LiteLLM recharge son fichier au démarrage
et réintroduirait les modèles morts par-dessus l'état de la base.

## Alternatives écartées

**Entrypoint du conteneur.** Ne se déclenche qu'au (re)démarrage. Or le conteneur tourne 6 à
9 jours d'affilée : cela **n'aurait rien empêché** des 51 jours de dérive. Le catalogue
OpenRouter change en continu, pas au boot. S'y ajoutent le montage `:ro` et la nécessité de
dériver l'image officielle.

**Hook dans le runbook HP.** C'est de la documentation, donc oubliable — et c'est exactement
ce qui a échoué : un docstring annonçait déjà la marche à suivre, personne ne l'a lue, la
cible n'existait même pas. Répéter le mécanisme en espérant un autre résultat serait naïf.

**Cron système sur le HP.** Simple, mais hors du dépôt versionné, invisible depuis le
dashboard, et lié à une seule machine.

## Contreparties assumées

- **La liste des gratuits quitte git.** On perd la traçabilité des changements de catalogue.
  Jugé acceptable : la section auto-générée produisait un diff de 28 lignes à chaque passage
  sans que personne ne la relise, et un état auto-découvert n'a pas vocation à être versionné.
- **Une brique de plus** (39 au lieu de 38) dans le registre, `/sante-globale` et le
  dashboard. C'est aussi un bénéfice : si `gateway-sync` meurt, ça se voit — au lieu de
  disparaître comme le script orphelin.
- **Un déploiement neuf n'a aucun modèle gratuit tant que le premier sync n'a pas tourné.**
  Atténué en synchronisant au démarrage du service, pas seulement sur l'appel de l'horloge.

## Ce que ce choix ne traite pas

Le cooldown des modèles en échec est **indépendant** et traité séparément (`router_settings`
dans `litellm_config.yaml`) : entre deux syncs quotidiens, un modèle qui vient de mourir doit
sortir de la cascade tout de suite, sans attendre 24 h. Sans cela, le bruit reviendrait par
paquets d'une journée.

## À rouvrir si…

- **LiteLLM retire ou casse son API modèles** — on retomberait sur le fichier, et il faudrait
  alors résoudre le rechargement (donc l'accès Docker).
- **Un second service a besoin d'une tâche périodique du même genre** — `gateway-sync`
  deviendrait le mauvais endroit ; il faudrait un vrai ordonnanceur partagé plutôt qu'une
  brique par besoin.
- **La cadence quotidienne se révèle trop lente** — si des modèles meurent plusieurs fois par
  jour, c'est le cooldown qui doit porter la charge, pas le sync.
