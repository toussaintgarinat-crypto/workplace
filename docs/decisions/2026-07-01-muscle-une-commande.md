# Décision — Ajouter un « muscle » (nœud de calcul) en UNE commande

- **Date** : 2026-07-01
- **Statut** : ✅ **Adopté** (implémenté S131 — `bootstrap.sh` + `POST /noeuds` persisté + Gateway auto — cf. `docs/sprints/S131-muscle-une-commande.md`)
- **Portée** : simplifier l'ajout d'un ordinateur (grosse RAM/VRAM) au pool de calcul (« le Muscle »)
- **Fichiers liés** : `briques/calcul/` (parc de nœuds), `core/muscle.py` (client Cœur),
  `GUIDE-mesh-netbird.md` partie F, `docs/decisions/2026-07-01-acces-distant-netbird.md` (le mesh)

> **But de ce document** : figer *pourquoi* on inverse le sens de l'inscription (le muscle
> s'annonce, au lieu que le serveur le connaisse), garder les *alternatives prêtes*, et savoir
> *quand rebasculer* le jour où il y aura beaucoup de nœuds ou du multi-utilisateur.

---

## Contexte & problème

Rejoindre le **mesh NetBird** est déjà un one-liner (`curl … netbird … && netbird up`).
Mais **transformer une machine en muscle utilisable** reste 100 % manuel côté serveur (la VM HP) :

1. Trouver à la main l'**IP mesh** + la **MAC** du nouvel ordi ;
2. Éditer à la main le JSON `CALCUL_NOEUDS` dans le `.env` racine — la brique calcul charge
   l'env **une seule fois au boot** (`briques/calcul/main.py:33`, parc figé) ;
3. Déclarer le modèle dans le **Gateway LiteLLM** (sinon `modele_gateway` ne pointe sur rien) ;
4. `docker compose up -d --force-recreate` sur **gateway ET calcul**.

Quatre étapes manuelles, sur une **autre** machine que celle qu'on branche → friction réelle,
et source d'erreurs (mauvaise IP, JSON cassé, modèle absent du Gateway).

**Objectif** : brancher un muscle = **une seule commande collée sur la machine à brancher**,
zéro édition de fichier côté serveur.

---

## Décision

### Principe : inverser le sens de l'inscription (le muscle s'auto-annonce)
Aujourd'hui, le serveur « connaît » ses muscles (env figé). On inverse : **c'est le nouvel ordi
qui s'annonce** à la brique calcul. Le serveur n'a plus rien à savoir d'avance.

Une seule commande, collée sur la machine à brancher :
```bash
curl -fsSL https://<IP_MESH_HP>/muscle/bootstrap.sh | MUSCLE_KEY=<clé> SETUP_KEY=<netbird> sh
```

Le script (servi par la brique calcul) fait tout, tout seul :
1. **Rejoint le mesh** NetBird si pas déjà membre (`SETUP_KEY`) ;
2. **Auto-détecte un runtime LLM OpenAI-compatible déjà présent** (sonde `11434` Ollama /
   `1234` LM Studio / `8080` llama.cpp) → **le réutilise** ; sinon installe Ollama et sert un
   modèle **taillé à la RAM/VRAM détectée** ;
3. **S'auto-inscrit** auprès de la brique calcul (`POST /noeuds`) : IP mesh, MAC, modèle,
   capacité. Zéro `.env` à toucher.

### Ce qu'on construit (3 pièces — détail dans le sprint S131)
- **A. Endpoint d'inscription dynamique + persisté** : `POST /noeuds` (et `DELETE /noeuds/{id}`)
  sur la brique calcul, gardé par `MUSCLE_KEY`. Le parc est **sauvé sur disque**
  (`CALCUL_PARC_FILE`) et **fusionné** avec les nœuds encore déclarés par l'env → l'env reste
  valide, on ne casse rien.
- **B. Enregistrement Gateway automatique** : à l'inscription, la brique calcul enregistre le
  modèle dans LiteLLM (`POST /model/new`, master key) avec `api_base` = endpoint mesh du nœud,
  et renvoie le `model_name` stocké comme `modele_gateway`. **Re-poussé au boot** (idempotent).
- **C. Le script `bootstrap.sh`** servi par la brique + détection matériel + auto-détection du
  runtime existant.

Le reste marche **déjà** et n'est pas touché : élection par priorité (`noeud.ordre_election`),
sonde live, réveil WoL, tête de cascade côté Cœur (`core/muscle.tete_de_cascade`).

