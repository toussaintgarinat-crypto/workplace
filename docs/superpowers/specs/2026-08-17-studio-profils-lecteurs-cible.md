# Design — Profils lecteurs & adaptation par âge (brique `studio`, port 6060)

**Date** : 2026-08-17
**Statut** : validé, prêt pour plan d'implémentation

## Contexte

Aujourd'hui, chaque série a un champ `cible` unique (`studio.py:252-285`, public visé —
`0-3`/`4-6`/`7-9`/`10-12`/`13-17`/`adulte`) qui influence le prompt de génération de chaque
nouveau chapitre écrit (`_consigne_cible`, injectée à la création d'épisode). Ce réglage est
global à la série et non versionné par épisode : changer la cible ne modifie que les chapitres
écrits **après** le changement, sans trace de « à partir d'ici, cible = X ».

Besoin utilisateur : créer une série pour son fils maintenant, et à la naissance de sa fille,
que la **même série** (même canon narratif) soit lisible par les deux à leur niveau d'âge
respectif, en parallèle — pas une chronologie unique qui grandit avec un seul enfant, mais deux
adaptations d'âge simultanées de la même œuvre. Le nom `cible` de la série reste la cible de
**référence** (celle utilisée à l'écriture) ; le nouveau besoin porte sur une adaptation à la
**consommation** (lecture/écoute), pas sur la réécriture du canon.

Clarifications actées avec l'utilisateur pendant le brainstorming :
- Même histoire, même intrigue : l'adaptation par âge ne change que le ton/vocabulaire/longueur,
  jamais le contenu narratif (pas de version « bébé » qui coupe des sous-intrigues).
- Adaptation déclenchée **à la lecture/écoute**, jamais stockée — même principe que le mécanisme
  de traduction déjà en place (`_traduire`, `studio.py:338-362`, utilisé uniquement côté audio
  aujourd'hui, `main.py:1009-1014`). Pas de cache par (épisode, cible) : chaque lecture
  recalcule.
- L'adaptation s'applique **au texte affiché ET à l'audio** — contrairement à la traduction
  actuelle qui ne touche que l'audio (le texte à l'écran, `front.html:479`, reste aujourd'hui
  toujours la version de référence).
- Sélection « pour qui » via des **profils lecteurs nommés** (« Fils », « Fille »), pas un simple
  sélecteur de tranche d'âge brut à chaque fois — chaque profil porte sa propre cible, modifiable
  dans le temps (c'est le geste central : faire vieillir un profil au fil des années).
- Les profils sont **globaux à l'atelier, pas propres à une série** — créés une fois, réutilisés
  sur toutes les séries **d'une même identité** (voir isolation multi-tenant ci-dessous).
- Le front mémorise le dernier profil sélectionné (`localStorage`) et le réapplique par défaut à
  la prochaine ouverture d'un chapitre.
- Repli honnête si l'adaptation échoue (Gateway injoignable, JSON illisible) : texte de référence
  affiché tel quel + indicateur, jamais de blocage — même politique que `_traduire`.

## État constaté du code (vérifié, pas supposé)

- `studio.py:37-38` (`ATELIERS_DIR`) : une série = un fichier JSON, nommé par `serie["id"]`
  (`uuid.uuid4().hex`, `main.py:297`) — aucun risque de collision avec un nom de fichier fixe
  type `profils.json`.
- `studio.py:252-285` (`CIBLES`/`CIBLE_GUIDE`/`_consigne_cible`) : la table des tranches d'âge et
  leurs consignes de registre existe déjà et sera réutilisée telle quelle pour l'adaptation à la
  lecture — aucune nouvelle taxonomie d'âge à inventer.
- `studio.py:338-362` (`_traduire`) : motif de référence pour l'adaptation — appel Gateway en
  lot, JSON strict en entrée/sortie, repli honnête (texte d'origine + `ok=False`) sur échec ou
  incohérence de longueur.
- `main.py:978-1039` (`POST /series/{serie_id}/audio`, body `FaireEpisode`) : pipeline actuel —
  script → découpe en répliques JSON (appel Gateway, `main.py:989-998`) → traduction éventuelle
  des répliques (`S._traduire`, ligne 1013) → casting voix → rendu TTS. La traduction s'applique
  **après** la découpe en répliques, sur la liste `(perso, texte)`.
- `front.html:479` (`<div class="recit">${md(ep.script_balise||ep.script_brut||'')}</div>`) : le
  texte affiché est lu directement depuis l'objet série chargé en mémoire, jamais retraduit ni
  adapté — confirmé, aucune route d'adaptation texte n'existe aujourd'hui.
- `main.py:206-217` (`FaireEpisode`, `CibleEpisode`, `DefinirCible`) : modèles Pydantic existants
  pour la cible de série (écriture) — distincts du besoin ici (cible de **lecture**, par profil).

## Architecture

### 1. Profils lecteurs (nouveau)

« Global à l'atelier » = partagé entre toutes les séries d'un même tenant, **pas** entre
tenants : cette brique est multi-tenant (`cle_api`/`charger()`, `main.py:44-93` — chaque série
est scopée à une identité `cree_par`, BYO clé ou personne du cercle privé via `X-User-Id`, S187).
Les profils suivent exactement le même principe d'isolation que les séries, pour ne jamais fuiter
un profil « Fils »/« Fille » entre deux identités différentes.

Stockage : un fichier par profil (même motif que les séries), dans un sous-dossier dédié pour ne
jamais collisionner avec un fichier de série — `os.path.join(ATELIERS_DIR, "profils",
f"{profil_id}.json")`. Contenu : `{id, nom, cible, cree_par, cree_le}`. `id` en
`uuid.uuid4().hex` (même convention que les séries). `cible` contrainte aux clés de `S.CIBLES`
existantes. `cree_par` = l'identité résolue par `cle_api`, jamais modifiable après création
(même motif que `serie["cree_par"]`).

Routes nouvelles (`main.py`), toutes scopées par `cle: str = Depends(cle_api)` et filtrant sur
`cree_par == cle` (404 — jamais 403 — sur un profil d'une autre identité, même motif que
`charger()`) :
- `GET /profils` — liste des profils de l'identité appelante
- `POST /profils {nom, cible}` — créer, `cree_par` = identité appelante
- `PATCH /profils/{id} {nom?, cible?}` — modifier (notamment faire vieillir un profil) ; 404 si
  le profil n'appartient pas à l'appelant
- `DELETE /profils/{id}` — supprimer ; même règle 404

La série ne référence jamais un profil par id stocké : le lien profil ↔ contenu se fait
uniquement au moment de la requête (`profil_id` en paramètre), jamais en persistance côté série.
Un profil supprimé ne casse donc aucune série existante.

### 2. Adaptation du texte affiché (nouveau)

Nouvelle fonction `_adapter_cible(texte: str, cible: str) -> tuple[str, bool]` dans `studio.py`,
calquée sur `_traduire` : un appel Gateway unique, prompt système qui réutilise
`CIBLE_GUIDE[cible]`, consigne explicite de préserver la structure (balises `[SFX]`/
`[AMBIANCE]`/`[MUSIQUE]`, didascalies entre parenthèses) et de ne reformuler que le registre
(vocabulaire, longueur, intensité), jamais l'intrigue. Repli honnête (texte d'origine, `ok=False`)
si la Gateway échoue, si la réponse est vide, ou si sa longueur s'écarte trop de l'original (hors
bornes ratio ~0.3×–3× — garde-fou anti-réponse tronquée ou anti-délire ; à la différence de
`_traduire`, qui vérifie un nombre de répliques attendu identique, il n'y a ici pas de liste à
recompter, juste un texte continu).

Nouvelle route `GET /series/{serie_id}/episodes/{n}/adapte?profil_id=X` → 
`{texte, adapte: bool, cible, profil_id}`. Résout le profil scopé à l'identité appelante (404 —
même règle que `charger()` — si le profil n'existe pas ou appartient à une autre identité ; ne
révèle jamais l'existence d'un profil étranger), prend `script_balise` (ou `script_brut` en
repli) de l'épisode `n`, appelle `_adapter_cible`. Rien n'est stocké : chaque appel recalcule.

Le front n'appelle cette route que si un profil est sélectionné dans le sélecteur « Lire
pour… » ; sans sélection, comportement strictement inchangé (texte de référence affiché
directement depuis l'objet série déjà chargé).

### 3. Adaptation de l'audio (extension de l'existant)

`FaireEpisode` (`main.py:206-209`, déjà réutilisé par `/audio`) gagne un champ
`profil_id: Optional[str] = None`. Dans `produire_audio` (`main.py:978`), si `profil_id` est
fourni, le profil est résolu scopé à l'identité appelante (même règle 404 qu'au point 2 —
`cle_api` protège déjà `charger(serie_id, cle)` dans cette route, la résolution du profil doit
suivre la même identité). Avant la découpe en répliques (avant `main.py:989`), le `script` passe
alors par `_adapter_cible(script, cible)` (cible résolue depuis le profil). La découpe en répliques, la traduction
de langue existante (ligne 1013) et le casting/TTS continuent inchangés en aval — cible et langue
se combinent donc sans code dupliqué (ex. profil « Fille », langue de sortie espagnol).

Le champ `profil_id` sur `FaireEpisode` n'a de sens que pour la route `/audio` ; la route
`/faire-episode` (écriture, `main.py:894`) qui partage le même modèle l'ignore simplement —
cohérent avec le partage déjà lâche de ce modèle entre les deux routes aujourd'hui.

### 4. Front

- Nouveau panneau global « Profils lecteurs » (créer/renommer/faire évoluer l'âge/supprimer),
  accessible depuis le tableau de bord des séries (hors d'une série précise, puisque global).
- Sur chaque chapitre affiché : sélecteur « Lire pour… » (liste des profils + option « texte de
  référence »). Sélection → appel `GET .../adapte?profil_id=...`, remplace le texte affiché ;
  option « texte de référence » → comportement actuel inchangé. Dernier choix persisté en
  `localStorage`, réappliqué par défaut à la prochaine ouverture d'un chapitre (de n'importe
  quelle série).
- Le générateur audio existant (bouton avec sélecteur de langue de sortie) gagne le même
  sélecteur de profil, envoyé comme `profil_id` dans le body de `POST /series/{id}/audio`.

## Modèle de données

Un fichier JSON par profil (pas de schéma SQL, pas de liste unique — même politique de
persistance qu'une série) dans `profils/` sous `ATELIERS_DIR` :

```json
// profils/<id>.json
{"id": "…hex32…", "nom": "Fils", "cible": "7-9", "cree_par": "perso", "cree_le": "2026-08-17T…Z"}
```

`GET /profils` liste ce sous-dossier et filtre sur `cree_par == cle`, même motif que
`lister_series` (`main.py:317-349`) qui liste `ATELIERS_DIR` et filtre sur `_identite_effective`.

Aucune modification du schéma des séries existantes.

## Erreurs / dégradation

- Adaptation texte ou audio échoue (Gateway injoignable, JSON illisible, longueur incohérente) :
  contenu de référence renvoyé tel quel, `adapte: false` — jamais de blocage. Le front affiche un
  indicateur discret (« adaptation indisponible, texte de référence affiché »).
- `profil_id` référence un profil supprimé entre-temps, ou appartenant à une autre identité : la
  route renvoie 404 explicite dans les deux cas (pas de repli silencieux sur un profil différent,
  jamais de fuite d'existence d'un profil étranger) ; le front retombe sur « texte de référence »
  et invalide son `localStorage`.
- Aucun profil créé : le sélecteur « Lire pour… » n'affiche que « texte de référence » — pas de
  régression pour un usage sans profil.

## Tests

- `test_profils.py` (nouveau) : CRUD complet (créer, lister, modifier la cible d'un profil,
  supprimer), validation de `cible` contre `S.CIBLES`, **isolation entre identités** (une clé A
  ne voit jamais, ne peut ni modifier ni supprimer un profil créé par une clé B — 404, même motif
  que les séries).
- `test_cible_lecture.py` (nouveau) : `_adapter_cible` — succès (registre modifié, structure/
  balises préservées), repli honnête sur échec Gateway, repli sur incohérence de longueur.
- Extension `test_audio.py`/équivalent existant : `POST /audio` avec `profil_id` seul, avec
  `profil_id` + `langue_sortie` combinés, avec `profil_id` invalide (404), sans `profil_id`
  (non-régression stricte du chemin actuel).
- Route `GET .../episodes/{n}/adapte` : profil valide, profil supprimé (404), Gateway en panne
  (repli honnête), épisode inexistant (404).

## Hors périmètre (explicitement)

- **Contenu narratif divergent par âge** (couper des sous-intrigues, simplifier la trame) — la
  décision actée est un seul canon, ton adapté uniquement.
- **Mise en cache des versions adaptées** — décision actée : recalcul à chaque lecture/écoute,
  comme la traduction existante. Une mise en cache par (épisode, profil) pourra être reconsidérée
  plus tard si le coût/latence LLM devient un problème réel constaté, pas anticipé ici.
- **Rattachement d'un profil à une série précise** — les profils restent globaux à l'atelier,
  jamais stockés dans le JSON d'une série.
- **Suggestion automatique de palier d'âge** (ex. à partir d'une date de naissance) — la mise à
  jour de la cible d'un profil reste un geste manuel (`PATCH /profils/{id}`).
