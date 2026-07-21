# Design — Audio du digest quotidien (veille-info)

**Date** : 2026-07-21
**Statut** : validé, prêt pour plan d'implémentation

## Contexte

Suite du spec `docs/superpowers/specs/2026-07-21-veille-info-brique-design.md` (brique
`veille-info`, port 6120, LIVE HP) qui excluait explicitement l'audio du périmètre. Ce spec
couvre cette dernière pièce : générer un MP3 du résumé quotidien, en réutilisant la brique
`voix` (5985) déjà existante — aucun code TTS neuf à écrire.

Clarifications actées avec l'utilisateur :
- **Choix du moteur TTS** : rien à construire. `briques/voix/moteur.py` balaie déjà les
  fournisseurs disponibles dans l'ordre « souverain (Piper) d'abord », ne basculant vers un
  fournisseur payant (OpenAI/ElevenLabs) que si aucun moteur gratuit n'est configuré/
  disponible — exactement le comportement « gratuit par défaut, payant si vraiment besoin »
  demandé, obtenu gratuitement en appelant `/rendre` sans forcer de fournisseur.
- **Génération automatique**, pas à la demande : juste après qu'un digest texte soit créé
  avec succès dans le pipeline quotidien (`digest.py`), sans attendre qu'une personne demande
  à l'écouter.
- **Stockage en table séparée** (`digest_audio`) plutôt que des colonnes sur `digests` — plus
  extensible si plusieurs versions audio par digest deviennent utiles un jour (voix
  différente, régénération), même si la logique applicative de cette version n'en crée
  jamais qu'une par digest.
- **Aucune notion de « voix par personne »** n'existe nulle part dans le système (vérifié :
  ni dans `voix`, ni dans `studio`/`personnages`, ni dans le Cœur) — pas de voix forcée, on
  laisse le moteur `voix` choisir sa voix par défaut.
- **Motif d'appel** : identique à `briques/studio/main.py:1010-1028`, qui appelle déjà
  `POST {VOIX_URL}/rendre` sans aucune clé (cohérent avec le reste du parc, où tous les
  `{BRIQUE}_KEY`/`API_KEYS` sont vides aujourd'hui, cf. mémoire du déploiement HP de
  `veille-info`).

## État constaté du code (vérifié, pas supposé)

- `briques/voix/main.py:205` (`POST /rendre`) : prend `{segments: [{voix, texte}], langue,
  episode_id}`, synthétise chaque segment (WAV) puis concatène en MP3 via ffmpeg, persiste
  dans `/data/voix/episodes/{episode_id}.mp3`, renvoie `{url, duree, episode_id}`. Ne prend
  actuellement PAS de paramètre `fournisseur`/`usage` au niveau du batch (chaque segment est
  synthétisé avec `fournisseur=None, usage=None` — ordre de préférence par défaut). Aucune
  modification de `voix` n'est nécessaire pour ce spec : le batch mono-segment fonctionne tel
  quel.
- `briques/studio/main.py:1010-1028` est la référence directe du motif d'appel : `httpx.AsyncClient`,
  timeout 180s, `try/except` → `HTTPException(502, ...)` si `voix` est injoignable. Aucune
  clé API envoyée (le parc entier tourne aujourd'hui avec des clés de service vides).
- `briques/studio/docker-compose.yml:19` confirme la valeur réelle déployée de `VOIX_URL` :
  `http://host.docker.internal:5985` (le défaut Python de `studio.py:41`, port 5810, est une
  incohérence préexistante ailleurs dans le code, hors périmètre de ce spec — on utilise le
  bon port, 5985, comme défaut dans `veille-info`).
- `stockage.inserer_digest(user_id, texte_resume, nb_articles, date=None) -> dict` (déjà
  existant) renvoie un dict avec `id` — c'est cet id qui sert de clé étrangère pour
  `digest_audio` et de nom d'épisode (`episode_id`).

## Modèle de données (ajout SQLite)

```sql
CREATE TABLE IF NOT EXISTS digest_audio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_id INTEGER NOT NULL REFERENCES digests(id),
    url TEXT NOT NULL,
    duree REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_digest_audio_digest ON digest_audio(digest_id);
```

`digest_id` n'est PAS `UNIQUE` : le schéma permet plusieurs lignes par digest (versions
futures), même si cette version n'en insère jamais qu'une (la plus récente = celle utilisée).

