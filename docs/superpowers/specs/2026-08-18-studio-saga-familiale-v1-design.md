# Design — Studio : V1 « saga familiale » (journal, lecture interactive, valeurs)

- **Date** : 2026-08-18
- **Portée** : brique `studio` (`briques/studio/studio.py`, `main.py`, `front.html` + nouveau `lecture.html`)
- **Décision préalable** : `docs/decisions/2026-08-18-studio-famille-compte-unique-portabilite-profil.md`
  (compte unique = famille, toute donnée propre à un enfant indexée par `profil_id`)

## Contexte

Suite au rapport stratégique « saga familiale évolutive » (conversation du 2026-08-18) et
à la décision de stockage famille, cette V1 resserre le périmètre à trois briques
concrètes, sans moteur de recommandation ni scores de relation (différés — voir
« Explicitement hors scope » ci-dessous) :

1. **Journal d'écoute/choix par enfant**, visible par le parent.
2. **Lecture interactive de l'arbre des choix** par l'enfant — un vrai écran où il choisit
   sa branche en écoutant, limité au contenu déjà écrit par le parent.
3. **Valeur suggérée par chapitre** (courage, empathie…), proposée par le Script Doctor,
   éditable par le parent.
4. Nom de famille cosmétique sur le panneau profils (pas une nouvelle entité).

Constat technique qui a façonné le périmètre : l'arbre des choix existant
(`POST /series/{id}/arbre`, `/arbre/{noeud_id}/jouer`, `/arbre/{noeud_id}/etendre`) est un
outil d'**auteur** — le parent construit et écrit l'arbre à l'avance dans l'atelier de
co-création. Il n'existait aucun écran où l'enfant choisit une branche en la vivant. Cette
V1 ajoute cet écran, en respectant la règle déjà en vigueur dans le Studio « un agent
PROPOSE, l'humain DÉCIDE » : rien n'est généré en direct pendant que l'enfant écoute.

## 1. Modèle de données

### 1.1 Journal (nouveau)

Un fichier par profil, préfixé par le même id que le profil pour rester solidaire lors
d'un futur transfert de compte (cf. ADR) :

```
PROFILS_DIR/{profil_id}-journal.json
```

```json
{
  "profil_id": "abc123",
  "evenements": [
    {
      "id": "uuid4",
      "type": "chapitre_lu",
      "serie_id": "...",
      "serie_titre": "Les Brumes d'Eldovar",
      "episode_n": 4,
      "noeud_id": null,
      "choix": null,
      "quand": "2026-08-18T10:00:00+00:00"
    },
    {
      "id": "uuid4",
      "type": "arbre_choix",
      "serie_id": "...",
      "serie_titre": "Les Brumes d'Eldovar",
      "episode_n": 5,
      "noeud_id": "n3",
      "choix": "Explorer la grotte",
      "quand": "2026-08-18T10:12:00+00:00"
    }
  ]
}
```

- Append-only. `serie_titre` et `choix` sont dénormalisés pour un affichage simple du
  journal sans recharger chaque série.
