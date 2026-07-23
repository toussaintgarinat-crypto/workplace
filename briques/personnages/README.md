# Personnages — distribution & casting en API

Produit autonome : **créer une distribution de personnages structurés** (via LLM) et
**caster un script** en affectant des voix de façon **stable et agnostique au TTS**.
Extrait du Studio Oria (S47), sans aucune dépendance à Workplace/Oria.

Le moteur (proposition, structure, casting) est du Python pur ; seul l'appel LLM sort.

## Démarrer

```bash
docker compose up -d --build      # API sur http://localhost:5900
curl localhost:5900/sante
```

## Démos visuelles (front intégré, sans build)

- `/` — **Distribution & casting** : décrire une histoire → distribution, caster un script → voix stables.
- `/atelier` — **Atelier holistique** : *Depuis une naissance* (portrait calculé) et *Depuis un caractère* (recherche inverse). C'est la vitrine du moteur multi-traditions. On peut saisir une **ville** (bouton *Localiser* → géocodage `GET /geo`, OpenStreetMap) au lieu des coordonnées.

## Authentification

- Header `X-API-Key: <clé>` (ou `Authorization: Bearer <clé>`).
- Les clés acceptées sont dans `API_KEYS` (séparées par virgule). **Vide = mode ouvert**
  (dev/démo, tenant unique `public`). En production, renseigner `API_KEYS` :
  chaque clé est un **tenant** isolé (un client ne voit jamais les distributions d'un autre).

## LLM (proposition de personnages)

- Par défaut : **Gateway Workplace** (cost-first, modèles gratuits) via `GATEWAY_URL` / `GATEWAY_KEY`.
- **Bring-Your-Own-Key** : passer `"llm": {"base_url": "...", "cle": "...", "modele": "..."}`
  dans le corps (n'importe quel endpoint OpenAI-compatible). Aucun coût porté par le service.

## API

### Stateless (le moteur, rien n'est stocké)

`POST /distribution/proposer` — propose une distribution à partir d'une prémisse.
```json
{ "premisse": "Un détective dans une cité sous-marine en 2200",
  "langue": "français", "combien": 3,
  "voix_dispo": ["el_rachel","el_drew","el_clyde"] }
```
→ `{ "personnages": [{nom, role, description, voix?}], "casting_suggere": {...} }`

`POST /casting` — affecte des voix aux intervenants d'un script, **de façon stable**.
```json
{ "personnages": [{"nom":"Aria"},{"nom":"Vorn"}],
  "repliques": [{"perso":"ARIA"},{"perso":"VORN"},{"perso":"NARRATEUR"}],
  "langue": "fr", "pool_voix": ["el_rachel","el_drew","el_clyde"] }
```
→ `{ "casting": {"ARIA":"el_rachel", ...}, "personnages": [...] }`

Les « voix » sont des **identifiants opaques** : ElevenLabs, Azure, OpenAI… au choix du client.
Un personnage connu garde **sa** voix d'un script à l'autre ; les intervenants non listés
(narrateur, figurants) reçoivent une voix tournante, de préférence non déjà attribuée.

### Holistique — génération de personnages multi-traditions (S49)

Moteur **100 % Python** (aucun LLM, aucune éphéméride externe) : calculs exacts,
interprétation de **divertissement**. Traditions couvertes : numérologie (gématrie
**A=1…Z=26** par défaut, ou pythagoricien — champ `systeme_numerologie`), astro occidentale
(Soleil / Ascendant / MC + **Lune** exacts ; Lune vérifiée à 0,001° contre l'exemple de
Meeus), astro chinoise (+ animal de l'heure), **védique** (rashi sidéral + **nakshatra**
lunaire), **égyptien**, **celte** (21 arbres gaulois, dont Châtaignier), **amérindien**
(totem), **maya** (Tzolkin).

Toutes ces traditions **votent** dans la synthèse (« cumul à travers les cultures ») : un
trait porté par plusieurs cultures ressort comme majeur.

`POST /holistique/traditions` — toutes les lectures dérivables de la fiche (étape brute).
```json
{ "prenoms":"Aria","nom":"Solis","date_naissance":"1990-09-05",
  "heure_naissance":"14:30","latitude":43.6,"longitude":1.44,"utc_offset":2.0 }
```

**Langue (S194)** : `langue_sortie` (`"fr"` par défaut ou `"en"`) sur `FicheHolistique` —
choisit la langue du portrait/empreinte **déterministes** (stats, archétype, pierre
d'équilibrage, récit, `significations.expliquer`). Même forme JSON dans les deux langues,
juste des valeurs traduites. Sans rapport avec `langue` de `LectureApprofondie` (texte
libre passé au LLM pour la réécriture littéraire, ex. `"français"`/`"english"`).

`POST /holistique/portrait` — **mode descendant** : fiche → tags → **stats**
(Charisme/Combativité/Sagesse/Créativité/Discrétion/Stabilité/Émotivité/Énergie) →
**archétype** + forces / faiblesse + **pierre d'équilibrage** (choisie selon la faiblesse) + récit.
→ `{ "traditions": {...}, "portrait": {...}, "empreinte": [{cle, valeur, sens, role}] }`
L'`empreinte` traduit chaque valeur calculée en **sens** (mots-clés) — c'est le « dictionnaire des données » (`significations.py`) : le portrait n'affiche pas que des étiquettes, il les explique.
La **date est requise** (les stats en dérivent) ; heure + coordonnées débloquent thème astral & védique.
Le front propose un bouton **🎲 Aléatoire** (date / heure / nom tirés au sort → personnage instantané).

`POST /holistique/recherche-inverse` — **mode montant** : on décrit un caractère,
le moteur renvoie les signes / nombres / **une date** qui maximisent l'overlap.
```json
{ "description": "guerrier colérique mais profondément spirituel et solitaire", "combien": 3 }
```
→ `{ cible, signes:[...], nombres:[...], autres_traditions:{...}, archetype, exemple_date, source_analyse, note }`
La **non-unicité est assumée** : ce sont DES pistes, pas une vérité unique.

L'analyse est d'abord **lexicale** (champ lexical étoffé + similarité `difflib`, hors-ligne, instantané). **Filet de secours** : si aucun trait n'est reconnu, la description est envoyée à un **LLM** (modèle gratuit via la Gateway par défaut, ou endpoint local/BYO en passant `llm:{base_url,cle,modele}`) qui la traduit en axes. `source_analyse` vaut `"lexique"` ou `"llm"`. Si le LLM échoue aussi, on reste honnête (« aucun trait reconnu », rien d'inventé).

> **Reste à venir** (vraie éphéméride Swiss Ephemeris → outils de build dans l'image) :
> planètes Mercure→Pluton et **Design Humain** (Type énergétique). Non livrés tant qu'on ne
> peut pas les calculer *exactement* — pas de Type inventé (honnêteté technique).

### Stateful (distributions persistées, cloisonnées par clé API)

| Méthode | Chemin | Rôle |
|---|---|---|
| POST | `/distributions` | créer une distribution |
| GET | `/distributions` | lister (résumé) |
| GET/PATCH/DELETE | `/distributions/{id}` | lire / modifier / supprimer |
| POST | `/distributions/{id}/proposer` | proposer des personnages cohérents (à ajouter) |
| POST | `/distributions/{id}/personnages` | ajouter une fiche |
| PATCH/DELETE | `/distributions/{id}/personnages/{pid}` | éditer / **renommer** (alias de série) / retirer |
| POST | `/distributions/{id}/casting` | caster un script + **persister les voix figées** |

Renommage : chaque personnage garde son **nom d'origine** (`nom_naissance`, figé) en plus du
nom affiché. Tu peux donc donner au même personnage cosmique un **nom de scène différent par
série** sans perdre son identité ni ses voix.

### Fiches cosmiques enregistrées (opt-in, cloisonnées par clé API)

| Méthode | Chemin | Rôle |
|---|---|---|
| POST | `/fiches` | enregistrer une fiche générée (snapshot complet ; `categorie` libre optionnelle) |
| GET | `/fiches` · `/fiches/{id}` | lister · lire (le listage expose `categorie` pour le regroupement) |
| PATCH | `/fiches/{id}` | **renommer** pour une série (garde `nom_naissance` + données) |
| PATCH | `/fiches/{id}/categorie` | **ranger** dans une catégorie libre (« Famille », « Collègues »… ; vide = non rangé) |
| DELETE | `/fiches/{id}` | supprimer |

La `categorie` est un texte libre choisi par l'utilisateur : le front groupe « Mes personnages
enregistrés » par catégorie (anti-scroll quand il y en a beaucoup), « Non rangés » en dernier.

## Configuration (env)

| Variable | Défaut | Rôle |
|---|---|---|
| `API_KEYS` | (vide) | clés acceptées ; vide = mode ouvert |
| `GATEWAY_URL` | `http://host.docker.internal:4001` | LLM par défaut |
| `GATEWAY_MODEL` | `free/google/gemma-4-31b-it` | modèle par défaut |
| `PERSONNAGES_DB` | `/data/personnages.db` | stockage (couche stateful) |

## Tests

```bash
python -m pytest -q     # moteur + stockage + API (LLM mocké)
```