## Pipeline

Dans `digest.py::_traiter_utilisateur`, juste après `stockage.inserer_digest(...)` (et
`stockage.marquer_articles_digestes(...)`, déjà en place) :

1. Appel `POST {VOIX_URL}/rendre` avec :
   ```json
   {"episode_id": "veille-info-<digest_id>",
    "segments": [{"voix": null, "texte": "<texte_resume>"}]}
   ```
   (motif `httpx.AsyncClient(timeout=180)`, identique à studio). `digest.py` étant
   aujourd'hui synchrone (pas de fonctions `async def`), l'appel se fait en `httpx` synchrone
   (`httpx.post`, même bibliothèque déjà utilisée par `rss.py`/`lib/llm_client.py` dans cette
   brique) — pas besoin d'introduire de code async dans ce module.
2. Si la réponse est 200 avec une `url` : `stockage.inserer_audio_digest(digest_id, url, duree)`.
3. Si `voix` est injoignable, renvoie une erreur, ou renvoie un `place_holder` honnête sans
   audio (`res.get("place_holder")` ou absence d'`url`) : journalisé (`logger.warning`),
   AUCUNE ligne insérée dans `digest_audio`, le digest texte (déjà créé à l'étape précédente)
   reste intact et consultable. Pas de retry automatique dans cette version — le texte reste
   la source de vérité utilisable immédiatement.
4. Cet appel est lui-même à l'intérieur du filet `_traiter_utilisateur_sans_planter` déjà en
   place (S189-2 Task 4) : un échec ici ne bloque jamais le traitement des autres personnes.

## API

`GET /digests` et `GET /digests/{digest_id}` (déjà existants) incluent désormais
`audio_url`/`audio_duree` dans leur réponse (`null`/`null` si aucun audio n'a encore été
généré ou si la génération a échoué) — la ligne `digest_audio` la plus récente pour ce
`digest_id`, s'il en existe une. Pas de nouvel endpoint : pas de capacité assistant
supplémentaire nécessaire (`veille_info_digest_lire` existant suffit, son schéma de réponse
s'enrichit simplement).

## Erreurs / dégradation

- `voix` injoignable (timeout, connexion refusée) → digest texte intact, pas d'audio, pas de
  crash, journalisé.
- `voix` répond mais sans audio (`place_holder: true`, aucun moteur configuré) → même
  traitement : pas de ligne `digest_audio`, pas d'erreur remontée à l'appelant du pipeline.
- Aucun scénario ne doit faire échouer `stockage.inserer_digest` lui-même : l'audio est
  strictement une étape APRÈS coup, jamais transactionnelle avec la création du digest.

## Tests

Extension de `test_digest.py` (mock `httpx.post` vers `voix`, aucun réseau réel) :
- Digest créé + `voix` répond 200 avec une URL → une ligne `digest_audio` existe, liée au bon
  `digest_id`.
- `voix` injoignable (exception) → digest texte toujours présent, aucune ligne `digest_audio`,
  pas d'exception remontée.
- `voix` répond avec `place_holder: true` (pas de moteur configuré) → même comportement que
  ci-dessus.
- `GET /digests/{id}` (test_main.py) : renvoie `audio_url`/`audio_duree` quand une ligne
  `digest_audio` existe, `null`/`null` sinon.
- Nouveau test dans `test_stockage.py` pour `inserer_audio_digest`/lecture du plus récent
  audio par digest, isolation par digest_id.

## Hors périmètre (explicitement)

- Toute modification de `briques/voix/` (le `/rendre` existant suffit tel quel).
- Retry automatique d'une génération audio échouée (le texte reste utilisable ; rejouable à la
  main plus tard si besoin réel constaté).
- Toute notion de voix par personne (n'existe nulle part dans le système ; hors périmètre).
- Nouvel endpoint dédié à l'audio : tout passe par l'enrichissement de `GET /digests(/{id})`.