- Helpers `studio.py` : `_journal_path(profil_id)`, `_load_journal(profil_id)` (liste vide
  si le fichier n'existe pas encore), `_ajouter_evenement(profil_id, evenement)`
  (load → append → save, même motif que `_load_profil`/`_save_profil`).
- **Aucun champ n'est ajouté au fichier du profil lui-même** — le journal reste un fichier
  séparé (approche B retenue face à A/C, cf. discussion de conception).

### 1.2 Valeurs (nouveau)

Liste fixe dans `studio.py`, même motif que `CIBLES`/`CIBLE_GUIDE` :

```python
VALEURS = {
    "courage": "Courage", "honnetete": "Honnêteté", "respect": "Respect",
    "empathie": "Empathie", "entraide": "Entraide", "patience": "Patience",
    "perseverance": "Persévérance", "generosite": "Générosité",
    "tolerance": "Tolérance", "curiosite": "Curiosité",
    "responsabilite": "Responsabilité", "confiance": "Confiance",
    "solidarite": "Solidarité", "justice": "Justice", "liberte": "Liberté",
    "gratitude": "Gratitude",
}
```

Sur chaque épisode (`serie["episodes"][i]`) :
- `valeur_suggeree` : clé de `VALEURS` proposée par le Script Doctor (ou `null` si la
  suggestion a échoué).
- `valeur` : clé retenue, initialisée à `valeur_suggeree`, écrasable par le parent via
  PATCH. Les deux champs sont conservés séparément (pas juste un seul `valeur`) pour
  garder une trace de ce que l'IA a proposé vs. ce que le parent a choisi.

### 1.3 Nom de famille (nouveau, cosmétique)

```
COMPTES_DIR/{sha256(cree_par)[:16]}.json → {"nom_famille": "Famille Martin"}
```

Hashé (pas la clé en clair) pour ne pas exposer `cree_par` dans un nom de fichier listable.
Ce n'est **pas** l'entité `Famille` écartée par l'ADR : aucune donnée d'enfant dedans,
uniquement une étiquette d'affichage au niveau du compte.

## 2. Backend (`main.py`)

### 2.1 Journal — lecture

```
GET /profils/{profil_id}/journal   (scope cree_par via _profil_de, comme l'existant)
→ {"evenements": [...]}
```

### 2.2 Journal — écriture « chapitre écouté »

**Nouvel endpoint dédié, pas d'effet de bord sur l'existant.**
`GET /series/{serie_id}/episodes/{n}/adapte?profil_id=` (`episode_adapte`, main.py:516)
sert déjà à la fois à la prévisualisation par le parent (front.html, aperçu « lecture
adaptée ») et, dans cette V1, à l'écran enfant — y accrocher un effet de bord aurait
journalisé chaque prévisualisation du parent comme si l'enfant avait écouté. À la place :

```
POST /series/{serie_id}/episodes/{n}/marquer-lu
body: {"profil_id": "..."}
```
Appelé uniquement par `lecture.html`, une fois par chapitre affiché (jamais par le
panneau parent). Une relecture/rafraîchissement peut créer un doublon dans le journal —
accepté : un historique de lecture n'a pas besoin d'être strictement idempotent, contrairement
à un choix d'arbre (2.4) qui, lui, fait progresser l'histoire et doit rester unique par
navigation.

### 2.3 Lecture d'un nœud d'arbre (nouveau, lecture seule)

```
GET /series/{serie_id}/arbre/{noeud_id}/lire?profil_id=
```
- Retrouve le nœud (réutilise `S._trouver_noeud`), 404 si le nœud n'a pas encore de
  `script` (pas encore écrit par le parent).
- Retourne le texte adapté au profil (réutilise `S._adapter_cible`, même moteur que
  `episode_adapte`) + `noeud["choix"]` **tels quels, sans adaptation LLM** (ces libellés
  courts ont déjà été écrits en tenant compte de la `cible` de la série au moment de la
  génération du nœud — cf. `_noeud()` qui injecte déjà `_consigne_cible`, donc un 2e appel
  LLM par option serait un coût/une latence sans bénéfice réel) + l'audio de l'épisode
  matérialisé si déjà produit pour ce profil (`ep["audios"][profil_id]`).
- N'écrit rien, ne journalise rien (une simple relecture ne doit pas dupliquer
  l'événement — la journalisation a lieu au moment du choix, section suivante).

### 2.4 Choisir une branche (nouveau, cœur de la lecture interactive)

```
POST /series/{serie_id}/arbre/{noeud_id}/choisir
body: {"profil_id": "...", "choix": "Explorer la grotte"}
```
- Retrouve le nœud, cherche l'enfant correspondant à `choix` dans `noeud["enfants"]`.
- **Si l'enfant n'existe pas ou n'a pas de `script`** → `404` avec un message clair
  (« Cette suite n'est pas encore écrite »). Aucune génération à la volée — règle décidée
  explicitement pendant le brainstorming.
- Sinon : journalise l'événement `arbre_choix` (profil_id, serie_id, noeud_id du nœud
  choisi, `choix`, episode_n du nœud d'origine), retourne le nœud enfant (même format que
  2.3) pour enchaîner directement côté front.

### 2.5 Reprise de lecture

Pas de nouveau champ « dernière position ». Le front déduit le nœud courant du **dernier
événement `arbre_choix`** du journal pour ce couple (profil_id, serie_id) — évite une 2e
source de vérité qui pourrait diverger du journal.

### 2.6 Valeur suggérée

Nouvelle fonction interne `S._suggerer_valeur(serie, episode) -> Optional[str]` (appel
Script Doctor, réponse contrainte à une clé de `VALEURS` ou aucune). Appelée dans les
**3 points de création d'un épisode** (avant le `S._save(serie)` de chacun) :
- production normale d'un chapitre,
- `episode_express`,
- `jouer_noeud` (matérialisation d'un chapitre depuis l'arbre).

Si l'appel échoue (LLM indisponible) : `valeur_suggeree = None`, la création du chapitre
n'est **jamais bloquée** (même principe que l'échec d'adaptation audio en S231).

```
PATCH /series/{serie_id}/episodes/{n}/valeur
body: {"valeur": "courage"}   # ou null pour retirer
```

### 2.7 Nom de famille

```
GET  /famille   → {"nom_famille": "..." | null}
PATCH /famille  body: {"nom_famille": "..."}
```
Scope `cree_par` (même dépendance `cle_api` que le reste).

## 3. Frontend

### 3.1 `lecture.html` (nouveau, mode enfant)

Page statique séparée, servie par la même brique, ouverte avec `?serie=X&profil=Y` :
- Au chargement : lit le journal du profil pour ce `serie_id`, en déduit le nœud courant
  (dernier `arbre_choix`) ou démarre à la racine de `serie["arbre"]` si aucun historique.
- Affiche le texte adapté (+ lecteur audio si disponible) du chapitre courant, puis
  appelle `POST .../marquer-lu` une fois l'affichage fait (chapitres linéaires **et**
  nœuds d'arbre — les deux passent par ce même marquage, seul le franchissement d'une
  branche déclenche en plus l'événement `arbre_choix` via `/choisir`).
- Si le nœud a des `choix` **et** qu'au moins une branche est déjà écrite : 2 gros
  boutons. Un choix vers une branche non écrite est simplement **désactivé** (pas caché,
  pour que l'enfant comprenne que la suite existe mais n'est pas prête) plutôt que
  provoquer un 404 en cliquant.
- Sinon (fin de branche ou chapitre linéaire hors arbre) : pas de bouton de choix.
- Aucun contrôle d'auteur visible (pas de « cartographier », pas de JSON brut, etc.).

### 3.2 `front.html` (parent) — ajouts

- Onglet « Journal » dans le panneau d'un profil : liste chronologique des événements
  (date, série, n° de chapitre, choix fait le cas échéant) — lecture seule.
- Badge valeur sur chaque chapitre dans l'accordéon existant, éditable (select parmi
  `VALEURS`), pré-rempli par `valeur_suggeree` si `valeur` n'a jamais été fixée.
