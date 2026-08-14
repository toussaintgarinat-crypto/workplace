# Synopsis — produit standalone déployé sur Vercel

**Date** : 2026-08-14
**Statut** : design approuvé, plan d'implémentation à venir

## Contexte

L'utilisateur veut proposer « synopsis » (résumé vidéo par IA) comme application
séparée, sur le modèle de [portrait-cosmique](https://github.com/toussaintgarinat-crypto/portrait-cosmique)
(repo GitHub public autonome, extrait d'une brique du monorepo Workplace), mais
déployée sur **Vercel** plutôt qu'auto-hébergée en Docker, avec un LLM gratuit par
défaut ou une clé personnelle (BYOK).

Deux bases de code existaient déjà et ont été évaluées :

- `Workplace/briques/synopsis` (port 6090) : FastAPI, pipeline async (202 + poll
  `/jobs/{id}`), résumé YouTube/fichier/lien direct, **highlight reels vidéo**
  (ffmpeg + yt-dlp, montage, sous-titres, narration TTS), transcription non-YouTube
  déléguée à une brique séparée (`transcription`, Whisper). Trop couplé au mesh
  Workplace et aux traitements vidéo lourds pour Vercel serverless.
- `toussaintgarinat-crypto/youtube-summarizer` (repo GitHub existant, non lié à
  Workplace) : application **Streamlit** bien plus riche fonctionnellement (multi-
  plateforme, Whisper local, upload fichiers, génération d'images, export
  PDF/Excalidraw/Drive/Obsidian, chat Q&A, playlists), mais Streamlit ne se déploie
  pas sur Vercel (process serveur persistant, pas des fonctions serverless).

**Décision** : nouveau repo `synopsis`, dont le moteur (`src/extractor.py`,
`chunker.py`, `fusion.py`, prompts) est **porté depuis `youtube-summarizer`**
(réduit à YouTube, sans les dépendances subprocess/yt-dlp), et dont l'architecture
serveur + l'adaptateur LLM + la charte front-end sont **calqués sur
`portrait-cosmique`**.

## Périmètre V1

✅ Inclus (tout compatible Vercel serverless, aucune fonction ne dépasse son budget
de temps car aucun téléchargement/traitement vidéo n'est nécessaire) :

- Résumé d'une vidéo YouTube à partir de son URL, via le **transcript natif**
  (`youtube_transcript_api`) — pas de téléchargement, pas de ffmpeg, pas de Whisper.
- Chapitrage horodaté + points clés, dérivés du résumé LLM.
- Multilingue (FR, EN, ES, DE, PT, IT).
- LLM gratuit par défaut (clé OpenRouter d'instance) **ou** BYOK par requête
  (fournisseur + URL + clé + modèle, jamais stocké côté serveur).
- Liste de modèles disponibles **récupérée en direct** chez le fournisseur BYOK
  (`GET {base_url}/models`) plutôt qu'une liste figée en dur — le repo `config.py`
  de youtube-summarizer maintenait une liste statique (`MODEL_CONTEXTS`) qui devient
  vite obsolète ; on reprend le pattern `lister_modeles()` de portrait-cosmique.
- Export PDF/Markdown/HTML généré 100 % côté navigateur (comme portrait-cosmique).
- Chat Q&A sur le contenu déjà résumé (contexte tenu côté client, un appel LLM par
  question, rien stocké côté serveur).
- Mode « plusieurs vidéos » : l'utilisateur colle plusieurs URLs (une par ligne), le
  navigateur boucle et appelle `/resumer` pour chacune — pas de vraie énumération de
  playlist YouTube (nécessiterait une clé YouTube Data API), donc pas d'API Google
  supplémentaire à gérer.

❌ Explicitement hors périmètre V1 (incompatibles avec Vercel serverless — pas de
disque persistant, pas de process long-lived, timeout par fonction) :

- Transcription Whisper (locale ou déléguée), upload de fichiers audio/vidéo.
- Vidéos non-YouTube (Twitch, Vimeo, TikTok…) qui nécessitent un téléchargement.
- Highlight reels vidéo (ffmpeg, montage, narration TTS, export vertical).
- Génération d'images, schéma Excalidraw, export Drive/Obsidian.
- Vraie énumération de playlist YouTube via API.

Ces fonctionnalités restent la spécialité de `youtube-summarizer` (Docker/desktop)
et de la brique Workplace (mesh interne) — synopsis-vercel ne cherche pas à les
remplacer, seulement à couvrir le cas d'usage « coller un lien, avoir un résumé »
sans rien installer.

## Architecture

FastAPI packagé comme fonction serverless unique sur Vercel — `api/index.py`
réexporte l'`app` de `main.py`, `vercel.json` route tout le trafic vers cette
fonction. Ce choix (plutôt qu'une réécriture en Next.js/JS) maximise la réutilisation
du code Python existant (youtube-summarizer + patterns portrait-cosmique) et garde
une parité complète avec le mode local (`uvicorn main:app`) et l'auto-hébergement
Docker.

Stateless : aucune base de données, aucun job asynchrone (pas de ffmpeg → pas besoin
du pattern 202+poll de la brique Workplace, un résumé se fait en un seul appel HTTP
synchrone dans le budget de temps d'une fonction Vercel).

```
synopsis/
├── api/
│   └── index.py            # réexporte `app` pour Vercel
├── engine/
│   ├── extractor.py        # porté de youtube-summarizer/src, réduit à YouTube
│   ├── chunker.py           # porté tel quel
│   ├── fusion.py             # porté tel quel
│   ├── test_extractor.py
│   ├── test_chunker.py
│   └── test_fusion.py
├── prompts/
│   ├── analyzer.xml         # porté de youtube-summarizer
│   └── fusion.xml           # porté de youtube-summarizer
├── llm.py                   # adaptateur calqué sur portrait-cosmique/llm.py
├── test_llm.py
├── main.py                  # endpoints FastAPI
├── test_main.py
├── static/
│   └── index.html           # front unique, charte portrait-cosmique
├── vercel.json
├── Dockerfile                # auto-hébergement, comme portrait-cosmique
├── docker-compose.yml
├── install.sh
├── requirements.txt
├── .env.example
├── README.md / README.en.md
└── LICENSE (Apache 2.0, cohérent avec portrait-cosmique)
```

## Composants

- **`engine/extractor.py`** — `extract_youtube_id(url)` (formats `watch?v=`,
  `youtu.be/`, `embed/`, ID nu) + appel `YouTubeTranscriptApi` → texte + segments
  horodatés. Lève une erreur explicite si sous-titres désactivés/absents — jamais de
  repli silencieux vers un autre moteur de transcription.
- **`engine/chunker.py`** — découpe le transcript sous la limite de tokens du modèle
  actif (BYOK ou gratuit par défaut).
- **`engine/fusion.py`** — fusionne les résumés partiels par chunk en un résumé final
  structuré (chapitres horodatés + points clés).
- **`prompts/analyzer.xml`, `prompts/fusion.xml`** — prompts externalisés, portés tels
  quels depuis youtube-summarizer.
- **`llm.py`** — adaptateur calqué sur `portrait-cosmique/llm.py` :
  - `_config(llm)` : priorité BYOK (`{base_url, cle, modele}`) > clé d'instance
    OpenRouter (`meta-llama/llama-3.3-70b-instruct:free` par défaut) > OpenCode Go >
    OpenAI-compatible > rien (erreur explicite).
  - `resumer_chunk()` / `fusionner()` : appels `POST {base}/chat/completions`.
  - `lister_modeles(base_url, cle)` : `GET {base}/models` → liste triée d'IDs réels,
    repris à l'identique de portrait-cosmique (pas de liste figée en dur).
  - Un seul retry court sur 429 (modèle gratuit saturé), puis erreur explicite —
    jamais de contenu inventé.
- **`main.py`** — endpoints :
  - `GET /sante` — statut + fournisseur LLM configuré (sans exposer la clé).
  - `GET /modeles?cle=&base_url=` — liste live des modèles BYOK (422 sans clé/URL,
    502 si le fournisseur échoue).
  - `POST /resumer` — `{url, langue, llm?}` → transcript → chunks → résumé fusionné,
    synchrone.
  - `POST /qa` — `{contexte, question, llm?}` → réponse contextuelle, sans stockage.
- **`static/index.html`** — front unique repris de la charte `portrait-cosmique` :
  - CSS vars identiques (`--bg:#0f1220`, `--panel`, `--accent:#b98cf7`,
    `--accent2:#6ee7c3`, dégradé sombre, `.wrap` 780px, `.panel` en cartes).
  - Toggle FR/EN (`.langs`) + objet `I18N` JS avec `data-t` sur chaque texte.
  - `<details class="avance">` "Options avancées" contenant tout le bloc BYOK repris
    à l'identique : dropdown `FOURNISSEURS` (OpenRouter/OpenCode Go/OpenAI/
    Personnalisé), champ clé `type=password` + bouton 👁️, bouton
    « 🔄 Charger les modèles » → `/modeles` → peuple un `<select>`, sauvegarde
    `localStorage` (jamais envoyée qu'à la demande), bouton effacer.
  - `@media print` pour l'export PDF (masque formulaire/nav, garde le résultat).
  - `telechargerHTML()` repris à l'identique (panneau + styles inline + script
    réinjecté, `</script>` échappé en `<\/script>`).
  - Nouveautés propres à synopsis dans la zone résultat : chapitres horodatés à la
    place des stats/empreinte astrale, zone chat Q&A, textarea multi-liens (mode
    plusieurs vidéos, boucle côté client sur `/resumer`).
- **`vercel.json` + `api/index.py`** — pattern standard FastAPI-ASGI-on-Vercel.
- **`Dockerfile`, `docker-compose.yml`, `install.sh`** — conservés pour
  l'auto-hébergement, même esprit que portrait-cosmique : Vercel n'est pas la seule
  cible de déploiement.

## Flux de données

**Résumé simple :**
1. Front → `POST /resumer {url, langue, llm?}`.
2. `extract_youtube_id(url)` → `YouTubeTranscriptApi` → transcript + segments.
   Sous-titres absents/désactivés → `422` immédiat, message explicite.
3. `chunker.py` découpe selon la limite de tokens du modèle actif.
4. Chaque chunk → `llm.py` avec `prompts/analyzer.xml` → résumé partiel + chapitres
   candidats.
5. `fusion.py` (+ `prompts/fusion.xml`) → résumé final structuré.
6. Réponse synchrone unique, rien conservé entre les étapes.

**BYOK + modèles :** le front appelle `GET /modeles` dès que la clé est saisie, pour
peupler le sélecteur avant même de lancer un résumé.

**Plusieurs vidéos :** le textarea multi-liens reste côté client — une boucle appelle
`/resumer` par URL, chaque appel est indépendant (son propre budget de temps Vercel),
un échec sur une ligne n'interrompt pas les autres.

**Chat Q&A :** le front garde le résumé/transcript déjà reçu en mémoire ; `POST /qa`
fait un seul appel LLM avec ce contexte en système, rien stocké côté serveur.

**Export PDF/Markdown/HTML :** généré 100 % dans le navigateur à partir du JSON déjà
reçu, aucun aller-retour serveur supplémentaire.

## Gestion d'erreur / repli honnête

Principe directeur (identique à portrait-cosmique et à la brique Workplace) :
**jamais inventer un résultat, toujours expliquer pourquoi ça échoue.**

- Pas de sous-titres → `422` explicite, pas de tentative Whisper (hors périmètre).
- URL invalide/non-YouTube → `422` avant tout appel réseau.
- Aucun LLM configuré (ni clé d'instance, ni BYOK) → `422` explicite, jamais de
  résumé dégradé silencieux.
- BYOK invalide/401/modèle inexistant → erreur du fournisseur relayée telle quelle
  (tronquée), pas de retry qui la masquerait.
- 429 sur le modèle gratuit → un seul retry court, puis erreur explicite invitant à
  fournir sa propre clé.
- `/modeles` échoue → `502` avec le message du fournisseur, le sélecteur reste sur le
  modèle gratuit par défaut, ne bloque pas la page.
- Timeout Vercel dépassé (vidéo très longue) → à surveiller en test réel ; le
  chunking doit rester assez agressif pour qu'un résumé single-vidéo tienne
  largement sous la limite plutôt que de sur-concevoir un mécanisme préventif
  maintenant.
- Mode plusieurs vidéos : un échec sur une ligne n'interrompt pas les autres, chaque
  résultat affiche son propre statut (ok/erreur).

## Tests

- `engine/test_extractor.py` — extraction d'ID (tous formats), URL invalide ; l'appel
  réseau `YouTubeTranscriptApi` est mocké.
- `engine/test_chunker.py`, `test_fusion.py` — adaptés des tests existants de
  youtube-summarizer si présents, sinon écrits neufs.
- `test_llm.py` — priorité de `_config()` (BYOK > OpenRouter > OpenAI-compatible >
  rien), `lister_modeles()` mocké, propagation propre des erreurs (401, 429,
  injoignable).
- `test_main.py` — `TestClient` FastAPI sur `/resumer` (transcript mocké), `/modeles`
  (422 sans clé, 502 si le fournisseur échoue), `/qa`, `/sante`. Aucun appel réseau
  réel dans la suite automatisée.
- **Preuve manuelle avant publication** : un vrai `POST /resumer` contre une vraie
  vidéo YouTube publique avec sous-titres, en local (`uvicorn`) **et** une fois
  déployé sur Vercel — c'est le point le moins éprouvé du design : ni
  portrait-cosmique ni youtube-summarizer n'ont encore été testés sur Vercel en
  production.

## Hors périmètre / décisions différées

- Pas de vraie énumération de playlist (nécessiterait une clé YouTube Data API) —
  le mode « coller plusieurs liens » couvre le besoin sans clé supplémentaire.
- Pas de fusion avec `youtube-summarizer` ni avec `briques/synopsis` — les trois
  bases de code restent distinctes, chacune avec son périmètre (desktop/Docker riche,
  mesh Workplace interne, Vercel léger).
- Nom de domaine / configuration Vercel (org, env vars sur le dashboard) — à faire
  au moment du déploiement, pas dans ce design.