**Valeurs qui guident le choix** : souveraineté (rien chez un tiers), coût nul, honnêteté
(aucun nœud inventé — on ne l'inscrit que s'il répond vraiment), et « pas de dette molle »
tant qu'un seul utilisateur suffit.

---

## Alternatives considérées & quand basculer

| Approche | Effort | Persistance | Bon quand… |
|---|---|---|---|
| **Auto-inscription + Gateway dynamique** *(choisi)* | moyen (S131) | disque + re-push boot | on ajoute/retire des muscles souvent, une commande |
| Édition manuelle du `.env` *(actuel)* | nul (déjà là) | env figé | 1 muscle stable qu'on ne bouge jamais |
| Script qui SSH vers la VM et édite le `.env` à distance | faible | env | on tolère de donner un accès SSH au nœud (couplage fort, moins propre) |
| LiteLLM avec **base de données** (`store_model_in_db`) | fort (Postgres pour le Gateway) | DB LiteLLM | multi-utilisateur / beaucoup de modèles / cloud |
| Orchestrateur (k8s, Nomad) qui place les modèles | très fort | orchestrateur | flotte de nœuds, entreprise |

**Déclencheurs de bascule (à surveiller)** :
- **Le Gateway redémarre souvent** et re-pousser au boot devient fragile → passer LiteLLM en
  **mode base de données** (`store_model_in_db=true` + Postgres) pour une persistance native.
- **Beaucoup de nœuds / multi-utilisateur** → penser routage/quotas par tenant (épopée
  multi-tenant déjà anticipée), voire un vrai orchestrateur.
- **Auto-détection insuffisante** (on veut choisir finement le modèle par machine) → garder
  l'override manuel via variables d'env du script (`MUSCLE_MODELE=…`).

---

## Runbooks (comment ça s'utilisera)

### A. Brancher un nouveau muscle (cas nominal)
1. Créer/réutiliser une **setup key NetBird** réutilisable (app.netbird.io) et connaître la
   `MUSCLE_KEY` du stack.
2. Sur la machine à brancher, coller :
   `curl -fsSL https://<IP_MESH_HP>/muscle/bootstrap.sh | MUSCLE_KEY=<clé> SETUP_KEY=<netbird> sh`
3. Vérifier côté dashboard ⚙ **Cerveau** : la tuile muscle affiche le nouveau nœud 🟢/🌙.

### B. Débrancher un muscle
`curl -X DELETE https://<IP_MESH_HP>/muscle/noeuds/<id> -H "X-API-Key: <MUSCLE_KEY>"`
(ou débrancher la machine : il tombera 🔴 puis pourra être purgé).

### C. Forcer un modèle précis (override de l'auto-détection)
Ajouter `MUSCLE_MODELE=qwen2.5:14b` (et éventuellement `MUSCLE_PRIORITE=10`) devant le `sh`.

### D. Après un redémarrage du Gateway
Rien à faire en théorie : la brique calcul **re-pousse** ses modèles dans LiteLLM au boot
(idempotent). Sinon `POST /noeuds/republier` (déclenchable par l'horloge du Cœur).

---

## Limites connues (honnêtes)

- **Persistance LiteLLM sans base de données** : `POST /model/new` est **en mémoire** → perdu
  au `recreate` du Gateway. Parade retenue = re-pousser au boot depuis le parc sur disque
  (idempotent). Ce n'est pas une vraie persistance ; le vrai fix = LiteLLM en mode DB (cf.
  déclencheur de bascule).
- **Le script installe des logiciels** (Ollama) et sert un port : il demande `sudo` et, pour
  Ollama, un `pull` de plusieurs Go. L'auto-détection réutilise l'existant pour l'éviter quand
  c'est possible.
- **Auto-détection du modèle = heuristique** par RAM/VRAM ; elle ne juge pas la *qualité*.
  Override manuel prévu (runbook C).
- **Réveil (WoL) toujours manuel à préparer** : l'auto-inscription remplit l'endpoint et la
  MAC, mais faire dormir/réveiller la machine reste conditionné au BIOS + carte réseau (cf.
  ADR mesh, partie D).
- **Sécurité** : `bootstrap.sh` est distribué → `MUSCLE_KEY` **obligatoire** pour s'inscrire,
  et policy NetBird stricte. Rien exposé hors mesh.

---

## Références
- `docs/sprints/S131-muscle-une-commande.md` — le plan d'implémentation tâche par tâche.
- `docs/decisions/2026-07-01-acces-distant-netbird.md` — le mesh (fondation).
- `GUIDE-mesh-netbird.md` partie F — la procédure manuelle actuelle (à remplacer).
- `briques/calcul/` — le parc de nœuds ; `core/muscle.py` — le client du Cœur.