- Champ « Nom de la famille » en tête du panneau profils lecteurs (GET/PATCH `/famille`).

## 4. Gestion des erreurs

| Cas | Comportement |
|---|---|
| Branche pas encore écrite, l'enfant clique quand même | `404` API, front désactive déjà le bouton en amont (défense en profondeur) |
| Script Doctor indisponible lors de la suggestion de valeur | `valeur_suggeree=null`, chapitre créé normalement, parent peut choisir une valeur manuellement plus tard |
| `profil_id` inconnu ou n'appartenant pas à `cree_par` | `404`, réutilise `_profil_de` existant |
| Journal absent (premier événement) | traité comme liste vide, pas d'erreur |

## 5. Tests

Pattern du repo : offline sur les vraies fonctions, `test_*.py` à côté de `studio.py`.
- `_ajouter_evenement` / `_load_journal` : création, append, ordre chronologique, isolation
  entre deux `profil_id`.
- `POST .../choisir` : 404 propre sur branche non écrite ; succès + événement journalisé
  sur branche écrite ; pas de double-journalisation sur relecture (`GET .../lire`).
- `GET .../adapte` (prévisualisation parent existante) : aucun événement journalisé —
  seul `POST .../marquer-lu` écrit dans le journal.
- `_suggerer_valeur` : repli silencieux (`None`) si le LLM échoue, ne bloque pas la
  sauvegarde de l'épisode.
- Scoping `cree_par` sur `/profils/{id}/journal` et `/famille` (même gabarit que les tests
  d'isolation existants, `test_isolation_personne.py`).
- Pas de preuve LIVE Docker dans l'immédiat (régime différé du projet, cf. mémoire
  `regime-preuve-docker-differe`).

## Explicitement hors scope (différé, pas oublié)

- Moteur de recommandation du prochain arc (`Development Architect`).
- Scores de relation enfant↔personnage, mémoire de continuité au-delà du journal brut.
- Entité `Famille` multi-comptes (cf. ADR — déclencheurs de bascule non atteints).
- Génération à la volée d'une branche non écrite pendant que l'enfant écoute.
- Épisodes multi-participants (parent-enfant, fratrie) — §11.C et §12 du rapport
  stratégique, nécessitent leur propre design une fois cette V1 validée à l'usage.
