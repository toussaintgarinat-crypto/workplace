# Synopsis (standalone Vercel) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Créer un nouveau repo standalone `synopsis` (résumé de vidéo YouTube par IA), déployable sur Vercel, avec moteur porté depuis `youtube-summarizer` et architecture/LLM/front calqués sur `portrait-cosmique`.

**Architecture:** FastAPI stateless (aucune base de données, aucun job asynchrone) packagé comme fonction serverless unique sur Vercel (`api/index.py` réexporte l'app). Le moteur (`engine/`) découpe YouTube → transcript natif → chunks → résumé par chunk (LLM) → fusion en un rapport unique. L'adaptateur `llm.py` route vers une clé OpenRouter gratuite d'instance ou un BYOK par requête, avec repli honnête (jamais de résumé inventé).

**Tech Stack:** Python 3.12, FastAPI 0.141.1, httpx 0.28.1, youtube-transcript-api 1.2.4, tiktoken 0.13.0, pytest 9.1.1, HTML/CSS/JS vanilla (pas de framework front), Docker (self-host), Vercel (déploiement serverless).

## Global Constraints

- Périmètre V1 strict : résumé YouTube uniquement (transcript natif via `youtube_transcript_api`, jamais de téléchargement, jamais de ffmpeg, jamais de Whisper). Toute vidéo non-YouTube ou sans sous-titres échoue avec un message explicite — pas de repli silencieux.
- Stateless : aucune donnée écrite sur disque, aucune base de données, aucun job asynchrone (202+poll) — chaque endpoint répond en un seul appel HTTP synchrone.
- LLM : priorité BYOK par requête (`{base_url, cle, modele}`) > clé d'instance OpenRouter (`meta-llama/llama-3.3-70b-instruct:free` par défaut) > OpenCode Go > OpenAI-compatible > erreur explicite si rien n'est configuré. Jamais de contenu inventé en repli.
- `GET /modeles` récupère la liste des modèles **en direct** chez le fournisseur BYOK (`GET {base_url}/models`) — jamais de liste figée en dur.
- Toutes les dépendances Python sont épinglées en versions exactes (`==`) dans `requirements.txt`.
- Charte front-end : reprise à l'identique de `portrait-cosmique/static/index.html` (CSS vars, i18n FR/EN, bloc BYOK complet, export navigateur, `@media print`).
- Licence Apache 2.0 (cohérent avec `portrait-cosmique`).
- Chemins de référence sur cette machine : `/Users/garinat_t/Desktop/portrait-cosmique` (charte/pattern LLM à copier), repo GitHub `toussaintgarinat-crypto/youtube-summarizer` (moteur source, accessible via `gh api repos/toussaintgarinat-crypto/youtube-summarizer/contents/...`).
- Nouveau repo local : `/Users/garinat_t/Desktop/synopsis` (n'existe pas encore, vérifié). Futur repo GitHub public : `toussaintgarinat-crypto/synopsis` (nom libre, vérifié).
- Spec complète : `docs/superpowers/specs/2026-08-14-synopsis-standalone-vercel-design.md` (dans le repo Workplace).

---

### Task 0: Scaffolding du repo

**Files:**
- Create: `/Users/garinat_t/Desktop/synopsis/requirements.txt`
- Create: `/Users/garinat_t/Desktop/synopsis/requirements-dev.txt`
- Create: `/Users/garinat_t/Desktop/synopsis/.gitignore`
- Create: `/Users/garinat_t/Desktop/synopsis/conftest.py`
- Create: `/Users/garinat_t/Desktop/synopsis/LICENSE` (copié de portrait-cosmique)
- Create: `/Users/garinat_t/Desktop/synopsis/NOTICE` (copié de portrait-cosmique, adapté)

**Interfaces:**
- Produces: `conftest.py` met `/Users/garinat_t/Desktop/synopsis` et `/Users/garinat_t/Desktop/synopsis/engine` sur `sys.path` — toutes les tâches suivantes en dépendent pour que `import llm`, `import extractor`, etc. fonctionnent depuis n'importe quel sous-dossier de tests.

- [ ] **Step 1: Créer le dossier et l'environnement virtuel**

```bash
mkdir -p /Users/garinat_t/Desktop/synopsis/engine /Users/garinat_t/Desktop/synopsis/prompts \
         /Users/garinat_t/Desktop/synopsis/static /Users/garinat_t/Desktop/synopsis/api
cd /Users/garinat_t/Desktop/synopsis
git init
python3 -m venv .venv
source .venv/bin/activate
```

- [ ] **Step 2: Écrire `requirements.txt`**

```
fastapi==0.141.1
uvicorn[standard]==0.52.3
httpx==0.28.1
youtube-transcript-api==1.2.4
tiktoken==0.13.0
```

- [ ] **Step 3: Écrire `requirements-dev.txt`**

```
-r requirements.txt
pytest==9.1.1
```

- [ ] **Step 4: Installer les dépendances**

```bash
pip install -r requirements-dev.txt
```

Expected: installation sans erreur.

- [ ] **Step 5: Écrire `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
.venv/
.env
.vercel/
```

- [ ] **Step 6: Écrire `conftest.py`**

```python
import sys
from pathlib import Path

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "engine"))
```

- [ ] **Step 7: Copier LICENSE et NOTICE depuis portrait-cosmique**

```bash
cp /Users/garinat_t/Desktop/portrait-cosmique/LICENSE /Users/garinat_t/Desktop/synopsis/LICENSE
cp /Users/garinat_t/Desktop/portrait-cosmique/NOTICE /Users/garinat_t/Desktop/synopsis/NOTICE
```

Ouvrir `NOTICE` et remplacer toute mention de « Portrait Cosmique » par « Synopsis » si le fichier en contient (vérifier avec `cat NOTICE`).

- [ ] **Step 8: Premier commit**

```bash
cd /Users/garinat_t/Desktop/synopsis
git add requirements.txt requirements-dev.txt .gitignore conftest.py LICENSE NOTICE
git commit -m "chore: scaffold du repo synopsis"
```

---

### Task 1: `engine/extractor.py` — transcript YouTube natif

**Files:**
- Create: `/Users/garinat_t/Desktop/synopsis/engine/extractor.py`
- Test: `/Users/garinat_t/Desktop/synopsis/engine/test_extractor.py`

**Interfaces:**
- Produces:
  - `extraire_id(url: str) -> str | None`
  - `titre_video(video_id: str) -> str`
  - `transcript_youtube(url: str, langues: list[str] | None = None) -> dict` renvoyant `{video_id: str, transcript: list[{text, start, duration}], langue: str, titre: str, duree_minutes: float}`
  - `class ErreurExtraction(Exception)`
- Consumes: rien (première tâche du moteur)

- [ ] **Step 1: Écrire les tests d'extraction d'ID**

```python
# engine/test_extractor.py
from unittest.mock import MagicMock, patch

import pytest

import extractor


def test_extraire_id_watch_url():
    assert extractor.extraire_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extraire_id_short_url():
    assert extractor.extraire_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extraire_id_embed_url():
    assert extractor.extraire_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extraire_id_id_nu():
    assert extractor.extraire_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extraire_id_invalide():
    assert extractor.extraire_id("https://example.com/pas-une-video") is None
```

- [ ] **Step 2: Vérifier que les tests échouent (module absent)**

```bash
cd /Users/garinat_t/Desktop/synopsis
pytest engine/test_extractor.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'extractor'`

- [ ] **Step 3: Implémenter `extraire_id`, `titre_video` et le squelette du module**

```python
# engine/extractor.py
"""Extraction de transcript YouTube — sans téléchargement, sans ffmpeg.

Utilise le transcript natif (sous-titres, auto-générés ou non) via
`youtube_transcript_api`. Lève une erreur explicite si la vidéo n'a pas de
sous-titres — jamais de repli vers une transcription audio."""
from __future__ import annotations

import re

import httpx
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
)

LANGUES_PAR_DEFAUT = ["fr", "en", "es", "de", "it", "pt"]


class ErreurExtraction(Exception):
    """Erreur explicite — URL invalide ou transcript indisponible."""


def extraire_id(url: str) -> str | None:
    """Extrait l'ID YouTube (11 caractères) depuis une URL ou un ID nu."""
    motifs = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for motif in motifs:
        m = re.search(motif, url.strip())
        if m:
            return m.group(1)
    return None


def titre_video(video_id: str) -> str:
    """Titre via l'API oembed publique — repli sur l'ID si indisponible."""
    try:
        r = httpx.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("title") or f"Vidéo {video_id}"
    except httpx.HTTPError:
        pass
    return f"Vidéo {video_id}"


def transcript_youtube(url: str, langues: list[str] | None = None) -> dict:
    """URL YouTube → {video_id, transcript, langue, titre, duree_minutes}.

    `transcript` = [{text, start, duration}, ...]. Lève ErreurExtraction avec un
    message explicite si l'URL est invalide ou si la vidéo n'a pas de sous-titres."""
    video_id = extraire_id(url)
    if not video_id:
        raise ErreurExtraction(
            "URL YouTube invalide. Format attendu : youtube.com/watch?v=ID ou youtu.be/ID.")

    api = YouTubeTranscriptApi()
    langues = langues or LANGUES_PAR_DEFAUT
    brut = None
    langue_trouvee = None

    for langue in langues:
        try:
            brut = list(api.fetch(video_id, languages=[langue]))
            langue_trouvee = langue
            break
        except Exception:
            continue

    if brut is None:
        try:
            fetched = api.fetch(video_id)
            brut = list(fetched)
            langue_trouvee = getattr(fetched, "language_code", "unknown")
        except TranscriptsDisabled:
            raise ErreurExtraction("Les sous-titres sont désactivés sur cette vidéo.")
        except NoTranscriptFound:
            raise ErreurExtraction("Aucun sous-titre disponible pour cette vidéo.")
        except CouldNotRetrieveTranscript as e:
            raise ErreurExtraction(f"Sous-titres inaccessibles : {str(e)[:150]}")
        except Exception as e:
            raise ErreurExtraction(f"Erreur lors de la récupération des sous-titres : {str(e)[:150]}")

    if not brut:
        raise ErreurExtraction("Aucun sous-titre disponible pour cette vidéo.")

    transcript = [{"text": e.text, "start": e.start, "duration": e.duration} for e in brut]
    derniere = transcript[-1]
    duree_min = (derniere["start"] + derniere["duration"]) / 60

    return {
        "video_id": video_id,
        "transcript": transcript,
        "langue": langue_trouvee or "unknown",
        "titre": titre_video(video_id),
        "duree_minutes": duree_min,
    }
```

- [ ] **Step 4: Vérifier que les 5 premiers tests passent**

```bash
pytest engine/test_extractor.py -v
```

Expected: 5 PASS

- [ ] **Step 5: Ajouter les tests de récupération du transcript (mockés, sans réseau)**

Ajouter à la fin de `engine/test_extractor.py` :

```python
def test_transcript_youtube_url_invalide():
    with pytest.raises(extractor.ErreurExtraction, match="URL YouTube invalide"):
        extractor.transcript_youtube("https://example.com/pas-une-video")


def _entree(text, start, duration):
    e = MagicMock()
    e.text, e.start, e.duration = text, start, duration
    return e


@patch("extractor.titre_video", return_value="Vidéo de test")
@patch("extractor.YouTubeTranscriptApi")
def test_transcript_youtube_succes(mock_api_cls, mock_titre):
    mock_api = MagicMock()
    mock_api.fetch.return_value = [_entree("Bonjour", 0.0, 2.0), _entree("le monde", 2.0, 1.5)]
    mock_api_cls.return_value = mock_api

    resultat = extractor.transcript_youtube("https://youtu.be/dQw4w9WgXcQ", langues=["fr"])

    assert resultat["video_id"] == "dQw4w9WgXcQ"
    assert resultat["titre"] == "Vidéo de test"
    assert resultat["transcript"] == [
        {"text": "Bonjour", "start": 0.0, "duration": 2.0},
        {"text": "le monde", "start": 2.0, "duration": 1.5},
    ]
    assert resultat["duree_minutes"] == pytest.approx(3.5 / 60)


@patch("extractor.YouTubeTranscriptApi")
def test_transcript_youtube_sous_titres_desactives(mock_api_cls):
    from youtube_transcript_api._errors import TranscriptsDisabled

    mock_api = MagicMock()
    mock_api.fetch.side_effect = TranscriptsDisabled("dQw4w9WgXcQ")
    mock_api_cls.return_value = mock_api

    with pytest.raises(extractor.ErreurExtraction, match="désactivés"):
        extractor.transcript_youtube("https://youtu.be/dQw4w9WgXcQ", langues=["fr"])
```

- [ ] **Step 6: Lancer toute la suite du module**

```bash
pytest engine/test_extractor.py -v
```

Expected: 8 PASS

- [ ] **Step 7: Commit**

```bash
git add engine/extractor.py engine/test_extractor.py
git commit -m "feat(engine): extraction de transcript YouTube natif"
```

---

### Task 2: `engine/chunker.py` — découpage par tokens

**Files:**
- Create: `/Users/garinat_t/Desktop/synopsis/engine/chunker.py`
- Test: `/Users/garinat_t/Desktop/synopsis/engine/test_chunker.py`

**Interfaces:**
- Produces:
  - `estimate_tokens(text: str) -> int`
  - `format_timestamp(seconds: float) -> str`
  - `create_text_from_transcript(transcript: list[dict]) -> str`
  - `chunk_transcript(transcript: list[dict], max_tokens: int = 12000, overlap_tokens: int = 1200) -> list[dict]` renvoyant `[{text, start, end, tokens}, ...]`
- Consumes: `transcript` au format produit par `extractor.transcript_youtube()['transcript']` (Task 1) : `[{text, start, duration}, ...]`

- [ ] **Step 1: Écrire les tests**

```python
# engine/test_chunker.py
import chunker


def _entree(text, start, duration=2.0):
    return {"text": text, "start": start, "duration": duration}


def test_chunk_transcript_vide():
    assert chunker.chunk_transcript([]) == []


def test_chunk_transcript_tient_dans_un_seul_chunk():
    transcript = [_entree("Bonjour", 0.0), _entree("le monde", 2.0)]
    chunks = chunker.chunk_transcript(transcript, max_tokens=1000)
    assert len(chunks) == 1
    assert chunks[0]["start"] == 0.0
    assert chunks[0]["end"] == 3.5
    assert "Bonjour" in chunks[0]["text"]


def test_chunk_transcript_decoupe_si_trop_long():
    transcript = [_entree(f"mot numero {i} " * 20, float(i) * 3) for i in range(50)]
    chunks = chunker.chunk_transcript(transcript, max_tokens=200, overlap_tokens=20)
    assert len(chunks) > 1
    assert chunks[-1]["end"] >= transcript[-1]["start"]


def test_format_timestamp_minutes():
    assert chunker.format_timestamp(65) == "01:05"


def test_format_timestamp_heures():
    assert chunker.format_timestamp(3661) == "01:01:01"
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
pytest engine/test_chunker.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'chunker'`

- [ ] **Step 3: Implémenter `engine/chunker.py`**

```python
# engine/chunker.py
"""Découpage d'un transcript en chunks sous la limite de tokens du modèle actif."""
from __future__ import annotations

import tiktoken

DEFAULT_MAX_TOKENS = 12000
DEFAULT_OVERLAP_TOKENS = 1200


def estimate_tokens(text: str) -> int:
    """Estimation via l'encodage cl100k_base — bonne approximation pour la plupart des modèles."""
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return len(text) // 4


def format_timestamp(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes >= 60:
        hours, minutes = minutes // 60, minutes % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def create_text_from_transcript(transcript: list[dict]) -> str:
    return "\n".join(f"[{format_timestamp(e['start'])}] {e['text']}" for e in transcript)


def chunk_transcript(transcript: list[dict], max_tokens: int = DEFAULT_MAX_TOKENS,
                      overlap_tokens: int = DEFAULT_OVERLAP_TOKENS) -> list[dict]:
    """Découpe un transcript [{text, start, duration}] en chunks
    [{text, start, end, tokens}] sous `max_tokens`, avec un recouvrement entre chunks
    pour ne pas couper le contexte en plein milieu d'une idée."""
    if not transcript:
        return []

    texte_complet = create_text_from_transcript(transcript)
    total_tokens = estimate_tokens(texte_complet)

    if total_tokens <= max_tokens:
        return [{"text": texte_complet, "start": transcript[0]["start"],
                  "end": transcript[-1]["start"] + transcript[-1].get("duration", 0),
                  "tokens": total_tokens}]

    chunks = []
    position = 0
    while position < len(transcript):
        entrees_chunk, tokens_chunk = [], 0
        debut_chunk = transcript[position]["start"]

        for i in range(position, len(transcript)):
            entree = transcript[i]
            texte_entree = f"[{format_timestamp(entree['start'])}] {entree['text']}"
            tokens_entree = estimate_tokens(texte_entree)
            if tokens_chunk + tokens_entree > max_tokens and entrees_chunk:
                break
            entrees_chunk.append(entree)
            tokens_chunk += tokens_entree

        derniere = entrees_chunk[-1]
        fin_chunk = derniere["start"] + derniere.get("duration", 0)
        chunks.append({"text": create_text_from_transcript(entrees_chunk), "start": debut_chunk,
                        "end": fin_chunk, "tokens": tokens_chunk})

        chevauchement = max(1, len(entrees_chunk) // 10)
        prochaine_position = min(position + len(entrees_chunk) - chevauchement, len(transcript) - 1)
        if prochaine_position <= position:
            prochaine_position = position + 1
        position = prochaine_position

    return chunks
```

- [ ] **Step 4: Vérifier que les tests passent**

```bash
pytest engine/test_chunker.py -v
```

Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add engine/chunker.py engine/test_chunker.py
git commit -m "feat(engine): découpage de transcript par budget de tokens"
```

---

### Task 3: `engine/analyzer.py` + `prompts/analyzer.xml` — préparation du prompt par chunk

**Files:**
- Create: `/Users/garinat_t/Desktop/synopsis/prompts/analyzer.xml`
- Create: `/Users/garinat_t/Desktop/synopsis/engine/analyzer.py`
- Test: `/Users/garinat_t/Desktop/synopsis/engine/test_analyzer.py`

**Interfaces:**
- Produces:
  - `charger_prompt_analyse() -> str`
  - `preparer_prompt(transcript_chunk: str, titre_video: str, langue: str = "Français") -> str`
- Consumes: `chunk["text"]` produit par `chunker.chunk_transcript()` (Task 2), `donnees["titre"]` produit par `extractor.transcript_youtube()` (Task 1)

- [ ] **Step 1: Créer `prompts/analyzer.xml`**

```xml
<prompt_definition>
  <role>
    Tu es un Expert en Analyse Multimédia et Intelligence de Contenu. Ta mission est de transformer des transcripts bruts et multilingues en rapports structurés à haute valeur ajoutée, dans la langue demandée.
  </role>
  <task_instructions>
    1. ANALYSE : Identifie le sujet principal et la langue source.
    2. TRADUCTION : Traduis les idées avec précision dans la langue de sortie demandée : {output_language}.
    3. CHAPITRAGE : Crée des segments logiques basés sur les timestamps.
    4. SYNTHÈSE : Produis un résumé exécutif (court) et un résumé détaillé (approfondi).
    5. EXTRACTION : Sélectionne les 3 meilleurs moments (insights).
  </task_instructions>
  <constraints>
    - SORTIE : Toujours en Markdown.
    - FIDÉLITÉ : Interdiction d'ajouter des informations externes à la vidéo.
    - TIMESTAMPS : Obligatoires pour chaque chapitre et insight. Format [MM:SS].
    - LANGUE : Tout le contenu généré doit être en {output_language}. C'est obligatoire.
    - LIMITE : Le résumé détaillé ne doit pas dépasser 1500 mots.
  </constraints>
  <output_format>
    # 📺 ANALYSE VIDÉO : {video_title}
    *Langue Source :* [Langue]

    ## 🚀 Résumé Exécutif (TL;DR)
    > [Résumé rapide en 3-5 phrases]

    ## 📍 Chapitrage Temporel
    | Time | Sujet | Description |
    | :--- | :--- | :--- |
    | [MM:SS] | *[Titre]* | [Valeur ajoutée] |

    ## 💡 Top 3 Moments Forts (Insights)
    1. *[Titre]* [MM:SS] : [Explication]
    2. *[Titre]* [MM:SS] : [Explication]
    3. *[Titre]* [MM:SS] : [Explication]

    ## 📝 Résumé Détaillé
    ### 🔹 Contexte et Enjeux
    [Détails ici...]
    ### 🔹 Points Techniques / Arguments
    [Détails ici...]
  </output_format>
  <self_verification>
    - Est-ce que les timestamps sont réels et issus du texte ?
    - Le ton est-il professionnel et informatif ?
    - La traduction est-elle naturelle (pas de mot-à-mot) ?
  </self_verification>
</prompt_definition>

---
TRANSCRIPT:
{transcript}
```

- [ ] **Step 2: Écrire les tests**

```python
# engine/test_analyzer.py
import analyzer


def test_preparer_prompt_injecte_les_valeurs():
    prompt = analyzer.preparer_prompt("Bonjour le monde", "Ma Vidéo", "English")
    assert "Ma Vidéo" in prompt
    assert "Bonjour le monde" in prompt
    assert "English" in prompt


def test_preparer_prompt_ne_casse_pas_sur_accolades_dans_le_transcript():
    prompt = analyzer.preparer_prompt("Un texte avec { des accolades }", "Titre", "Français")
    assert "{ des accolades }" in prompt
```

- [ ] **Step 3: Vérifier que les tests échouent**

```bash
pytest engine/test_analyzer.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'analyzer'`

- [ ] **Step 4: Implémenter `engine/analyzer.py`**

```python
# engine/analyzer.py
"""Prépare le prompt d'analyse par chunk à partir du gabarit prompts/analyzer.xml."""
from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def charger_prompt_analyse() -> str:
    return (_PROMPTS_DIR / "analyzer.xml").read_text(encoding="utf-8")


def _formater(gabarit: str, **kw) -> str:
    for cle, val in kw.items():
        gabarit = gabarit.replace("{" + cle + "}", str(val))
    return gabarit


def preparer_prompt(transcript_chunk: str, titre_video: str, langue: str = "Français") -> str:
    return _formater(charger_prompt_analyse(), video_title=titre_video,
                      transcript=transcript_chunk, output_language=langue)
```

- [ ] **Step 5: Vérifier que les tests passent**

```bash
pytest engine/test_analyzer.py -v
```

Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add prompts/analyzer.xml engine/analyzer.py engine/test_analyzer.py
git commit -m "feat(engine): préparation du prompt d'analyse par chunk"
```

---

### Task 4: `llm.py` — adaptateur LLM (BYOK / gratuit / repli honnête)

**Files:**
- Create: `/Users/garinat_t/Desktop/synopsis/llm.py`
- Test: `/Users/garinat_t/Desktop/synopsis/test_llm.py`

**Interfaces:**
- Produces:
  - `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENCODE_GO_API_KEY`, `OPENCODE_GO_BASE_URL`, `OPENCODE_GO_MODEL` (module-level, lus depuis les variables d'environnement au chargement)
  - `config(llm: dict | None) -> tuple[str, str, str]` (base_url, cle, modele)
  - `class ErreurLLM(Exception)`
  - `completer(prompt: str, llm: dict | None, max_tokens: int, temperature: float = 0.5) -> str`
  - `lister_modeles(base_url: str, cle: str) -> list[str]`
- Consumes: rien (module indépendant, pas de dépendance sur `engine/`)

- [ ] **Step 1: Écrire les tests de `config()` et du repli honnête**

```python
# test_llm.py
from unittest.mock import MagicMock

import httpx
import pytest

import llm


def test_config_priorite_byok():
    base, cle, modele = llm.config({"base_url": "https://api.exemple.com/v1", "cle": "sk-xxx", "modele": "gpt-x"})
    assert (base, cle, modele) == ("https://api.exemple.com/v1", "sk-xxx", "gpt-x")


def test_config_priorite_openrouter_instance(monkeypatch):
    monkeypatch.setattr(llm, "OPENROUTER_API_KEY", "sk-or-instance")
    base, cle, modele = llm.config(None)
    assert base == llm.OPENROUTER_BASE
    assert cle == "sk-or-instance"
    assert modele == llm.OPENROUTER_MODEL


def test_config_rien_configure(monkeypatch):
    monkeypatch.setattr(llm, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(llm, "OPENCODE_GO_API_KEY", "")
    monkeypatch.setattr(llm, "OPENAI_API_KEY", "")
    base, cle, modele = llm.config(None)
    assert (base, cle, modele) == ("", "", "")


def test_completer_leve_si_rien_configure(monkeypatch):
    monkeypatch.setattr(llm, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(llm, "OPENCODE_GO_API_KEY", "")
    monkeypatch.setattr(llm, "OPENAI_API_KEY", "")
    with pytest.raises(llm.ErreurLLM, match="Aucun modèle"):
        llm.completer("prompt", None, max_tokens=100)
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
cd /Users/garinat_t/Desktop/synopsis
pytest test_llm.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'llm'`

- [ ] **Step 3: Implémenter `llm.py`**

```python
# llm.py
"""Adaptateur LLM — résumé de transcript vidéo.

Priorité : BYOK par requête > clé d'instance OpenRouter > OpenCode Go > OpenAI-
compatible > repli honnête (erreur explicite, jamais de résumé inventé)."""
from __future__ import annotations

import os
import time

import httpx

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
OPENROUTER_BASE = "https://openrouter.ai/api/v1"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

OPENCODE_GO_API_KEY = os.getenv("OPENCODE_GO_API_KEY", "")
OPENCODE_GO_BASE_URL = os.getenv("OPENCODE_GO_BASE_URL", "https://opencode.ai/zen/go/v1")
OPENCODE_GO_MODEL = os.getenv("OPENCODE_GO_MODEL", "deepseek-v4-pro")


def config(llm: dict | None) -> tuple[str, str, str]:
    """(base_url, cle, modele) : BYO si fourni et complet, sinon OpenRouter en
    priorité, puis OpenCode Go, puis OpenAI comme fournisseurs par défaut de l'instance."""
    llm = llm or {}
    base = (llm.get("base_url") or "").strip()
    if base:
        return base.rstrip("/"), (llm.get("cle") or "").strip(), (llm.get("modele") or "").strip()
    modele = (llm.get("modele") or "").strip()
    if OPENROUTER_API_KEY:
        return OPENROUTER_BASE, OPENROUTER_API_KEY, modele or OPENROUTER_MODEL
    if OPENCODE_GO_API_KEY:
        return OPENCODE_GO_BASE_URL, OPENCODE_GO_API_KEY, modele or OPENCODE_GO_MODEL
    if OPENAI_API_KEY:
        return OPENAI_BASE_URL, OPENAI_API_KEY, modele or OPENAI_MODEL
    return "", "", ""


class ErreurLLM(Exception):
    """Erreur explicite remontée à l'appelant — jamais de contenu inventé en repli."""


def completer(prompt: str, llm: dict | None, max_tokens: int, temperature: float = 0.5) -> str:
    """Un appel chat-completion, avec un seul retry court sur 429."""
    base, cle, modele = config(llm)
    if not cle or not modele:
        raise ErreurLLM("Aucun modèle LLM configuré (ni BYOK, ni clé par défaut de l'instance).")
    headers = {"Authorization": f"Bearer {cle}"}
    payload = {"model": modele, "temperature": temperature, "max_tokens": max_tokens,
               "messages": [{"role": "user", "content": prompt}]}
    with httpx.Client(timeout=120) as c:
        for tentative in (1, 2):
            r = c.post(f"{base}/chat/completions", json=payload, headers=headers)
            if r.status_code == 429 and tentative == 1:
                time.sleep(3)
                continue
            if r.status_code == 429:
                raise ErreurLLM("Modèle gratuit saturé (429) — réessaie dans un instant ou fournis ta propre clé.")
            if r.status_code >= 400:
                raise ErreurLLM(f"Erreur fournisseur ({r.status_code}) : {r.text[:200]}")
            data = r.json()
            contenu = (data.get("choices") or [{}])[0].get("message", {}).get("content")
            if not contenu:
                raise ErreurLLM("Le modèle a renvoyé une réponse vide.")
            return contenu.strip()
    raise ErreurLLM("Modèle gratuit saturé — réessaie dans un instant ou fournis ta propre clé.")


def lister_modeles(base_url: str, cle: str) -> list[str]:
    """Liste les modèles disponibles chez un fournisseur OpenAI-compatible (BYOK)."""
    headers = {"Authorization": f"Bearer {cle}"}
    with httpx.Client(timeout=15) as c:
        r = c.get(f"{base_url.rstrip('/')}/models", headers=headers)
        r.raise_for_status()
        data = r.json()
    return sorted([m["id"] for m in data.get("data", []) if m.get("id")], key=lambda x: x.lower())
```

- [ ] **Step 4: Vérifier que les 4 premiers tests passent**

```bash
pytest test_llm.py -v
```

Expected: 4 PASS

- [ ] **Step 5: Ajouter les tests d'appel réseau (mockés) et de retry 429**

Ajouter à la fin de `test_llm.py` :

```python
def test_completer_appelle_le_fournisseur(monkeypatch):
    reponse = MagicMock(status_code=200)
    reponse.json.return_value = {"choices": [{"message": {"content": "  Résultat  "}}]}

    mock_client = MagicMock()
    mock_client.__enter__.return_value.post.return_value = reponse
    monkeypatch.setattr(httpx, "Client", lambda **kw: mock_client)

    texte = llm.completer("prompt", {"base_url": "https://api.exemple.com/v1", "cle": "sk-x", "modele": "m"}, max_tokens=100)
    assert texte == "Résultat"


def test_completer_429_puis_succes_second_essai(monkeypatch):
    reponse_429 = MagicMock(status_code=429, text="rate limited")
    reponse_ok = MagicMock(status_code=200)
    reponse_ok.json.return_value = {"choices": [{"message": {"content": "Résultat"}}]}

    mock_client = MagicMock()
    mock_client.__enter__.return_value.post.side_effect = [reponse_429, reponse_ok]
    monkeypatch.setattr(httpx, "Client", lambda **kw: mock_client)
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)

    texte = llm.completer("prompt", {"base_url": "https://api.exemple.com/v1", "cle": "sk-x", "modele": "m"}, max_tokens=100)
    assert texte == "Résultat"


def test_completer_429_persistant_leve_erreur_explicite(monkeypatch):
    reponse = MagicMock(status_code=429, text="rate limited")

    mock_client = MagicMock()
    mock_client.__enter__.return_value.post.return_value = reponse
    monkeypatch.setattr(httpx, "Client", lambda **kw: mock_client)
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)

    with pytest.raises(llm.ErreurLLM, match="saturé"):
        llm.completer("prompt", {"base_url": "https://api.exemple.com/v1", "cle": "sk-x", "modele": "m"}, max_tokens=100)


def test_lister_modeles_trie_les_ids(monkeypatch):
    reponse = MagicMock()
    reponse.json.return_value = {"data": [{"id": "z-model"}, {"id": "a-model"}]}
    reponse.raise_for_status.return_value = None

    mock_client = MagicMock()
    mock_client.__enter__.return_value.get.return_value = reponse
    monkeypatch.setattr(httpx, "Client", lambda **kw: mock_client)

    assert llm.lister_modeles("https://api.exemple.com/v1", "sk-x") == ["a-model", "z-model"]
```

- [ ] **Step 6: Lancer toute la suite du module**

```bash
pytest test_llm.py -v
```

Expected: 8 PASS

- [ ] **Step 7: Commit**

```bash
git add llm.py test_llm.py
git commit -m "feat: adaptateur LLM BYOK/gratuit avec repli honnête"
```

---

### Task 5: `engine/fusion.py` + `prompts/fusion.xml` — fusion des analyses partielles

**Files:**
- Create: `/Users/garinat_t/Desktop/synopsis/prompts/fusion.xml`
- Create: `/Users/garinat_t/Desktop/synopsis/engine/fusion.py`
- Test: `/Users/garinat_t/Desktop/synopsis/engine/test_fusion.py`

**Interfaces:**
- Produces: `fusionner(analyses: list[str], titre_video: str, langue: str = "Français", llm_body: dict | None = None) -> str`
- Consumes: `llm.completer(prompt, llm, max_tokens, temperature)` (Task 4) ; `analyses` = liste de sorties markdown au format `prompts/analyzer.xml` (une par chunk, produites à l'étape d'orchestration de Task 6)

- [ ] **Step 1: Créer `prompts/fusion.xml`**

```xml
<prompt_definition>
  <role>
    Tu es un Expert en Synthèse de Contenu Multimédia. Ta mission est de fusionner plusieurs analyses partielles en un rapport final cohérent et complet.
  </role>
  <task_instructions>
    1. FUSION : Combine les résumés détaillés en une narration continue et fluide.
    2. CHAPITRAGE : Fusionne les tableaux de chapitrage par ordre chronologique.
    3. INSIGHTS : Conserve les meilleurs moments de chaque partie, garde les 3 les plus pertinents.
    4. COHÉRENCE : Élimine les répétitions, unifie le style.
  </task_instructions>
  <constraints>
    - SORTIE : Toujours en Markdown.
    - FIDÉLITÉ : Ne pas inventer d'informations.
    - TIMESTAMPS : Respecter l'ordre chronologique.
    - LANGUE : Tout en {output_language}. C'est obligatoire.
    - COUVERTURE : Couvre l'intégralité du contenu vidéo, du début à la fin. Ne jamais tronquer.
  </constraints>
  <output_format>
    # 📺 ANALYSE VIDÉO : {video_title}
    *Langue Source :* [Langue]

    ## 🚀 Résumé Exécutif (TL;DR)
    > [Résumé rapide en 3-5 phrases]

    ## 📍 Chapitrage Temporel
    | Time | Sujet | Description |
    | :--- | :--- | :--- |
    | [MM:SS] | *[Titre]* | [Valeur ajoutée] |

    ## 💡 Top 3 Moments Forts (Insights)
    1. *[Titre]* [MM:SS] : [Explication]
    2. *[Titre]* [MM:SS] : [Explication]
    3. *[Titre]* [MM:SS] : [Explication]

    ## 📝 Résumé Détaillé
    ### 🔹 Contexte et Enjeux
    [Détails ici...]
    ### 🔹 Points Techniques / Arguments
    [Détails ici...]
  </output_format>
  <self_verification>
    - Les timestamps sont-ils en ordre chronologique ?
    - Y a-t-il des répétitions entre les sections ?
    - Le rapport est-il cohérent et fluide ?
  </self_verification>
</prompt_definition>

---
ANALYSES PRÉCÉDENTES:
{analyses}
```

- [ ] **Step 2: Écrire les tests**

```python
# engine/test_fusion.py
from unittest.mock import patch

import fusion

ANALYSE_1 = """# 📺 ANALYSE VIDÉO : Titre
*Langue Source :* Français

## 🚀 Résumé Exécutif (TL;DR)
> Un résumé court de la première moitié.

## 📍 Chapitrage Temporel
| Time | Sujet | Description |
| :--- | :--- | :--- |
| [00:10] | *Introduction* | Présentation du sujet |

## 💡 Top 3 Moments Forts (Insights)
1. *Point clé A* [00:15] : Explication A

## 📝 Résumé Détaillé
### 🔹 Contexte
Premier bloc de contenu.
"""

ANALYSE_2 = """# 📺 ANALYSE VIDÉO : Titre
*Langue Source :* Français

## 🚀 Résumé Exécutif (TL;DR)
> Un résumé court de la seconde moitié.

## 📍 Chapitrage Temporel
| Time | Sujet | Description |
| :--- | :--- | :--- |
| [05:00] | *Conclusion* | Synthèse finale |

## 💡 Top 3 Moments Forts (Insights)
1. *Point clé B* [05:05] : Explication B

## 📝 Résumé Détaillé
### 🔹 Conclusion
Second bloc de contenu.
"""


def test_fusionner_un_seul_chunk_renvoie_tel_quel():
    assert fusion.fusionner([ANALYSE_1], "Titre") == ANALYSE_1


def test_extraire_chapitres():
    chapitres = fusion._extraire_chapitres(ANALYSE_1)
    assert chapitres == [{"timestamp": "00:10", "ts_secondes": 10,
                           "sujet": "Introduction", "description": "Présentation du sujet"}]


def test_extraire_insights():
    insights = fusion._extraire_insights(ANALYSE_1)
    assert insights == [{"titre": "Point clé A", "timestamp": "00:15", "description": "Explication A"}]


@patch("llm.completer", return_value="### 🔹 Fusionné\nContenu fusionné cohérent.")
def test_fusionner_plusieurs_chunks(mock_completer):
    rapport = fusion.fusionner([ANALYSE_1, ANALYSE_2], "Titre", "Français")

    assert "Introduction" in rapport
    assert "Conclusion" in rapport
    assert "Point clé A" in rapport and "Point clé B" in rapport
    assert "Contenu fusionné cohérent." in rapport
    mock_completer.assert_called_once()
```

- [ ] **Step 3: Vérifier que les tests échouent**

```bash
cd /Users/garinat_t/Desktop/synopsis
pytest engine/test_fusion.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'fusion'`

- [ ] **Step 4: Implémenter `engine/fusion.py`**

```python
# engine/fusion.py
"""Fusion de résumés partiels en un rapport final.

Chapitrage et points clés sont fusionnés par du code (dédoublonnage, tri
chronologique) ; seul le résumé détaillé est refusionné par le LLM, à partir du
gabarit `prompts/fusion.xml`."""
from __future__ import annotations

import re
from pathlib import Path

import llm

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def charger_prompt_fusion() -> str:
    return (_PROMPTS_DIR / "fusion.xml").read_text(encoding="utf-8")


def _formater(gabarit: str, **kw) -> str:
    for cle, val in kw.items():
        gabarit = gabarit.replace("{" + cle + "}", str(val))
    return gabarit


def _extraire_chapitres(analyse: str) -> list[dict]:
    """Extrait les lignes du tableau `## 📍 Chapitrage Temporel`."""
    chapitres = []
    if not analyse:
        return chapitres
    motif_section = r"##\s*📍\s*Chapitrage\s*Temporel\s*\n(.*?)(?=\n##\s|\Z)"
    m = re.search(motif_section, analyse, re.DOTALL | re.IGNORECASE)
    if not m:
        return chapitres
    section = m.group(1)
    motif_ligne = r"\|\s*\[?(\d{1,3}:\d{2})\]?\s*\|\s*\*?(.+?)\*?\s*\|\s*(.+?)\s*\|"
    for ligne in re.finditer(motif_ligne, section):
        ts_brut = ligne.group(1)
        sujet = ligne.group(2).strip().rstrip("*").lstrip("*")
        desc = ligne.group(3).strip()
        if sujet.startswith(":") and desc.startswith(":"):
            continue
        parts = ts_brut.split(":")
        ts_secondes = int(parts[0]) * 60 + int(parts[1])
        chapitres.append({"timestamp": ts_brut, "ts_secondes": ts_secondes,
                           "sujet": sujet, "description": desc})
    return chapitres


def _extraire_insights(analyse: str) -> list[dict]:
    """Extrait les entrées de `## 💡 Top 3 Moments Forts`."""
    insights = []
    if not analyse:
        return insights
    motif_section = r"##\s*💡\s*Top\s*\d*\s*Moments\s*Forts.*?\n(.*?)(?=\n##\s|\Z)"
    m = re.search(motif_section, analyse, re.DOTALL | re.IGNORECASE)
    if not m:
        return insights
    section = m.group(1)
    motif_item = r"\d+\.\s*\*?(.+?)\*?\s*\[?(\d{1,3}:\d{2})\]?\s*:\s*(.+)"
    for item in re.finditer(motif_item, section):
        insights.append({"titre": item.group(1).strip().rstrip("*").lstrip("*"),
                          "timestamp": item.group(2), "description": item.group(3).strip()})
    return insights


def _extraire_corps_resume(analyse: str) -> str:
    m = re.search(r"##\s*📝\s*Résumé\s*Détaillé\s*\n(.*)", analyse, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _extraire_resume_executif(analyse: str) -> str:
    m = re.search(r"##\s*🚀\s*Résumé\s*Exécutif.*?\n>\s*(.*?)(?=\n##\s|\n\*\*|\Z)",
                  analyse, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _fusionner_chapitres(listes: list[list[dict]]) -> list[dict]:
    tous = [c for l in listes for c in l]
    tous.sort(key=lambda x: x.get("ts_secondes", 0))
    vus, uniques = set(), []
    for c in tous:
        ts = c.get("ts_secondes", 0)
        if ts not in vus:
            vus.add(ts)
            uniques.append(c)
    return uniques


def _selectionner_top_insights(listes: list[list[dict]], max_insights: int = 3) -> list[dict]:
    tous, vus = [], set()
    for l in listes:
        for ins in l:
            cle = ins.get("titre", "").lower()
            if cle and cle not in vus:
                vus.add(cle)
                tous.append(ins)
    return tous[:max_insights]


def _table_chapitres_markdown(chapitres: list[dict]) -> str:
    if not chapitres:
        return ""
    lignes = ["## 📍 Chapitrage Temporel", "| Time | Sujet | Description |", "| :--- | :--- | :--- |"]
    for c in chapitres:
        lignes.append(f"| {c.get('timestamp', '')} | *{c.get('sujet', '')}* | {c.get('description', '')} |")
    return "\n".join(lignes)


def _liste_insights_markdown(insights: list[dict]) -> str:
    if not insights:
        return ""
    lignes = ["## 💡 Top 3 Moments Forts (Insights)"]
    for i, ins in enumerate(insights, 1):
        lignes.append(f"{i}. *{ins.get('titre', '')}* [{ins.get('timestamp', '')}] : {ins.get('description', '')}")
    return "\n".join(lignes)


def fusionner(analyses: list[str], titre_video: str, langue: str = "Français",
              llm_body: dict | None = None) -> str:
    """Fusionne plusieurs analyses partielles (une par chunk) en un rapport unique.

    Chapitrage et insights sont fusionnés par code (dédoublonnés, triés). Le résumé
    détaillé est refusionné par le LLM à partir de `prompts/fusion.xml` — si un seul
    chunk existe, on renvoie l'analyse telle quelle (rien à fusionner)."""
    if len(analyses) == 1:
        return analyses[0]

    listes_chapitres, listes_insights, corps, execs = [], [], [], []
    for a in analyses:
        if not a:
            continue
        listes_chapitres.append(_extraire_chapitres(a))
        listes_insights.append(_extraire_insights(a))
        c = _extraire_corps_resume(a)
        if c:
            corps.append(c)
        e = _extraire_resume_executif(a)
        if e:
            execs.append(e)

    chapitres_fusionnes = _fusionner_chapitres(listes_chapitres)
    insights_choisis = _selectionner_top_insights(listes_insights)
    resume_exec = " ".join(execs) if execs else "Analyse de la vidéo."

    if corps:
        prompt = _formater(charger_prompt_fusion(), video_title=titre_video,
                            output_language=langue, analyses="\n\n---\n\n".join(corps))
        resume_detaille = llm.completer(prompt, llm_body, max_tokens=6000, temperature=0.5)
    else:
        resume_detaille = analyses[0]

    corps_final = resume_detaille.strip()
    for prefixe in ("## 📝 Résumé Détaillé", "## 📝 Résumé Détaille"):
        if corps_final.startswith(prefixe):
            corps_final = corps_final[len(prefixe):].strip()

    parties = [
        f"# 📺 ANALYSE VIDÉO : {titre_video}",
        f"*Langue Source :* {langue}\n",
        "## 🚀 Résumé Exécutif (TL;DR)",
        f"> {resume_exec.strip()}\n",
        _table_chapitres_markdown(chapitres_fusionnes),
        "",
        _liste_insights_markdown(insights_choisis),
        "",
        "## 📝 Résumé Détaillé",
        corps_final,
    ]
    return "\n\n".join(p for p in parties if p)
```

- [ ] **Step 5: Vérifier que les tests passent**

```bash
pytest engine/test_fusion.py -v
```

Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add prompts/fusion.xml engine/fusion.py engine/test_fusion.py
git commit -m "feat(engine): fusion des analyses partielles en un rapport unique"
```

---

### Task 6: `main.py` — endpoints FastAPI

**Files:**
- Create: `/Users/garinat_t/Desktop/synopsis/main.py`
- Test: `/Users/garinat_t/Desktop/synopsis/test_main.py`

**Interfaces:**
- Produces: `app` (instance FastAPI) — consommée par `api/index.py` (Task 8) et par `Dockerfile`/`uvicorn` (Task 9)
- Consumes: `extractor.transcript_youtube()` (Task 1), `chunker.chunk_transcript()` (Task 2), `analyzer.preparer_prompt()` (Task 3), `llm.completer()` / `llm.lister_modeles()` (Task 4), `fusion.fusionner()` (Task 5)

- [ ] **Step 1: Écrire les tests**

```python
# test_main.py
from unittest.mock import patch

from fastapi.testclient import TestClient

import extractor
import main

client = TestClient(main.app)


def _transcript_court():
    return {
        "video_id": "dQw4w9WgXcQ",
        "transcript": [{"text": "Bonjour le monde", "start": 0.0, "duration": 2.0}],
        "langue": "fr",
        "titre": "Vidéo de test",
        "duree_minutes": 0.03,
    }


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["service"] == "synopsis"


def test_modeles_sans_cle_renvoie_422():
    r = client.get("/modeles", params={"cle": "", "base_url": "https://api.exemple.com/v1"})
    assert r.status_code == 422


@patch("main.llm.lister_modeles", return_value=["a-model", "b-model"])
def test_modeles_avec_cle(mock_lister):
    r = client.get("/modeles", params={"cle": "sk-x", "base_url": "https://api.exemple.com/v1"})
    assert r.status_code == 200
    assert r.json() == {"modeles": ["a-model", "b-model"]}


@patch("main.extractor.transcript_youtube", return_value=_transcript_court())
@patch("main.llm.completer", return_value="## 📝 Résumé Détaillé\nContenu résumé.")
def test_resumer_video_valide(mock_completer, mock_transcript):
    r = client.post("/resumer", json={"url": "https://youtu.be/dQw4w9WgXcQ", "langue": "Français"})
    assert r.status_code == 200
    body = r.json()
    assert body["video_id"] == "dQw4w9WgXcQ"
    assert "Contenu résumé." in body["rapport"]


@patch("main.extractor.transcript_youtube", side_effect=extractor.ErreurExtraction("URL YouTube invalide."))
def test_resumer_url_invalide(mock_transcript):
    r = client.post("/resumer", json={"url": "pas-une-url", "langue": "Français"})
    assert r.status_code == 422
    assert "invalide" in r.json()["detail"]


@patch("main.fusion.fusionner", side_effect=main.llm.ErreurLLM("Modèle gratuit saturé — réessaie."))
@patch("main.extractor.transcript_youtube", return_value=_transcript_court())
@patch("main.llm.completer", return_value="## 📝 Résumé Détaillé\nContenu résumé.")
def test_resumer_erreur_fusion_renvoie_422_pas_500(mock_completer, mock_transcript, mock_fusion):
    """La fusion appelle aussi llm.completer en interne (Task 5) — une erreur LLM à
    cette étape doit rester un 422 explicite, pas un 500 non géré."""
    r = client.post("/resumer", json={"url": "https://youtu.be/dQw4w9WgXcQ", "langue": "Français"})
    assert r.status_code == 422
    assert "saturé" in r.json()["detail"]


@patch("main.llm.completer", return_value="Oui, il est question de X.")
def test_qa(mock_completer):
    r = client.post("/qa", json={"contexte": "Résumé : la vidéo parle de X.", "question": "De quoi ça parle ?"})
    assert r.status_code == 200
    assert "X" in r.json()["reponse"]


def test_qa_sans_contexte_renvoie_422():
    r = client.post("/qa", json={"contexte": "", "question": "Quoi ?"})
    assert r.status_code == 422
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
cd /Users/garinat_t/Desktop/synopsis
pytest test_main.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Créer un `static/index.html` minimal temporaire (pour que `main.py` puisse le servir sans erreur)**

```html
<!DOCTYPE html>
<html><head><title>Synopsis</title></head><body>À remplacer en Task 7</body></html>
```

- [ ] **Step 4: Implémenter `main.py`**

```python
# main.py
"""Synopsis — résumé de vidéo YouTube par IA.

Transcript natif YouTube (pas de téléchargement, pas de ffmpeg, pas de Whisper) →
découpage en chunks → résumé par chunk (LLM) → fusion en un rapport unique
(chapitres horodatés + points clés). Stateless : rien n'est stocké, chaque appel
est indépendant. LLM gratuit par défaut (clé OpenRouter d'instance) ou BYOK par
requête — jamais de résumé inventé si aucun modèle n'est configuré."""
import os
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent / "engine"))

import analyzer as prompt_analyzer
import chunker
import extractor
import fusion

import llm

app = FastAPI(title="Synopsis", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])


class ResumerBody(BaseModel):
    url: str
    langue: str = "Français"
    llm: Optional[dict] = None


class QaBody(BaseModel):
    contexte: str
    question: str
    llm: Optional[dict] = None


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return Path(__file__).parent.joinpath("static/index.html").read_text(encoding="utf-8")


@app.get("/sante", tags=["système"])
def sante():
    fournisseur = None
    if llm.OPENROUTER_API_KEY:
        fournisseur = "openrouter"
    elif llm.OPENCODE_GO_API_KEY:
        fournisseur = "opencode-go"
    elif llm.OPENAI_API_KEY:
        fournisseur = "openai"
    return {"statut": "ok", "service": "synopsis", "version": app.version,
            "resume_configure": bool(fournisseur), "fournisseur_actif": fournisseur}


@app.get("/modeles", tags=["synopsis"])
def modeles(cle: str = Query(...), base_url: str = Query("")):
    """Liste les modèles disponibles pour une API OpenAI-compatible (BYOK)."""
    cle = cle.strip()
    if not cle:
        raise HTTPException(422, "Une clé API est nécessaire.")
    base = (base_url or "").strip()
    if not base:
        raise HTTPException(422, "Une URL de base est nécessaire.")
    try:
        return {"modeles": llm.lister_modeles(base, cle)}
    except Exception as e:
        raise HTTPException(502, f"Impossible de récupérer les modèles : {str(e)[:150]}")


@app.post("/resumer", tags=["synopsis"])
def resumer(body: ResumerBody):
    """URL YouTube → transcript natif → chunks → résumé par chunk → fusion."""
    try:
        donnees = extractor.transcript_youtube(body.url)
    except extractor.ErreurExtraction as e:
        raise HTTPException(422, str(e))

    chunks = chunker.chunk_transcript(donnees["transcript"])
    if not chunks:
        raise HTTPException(422, "Transcript vide — impossible de résumer.")

    analyses = []
    for c in chunks:
        prompt = prompt_analyzer.preparer_prompt(c["text"], donnees["titre"], body.langue)
        try:
            analyses.append(llm.completer(prompt, body.llm, max_tokens=4000, temperature=0.5))
        except llm.ErreurLLM as e:
            raise HTTPException(422, str(e))

    try:
        rapport = fusion.fusionner(analyses, donnees["titre"], body.langue, body.llm)
    except llm.ErreurLLM as e:
        raise HTTPException(422, str(e))
    return {"video_id": donnees["video_id"], "titre": donnees["titre"],
            "langue_source": donnees["langue"], "duree_minutes": donnees["duree_minutes"],
            "rapport": rapport}


@app.post("/qa", tags=["synopsis"])
def qa(body: QaBody):
    """Question sur un résumé déjà généré — un seul appel LLM, rien stocké."""
    if not body.contexte.strip() or not body.question.strip():
        raise HTTPException(422, "Contexte et question sont requis.")
    prompt = (
        "Tu réponds à une question sur le contenu d'une vidéo, en te basant "
        "UNIQUEMENT sur le résumé fourni ci-dessous. N'invente rien qui n'y figure "
        "pas ; si la réponse n'est pas dans le résumé, dis-le clairement.\n\n"
        f"RÉSUMÉ :\n{body.contexte}\n\nQUESTION : {body.question}"
    )
    try:
        return {"reponse": llm.completer(prompt, body.llm, max_tokens=800, temperature=0.3)}
    except llm.ErreurLLM as e:
        raise HTTPException(422, str(e))
```

- [ ] **Step 5: Vérifier que les tests passent**

```bash
pytest test_main.py -v
```

Expected: 8 PASS

- [ ] **Step 6: Lancer toute la suite du projet pour confirmer qu'aucune régression n'a été introduite**

```bash
pytest -v
```

Expected: 35 PASS (8 extractor + 5 chunker + 2 analyzer + 8 llm + 4 fusion + 8 main = 35) — l'important est **0 FAIL**, le total exact affiché fait foi.

- [ ] **Step 7: Commit**

```bash
git add main.py test_main.py static/index.html
git commit -m "feat: endpoints FastAPI /resumer /qa /modeles /sante"
```

---

### Task 7: `static/index.html` — front-end (charte portrait-cosmique)

**Files:**
- Modify: `/Users/garinat_t/Desktop/synopsis/static/index.html` (remplace le placeholder de Task 6)

**Interfaces:**
- Consumes : endpoints de Task 6 — `GET /sante`, `GET /modeles?cle=&base_url=`, `POST /resumer {url, langue, llm?}`, `POST /qa {contexte, question, llm?}`

- [ ] **Step 1: Lire la référence pour copier la charte exacte**

```bash
cat /Users/garinat_t/Desktop/portrait-cosmique/static/index.html
```

Repérer précisément : le bloc `<style>` (CSS vars `--bg/--panel/--panel2/--border/--text/--muted/--accent/--accent2/--danger`, classes `.wrap/.panel/.btn/.btn.secondary/.btn.ghost/details.avance/@media print`), le bloc BYOK complet (`FOURNISSEURS`, `changerFournisseur()`, `chargerModeles()`, `chargerConfigLLM()`/`sauvegarderConfigLLM()`/`effacerConfigLLM()`, `basculerVisibiliteCle()`, `LLM_STORAGE_KEY`), le toggle FR/EN (`I18N`, `setLangue()`), et `telechargerHTML()`.

- [ ] **Step 2: Écrire `static/index.html`**

Reprendre l'intégralité du `<style>` de `portrait-cosmique/static/index.html` tel quel (CSS vars, `.wrap`, `.panel`, boutons, `details.avance`, `@media print`) — copier-coller le bloc `<style>...</style>` sans modification.

Reprendre tel quel le bloc BYOK complet (constantes `FOURNISSEURS`, fonctions `changerFournisseur()`, `chargerModeles()` → adapté pour appeler `/modeles` de ce repo, `chargerConfigLLM()`/`sauvegarderConfigLLM()`/`effacerConfigLLM()`, `basculerVisibiliteCle()`, `debounce()`, `LLM_STORAGE_KEY` renommé `"synopsis-llm"`) et le toggle FR/EN (`setLangue()`, objet `I18N` adapté aux textes de Synopsis).

Remplacer le corps du formulaire et la zone résultat par :

```html
<div class="panel">
  <form id="form-resumer">
    <label data-t="l_url">URL de la vidéo YouTube</label>
    <input id="url" type="text" placeholder="https://www.youtube.com/watch?v=..." required>

    <label style="margin-top:12px;" data-t="l_langue_resume">Langue du résumé</label>
    <select id="langue_resume">
      <option value="Français">Français</option>
      <option value="English">English</option>
      <option value="Español">Español</option>
      <option value="Deutsch">Deutsch</option>
      <option value="Português">Português</option>
      <option value="Italiano">Italiano</option>
    </select>

    <details class="avance">
      <summary data-t="l_options">Options avancées</summary>
      <label style="margin-top:16px;" data-t="l_byok">Configuration IA personnelle</label>
      <p class="sous" style="margin:4px 0 8px;" data-t="l_byok_desc">Votre clé est sauvegardée localement dans votre navigateur. Elle n'est transmise au serveur qu'au moment du résumé.</p>
      <label data-t="l_fournisseur">Fournisseur</label>
      <select id="llm_fournisseur">
        <option value="openrouter">OpenRouter</option>
        <option value="opencodego">OpenCode Go</option>
        <option value="openai">OpenAI</option>
        <option value="custom" data-t="o_custom">Personnalisé</option>
      </select>
      <div id="llm_base_url_group">
        <label style="margin-top:6px;" data-t="l_base_url">URL de l'API</label>
        <input id="llm_base_url" type="text" placeholder="https://api.openai.com/v1" readonly>
      </div>
      <label style="margin-top:6px;" data-t="l_cle">Clé API</label>
      <div id="llm_cle_wrapper" style="position:relative;">
        <input id="llm_cle" type="password" placeholder="sk-..." style="padding-right:46px;">
        <button type="button" onclick="basculerVisibiliteCle()" id="btn-voir-cle" style="position:absolute; right:2px; top:50%; transform:translateY(-50%); background:none; border:none; cursor:pointer; font-size:1.1rem; padding:6px 10px; color:var(--muted); line-height:1;">👁️</button>
      </div>
      <div style="display:flex; gap:8px; align-items:center; margin-top:6px;">
        <label data-t="l_modele" style="margin:0;">Modèle</label>
        <button type="button" class="btn ghost" onclick="chargerModeles()" data-t="b_charger_modeles" style="font-size:.78rem; padding:4px 10px;">🔄 Charger les modèles</button>
        <span id="llm-modeles-status" style="font-size:.75rem; color:var(--muted);"></span>
      </div>
      <select id="llm_modele_select" style="margin-top:4px; display:none;"><option value="">--</option></select>
      <input id="llm_modele" type="text" placeholder="gpt-4o-mini">
      <div style="display:flex; gap:8px; align-items:center; margin-top:8px;">
        <span id="llm-status" style="font-size:.78rem; color:var(--accent2);" data-t="l_llm_vide">Aucune config sauvegardée</span>
        <button type="button" class="btn ghost" onclick="effacerConfigLLM()" data-t="b_effacer_llm" style="margin-left:auto;">🗑️ Effacer</button>
      </div>
    </details>

    <details class="avance">
      <summary data-t="l_multi">Résumer plusieurs vidéos</summary>
      <p class="sous" style="margin:4px 0 8px;" data-t="l_multi_desc">Colle plusieurs URLs YouTube, une par ligne. Chaque vidéo est résumée séparément.</p>
      <textarea id="urls_multi" rows="4" style="width:100%; background:var(--panel2); border:1px solid var(--border); color:var(--text); padding:10px 12px; border-radius:8px; font-size:.9rem;" placeholder="https://youtu.be/...&#10;https://youtu.be/..."></textarea>
      <button type="button" class="btn secondary" style="margin-top:8px;" onclick="resumerPlusieurs()" data-t="b_multi">Résumer toutes ces vidéos</button>
    </details>

    <div class="btns">
      <button type="submit" class="btn" data-t="b_resumer">✨ Résumer</button>
    </div>
    <div id="erreur" class="erreur"></div>
  </form>
</div>

<div id="resultats"></div>
```

- [ ] **Step 3: Ajouter le JavaScript propre à Synopsis (résumé, chat, export, multi-vidéos)**

Ajouter dans `<script>`, après la reprise des fonctions BYOK/i18n de portrait-cosmique :

```javascript
const I18N_SYNOPSIS = {
  fr: {
    l_url: "URL de la vidéo YouTube", l_langue_resume: "Langue du résumé",
    l_multi: "Résumer plusieurs vidéos",
    l_multi_desc: "Colle plusieurs URLs YouTube, une par ligne. Chaque vidéo est résumée séparément.",
    b_multi: "Résumer toutes ces vidéos", b_resumer: "✨ Résumer",
    erreur_generique: "Une erreur est survenue.",
    b_qa: "Poser la question", l_qa_placeholder: "Une question sur cette vidéo ?",
    b_html: "⬇️ Télécharger en HTML", b_md: "⬇️ Télécharger en Markdown", b_pdf: "🖨️ Imprimer / Enregistrer en PDF",
  },
  en: {
    l_url: "YouTube video URL", l_langue_resume: "Summary language",
    l_multi: "Summarize multiple videos",
    l_multi_desc: "Paste multiple YouTube URLs, one per line. Each video is summarized separately.",
    b_multi: "Summarize all these videos", b_resumer: "✨ Summarize",
    erreur_generique: "Something went wrong.",
    b_qa: "Ask", l_qa_placeholder: "A question about this video?",
    b_html: "⬇️ Download as HTML", b_md: "⬇️ Download as Markdown", b_pdf: "🖨️ Print / Save as PDF",
  },
};
Object.assign(I18N.fr, I18N_SYNOPSIS.fr);
Object.assign(I18N.en, I18N_SYNOPSIS.en);

function configLLMActuelle() {
  const cle = document.getElementById("llm_cle").value.trim();
  if (!cle) return null;
  const fournisseur = document.getElementById("llm_fournisseur").value;
  let base_url = document.getElementById("llm_base_url").value.trim();
  if (fournisseur !== "custom") base_url = FOURNISSEURS[fournisseur].base_url;
  const modeleSelect = document.getElementById("llm_modele_select");
  const modele = modeleSelect.style.display !== "none" ? modeleSelect.value : document.getElementById("llm_modele").value.trim();
  return { base_url, cle, modele };
}

function md(txt) {
  const esc = (txt || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  return esc.split("\n\n").map(p => "<p>" + p
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/_(.+?)_/g, "<em>$1</em>") + "</p>").join("");
}

async function resumerUne(url) {
  const body = { url, langue: document.getElementById("langue_resume").value, llm: configLLMActuelle() };
  const r = await fetch("/resumer", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body) });
  const d = await r.json();
  if (!r.ok) throw new Error(d.detail || I18N[LANGUE].erreur_generique);
  return d;
}

function blocResultat(d) {
  const t = I18N[LANGUE];
  const div = document.createElement("div");
  div.className = "panel";
  div.innerHTML = `
    <div class="identite"><div class="nom">${d.titre}</div>
      <div class="details">${d.duree_minutes.toFixed(1)} min · ${d.langue_source}</div></div>
    <div class="recit">${md(d.rapport)}</div>
    <div class="btns" style="margin-top:14px;">
      <button type="button" class="btn secondary" data-action="html">${t.b_html}</button>
      <button type="button" class="btn secondary" data-action="md">${t.b_md}</button>
      <button type="button" class="btn secondary" data-action="print">${t.b_pdf}</button>
    </div>
    <details class="avance" style="margin-top:14px;">
      <summary>💬 ${t.b_qa}</summary>
      <input class="qa-question" type="text" placeholder="${t.l_qa_placeholder}">
      <button type="button" class="btn ghost qa-btn" style="margin-top:8px;">${t.b_qa}</button>
      <div class="qa-reponse sous" style="margin-top:8px;"></div>
    </details>`;
  div.querySelector('[data-action="html"]').onclick = () => telechargerResultatHTML(d);
  div.querySelector('[data-action="md"]').onclick = () => telechargerResultatMarkdown(d);
  div.querySelector('[data-action="print"]').onclick = () => window.print();
  div.querySelector(".qa-btn").onclick = async () => {
    const question = div.querySelector(".qa-question").value.trim();
    if (!question) return;
    const zone = div.querySelector(".qa-reponse");
    zone.textContent = "…";
    try {
      const r = await fetch("/qa", { method: "POST", headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ contexte: d.rapport, question, llm: configLLMActuelle() }) });
      const rd = await r.json();
      zone.textContent = r.ok ? rd.reponse : (rd.detail || I18N[LANGUE].erreur_generique);
    } catch (e) { zone.textContent = I18N[LANGUE].erreur_generique; }
  };
  return div;
}

function telechargerResultatHTML(d) {
  const styles = document.querySelector("style").outerHTML;
  const html = `<!DOCTYPE html><html lang="${LANGUE}"><head><meta charset="utf-8"><title>${d.titre}</title>${styles}</head>
    <body><div class="wrap">${blocResultat(d).outerHTML}</div></body></html>`;
  const blob = new Blob([html], { type: "text/html" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `synopsis-${d.video_id}.html`;
  a.click();
}

function telechargerResultatMarkdown(d) {
  const blob = new Blob([d.rapport], { type: "text/markdown" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `synopsis-${d.video_id}.md`;
  a.click();
}

document.getElementById("form-resumer").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const err = document.getElementById("erreur");
  err.textContent = "";
  const zone = document.getElementById("resultats");
  zone.innerHTML = "";
  try {
    const d = await resumerUne(document.getElementById("url").value.trim());
    zone.appendChild(blocResultat(d));
  } catch (e) {
    err.textContent = e.message || I18N[LANGUE].erreur_generique;
  }
});

async function resumerPlusieurs() {
  const urls = document.getElementById("urls_multi").value.split("\n").map(u => u.trim()).filter(Boolean);
  const zone = document.getElementById("resultats");
  zone.innerHTML = "";
  for (const url of urls) {
    const placeholder = document.createElement("div");
    placeholder.className = "panel";
    placeholder.textContent = `${url} — …`;
    zone.appendChild(placeholder);
    try {
      const d = await resumerUne(url);
      zone.replaceChild(blocResultat(d), placeholder);
    } catch (e) {
      placeholder.textContent = `${url} — ${e.message || I18N[LANGUE].erreur_generique}`;
      placeholder.classList.add("erreur");
    }
  }
}
```

- [ ] **Step 4: Vérification manuelle locale (sans clé LLM, juste le service et la page)**

```bash
cd /Users/garinat_t/Desktop/synopsis
uvicorn main:app --reload --port 8420 &
sleep 2
curl -s http://localhost:8420/sante
```

Expected: `{"statut":"ok","service":"synopsis",...}`

Ouvrir `http://localhost:8420` dans un navigateur : vérifier que la page s'affiche avec le thème sombre/violet, que le toggle FR/EN fonctionne, que « Options avancées » se déplie et affiche le bloc BYOK, que « Résumer plusieurs vidéos » se déplie et affiche le textarea.

```bash
kill %1
```

- [ ] **Step 5: Commit**

```bash
git add static/index.html
git commit -m "feat(front): charte portrait-cosmique + résumé/chat/multi-vidéos/export"
```

---

### Task 8: Déploiement Vercel — `api/index.py` + `vercel.json`

**Files:**
- Create: `/Users/garinat_t/Desktop/synopsis/api/index.py`
- Create: `/Users/garinat_t/Desktop/synopsis/vercel.json`

**Interfaces:**
- Consumes: `main.app` (Task 6)

- [ ] **Step 1: Créer `api/index.py`**

```python
# api/index.py
"""Point d'entrée Vercel — réexporte l'application FastAPI de main.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app  # noqa: E402,F401
```

- [ ] **Step 2: Créer `vercel.json`**

```json
{
  "version": 2,
  "builds": [
    { "src": "api/index.py", "use": "@vercel/python" }
  ],
  "routes": [
    { "src": "/(.*)", "dest": "api/index.py" }
  ]
}
```

- [ ] **Step 3: Vérifier localement que `api/index.py` s'importe sans erreur**

```bash
cd /Users/garinat_t/Desktop/synopsis
python3 -c "from api.index import app; print(app.title)"
```

Expected: `Synopsis`

- [ ] **Step 4: Commit**

```bash
git add api/index.py vercel.json
git commit -m "feat: wiring Vercel (FastAPI ASGI en fonction serverless)"
```

---

### Task 9: Auto-hébergement Docker — Dockerfile, docker-compose, install.sh, .env.example

**Files:**
- Create: `/Users/garinat_t/Desktop/synopsis/Dockerfile`
- Create: `/Users/garinat_t/Desktop/synopsis/docker-compose.yml`
- Create: `/Users/garinat_t/Desktop/synopsis/install.sh`
- Create: `/Users/garinat_t/Desktop/synopsis/.env.example`

**Interfaces:**
- Consumes: `main.py`, `llm.py`, `engine/`, `prompts/`, `static/` (Tasks 1-7)

- [ ] **Step 1: Écrire `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY engine/ ./engine/
COPY prompts/ ./prompts/
COPY main.py llm.py ./
COPY static/ ./static/

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8420
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8420/sante')" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8420"]
```

- [ ] **Step 2: Écrire `docker-compose.yml`**

```yaml
services:
  synopsis:
    build: .
    image: synopsis
    ports: ["8420:8420"]
    environment:
      - CORS_ORIGINS=${CORS_ORIGINS:-*}
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-}
      - OPENROUTER_MODEL=${OPENROUTER_MODEL:-meta-llama/llama-3.3-70b-instruct:free}
      - OPENCODE_GO_API_KEY=${OPENCODE_GO_API_KEY:-}
      - OPENCODE_GO_BASE_URL=${OPENCODE_GO_BASE_URL:-https://opencode.ai/zen/go/v1}
      - OPENCODE_GO_MODEL=${OPENCODE_GO_MODEL:-deepseek-v4-pro}
      - OPENAI_API_KEY=${OPENAI_API_KEY:-}
      - OPENAI_BASE_URL=${OPENAI_BASE_URL:-https://api.openai.com/v1}
      - OPENAI_MODEL=${OPENAI_MODEL:-gpt-4o-mini}
```

- [ ] **Step 3: Écrire `.env.example`**

```
# Synopsis — configuration optionnelle
#
# Sans rien renseigner, /resumer et /qa répondent 422 "Aucun modèle LLM configuré"
# tant que le visiteur n'a pas fourni sa propre clé (BYOK, dans le formulaire).
# Ce qui suit configure une clé GRATUITE PAR DÉFAUT pour TOUS les visiteurs de cette
# instance.

# ── Fournisseur 1 : OpenRouter (prioritaire) ──────────────────────────────
# Clé OpenRouter (gratuite à créer sur openrouter.ai). ATTENTION si tu exposes
# cette instance publiquement : n'importe quel visiteur consomme cette clé.
OPENROUTER_API_KEY=

# Modèle gratuit OpenRouter (voir openrouter.ai/models, filtrer sur $0).
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct:free

# ── Fournisseur 2 : OpenCode Go ──────────────────────────────────────────
# Utilisé UNIQUEMENT si OpenRouter n'est PAS configuré.
OPENCODE_GO_API_KEY=
OPENCODE_GO_BASE_URL=https://opencode.ai/zen/go/v1
OPENCODE_GO_MODEL=deepseek-v4-pro

# ── Fournisseur 3 : OpenAI / tout endpoint compatible ─────────────────────
# Utilisé UNIQUEMENT si ni OpenRouter ni OpenCode Go ne sont configurés.
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

# CORS — restreindre en production si besoin (défaut : tout autoriser)
CORS_ORIGINS=*
```

- [ ] **Step 4: Écrire `install.sh`**

```bash
#!/usr/bin/env bash
# Installe et lance Synopsis en une seule commande :
#
#   curl -fsSL https://raw.githubusercontent.com/toussaintgarinat-crypto/synopsis/main/install.sh | bash
#
set -euo pipefail

REPO_URL="https://github.com/toussaintgarinat-crypto/synopsis.git"
DEST="${SYNOPSIS_DIR:-synopsis}"
PORT=8420

info()  { printf '\033[1;36m→ %s\033[0m\n' "$1"; }
ok()    { printf '\033[1;32m✓ %s\033[0m\n' "$1"; }
fail()  { printf '\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

command -v git >/dev/null 2>&1 || fail "git est requis (https://git-scm.com/downloads)."
command -v docker >/dev/null 2>&1 || fail "Docker est requis (https://docs.docker.com/get-docker/)."
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    fail "Docker Compose est requis (inclus dans Docker Desktop, ou 'docker-compose' standalone)."
fi

if [ -d "$DEST/.git" ]; then
    info "Dépôt déjà cloné dans $DEST — mise à jour..."
    git -C "$DEST" pull --ff-only
elif [ -e "$DEST" ]; then
    fail "$DEST existe déjà et n'est pas un dépôt git de Synopsis. Supprime-le, ou lance : SYNOPSIS_DIR=autre-dossier bash install.sh"
else
    info "Clonage dans $DEST..."
    git clone --depth 1 "$REPO_URL" "$DEST"
fi

cd "$DEST"
info "Construction et démarrage (peut prendre une minute la première fois)..."
$COMPOSE up -d --build

info "Attente que le service réponde sur le port $PORT..."
for _ in $(seq 1 30); do
    if curl -fsS "http://localhost:$PORT/sante" >/dev/null 2>&1; then
        ok "Synopsis tourne : http://localhost:$PORT"
        exit 0
    fi
    sleep 1
done

fail "Le service ne répond pas après 30s — vérifie les logs : (cd $DEST && $COMPOSE logs)"
```

- [ ] **Step 4bis: Rendre `install.sh` exécutable**

```bash
chmod +x install.sh
```

- [ ] **Step 5: Vérifier le build Docker localement**

```bash
cd /Users/garinat_t/Desktop/synopsis
docker compose up -d --build
sleep 3
curl -s http://localhost:8420/sante
```

Expected: `{"statut":"ok","service":"synopsis",...}`

```bash
docker compose down
```

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml install.sh .env.example
git commit -m "feat: auto-hébergement Docker + install.sh"
```

---

### Task 10: Documentation — README bilingue

**Files:**
- Create: `/Users/garinat_t/Desktop/synopsis/README.md`
- Create: `/Users/garinat_t/Desktop/synopsis/README.en.md`

**Interfaces:**
- Consumes: tous les endpoints et le comportement documentés dans les tâches précédentes (rien de nouveau, uniquement de la documentation fidèle au code livré)

- [ ] **Step 1: Écrire `README.md`**

```markdown
# 📺 Synopsis

*[English version](README.en.md)*

Colle l'URL d'une vidéo YouTube : reçois un résumé structuré (chapitres horodatés,
points clés, résumé détaillé) en français ou dans 5 autres langues. Gratuit,
instantané, auto-hébergeable, déployable sur Vercel.

> Résumé généré par IA à partir des sous-titres — vérifie les points importants
> dans la vidéo source avant de t'y fier pour une décision.

## Essayer en ligne

*(à compléter après le déploiement Vercel — Task 12)*

## Installation (auto-hébergée)

### Prérequis

- [Docker](https://docs.docker.com/get-docker/) + Docker Compose.
- `git`, `curl`.
- Port **8420** libre (changeable dans `docker-compose.yml`).

### En une commande

```bash
curl -fsSL https://raw.githubusercontent.com/toussaintgarinat-crypto/synopsis/main/install.sh | bash
```

### Ou manuellement

```bash
git clone https://github.com/toussaintgarinat-crypto/synopsis.git
cd synopsis
docker compose up -d --build
```

Vérifier :

```bash
curl http://localhost:8420/sante
```

Puis ouvrir **http://localhost:8420**.

**Sans Docker** (dev local) :

```bash
pip install -r requirements-dev.txt
uvicorn main:app --reload --port 8420
```

## Ce que tu obtiens

- Résumé structuré : résumé exécutif, chapitrage temporel horodaté, 3 points clés,
  résumé détaillé.
- 6 langues : Français, English, Español, Deutsch, Português, Italiano.
- Chat sur le contenu déjà résumé.
- Plusieurs vidéos d'un coup (colle plusieurs liens, une par ligne).
- Export HTML / Markdown / PDF (impression), 100% navigateur.

## Coût réel : zéro (par défaut)

Le transcript est le sous-titrage natif YouTube — aucun téléchargement, aucun
ffmpeg, aucun Whisper. Seul le résumé passe par un LLM.

## Configurer un LLM

Deux façons, au choix :

1. **Clé personnelle (BYOK)** : dans « Options avancées » du formulaire, choisis un
   fournisseur (OpenRouter, OpenCode Go, OpenAI, ou personnalisé), colle ta clé.
   Elle est sauvegardée uniquement dans ton navigateur (`localStorage`), jamais sur
   le serveur.
2. **Clé d'instance** (si tu auto-héberges) : renseigne `OPENROUTER_API_KEY` (ou
   `OPENCODE_GO_API_KEY` / `OPENAI_API_KEY`) dans `.env` (voir `.env.example`) —
   active un modèle gratuit par défaut pour tous les visiteurs de ton instance.

Sans aucune des deux, `/resumer` et `/qa` répondent une erreur explicite — jamais
de résumé inventé.

## Limites (V1)

- YouTube uniquement (pas Twitch/Vimeo/TikTok/fichiers) — nécessite des
  sous-titres (auto-générés ou non) sur la vidéo.
- Pas de vraie playlist YouTube (l'énumération demanderait une clé YouTube Data
  API) — colle plusieurs liens à la place.
- Pas de transcription audio (Whisper) — incompatible avec un déploiement
  serverless sans disque persistant.

## Licence

Apache 2.0 — voir `LICENSE` et `NOTICE`.
```

- [ ] **Step 2: Écrire `README.en.md`** (traduction fidèle du `README.md`, même structure)

```markdown
# 📺 Synopsis

*[Version française](README.md)*

Paste a YouTube video URL: get a structured summary (timestamped chapters, key
points, detailed summary) in French or 5 other languages. Free, instant,
self-hostable, deployable on Vercel.

> AI-generated summary based on captions — double-check anything important
> against the source video before relying on it.

## Try it online

*(to be filled in after the Vercel deployment — Task 12)*

## Installation (self-hosted)

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) + Docker Compose.
- `git`, `curl`.
- Free port **8420** (changeable in `docker-compose.yml`).

### One command

```bash
curl -fsSL https://raw.githubusercontent.com/toussaintgarinat-crypto/synopsis/main/install.sh | bash
```

### Or manually

```bash
git clone https://github.com/toussaintgarinat-crypto/synopsis.git
cd synopsis
docker compose up -d --build
```

Check:

```bash
curl http://localhost:8420/sante
```

Then open **http://localhost:8420**.

**Without Docker** (local dev):

```bash
pip install -r requirements-dev.txt
uvicorn main:app --reload --port 8420
```

## What you get

- Structured summary: executive summary, timestamped chapters, 3 key highlights,
  detailed summary.
- 6 languages: French, English, Spanish, German, Portuguese, Italian.
- Chat about the already-summarized content.
- Multiple videos at once (paste several links, one per line).
- HTML / Markdown / PDF export (print), 100% browser-side.

## Real cost: zero (by default)

The transcript comes from YouTube's native captions — no download, no ffmpeg, no
Whisper. Only the summary itself goes through an LLM.

## Configuring an LLM

Two options:

1. **Personal key (BYOK)**: in the form's "Advanced options", pick a provider
   (OpenRouter, OpenCode Go, OpenAI, or custom), paste your key. It's saved only
   in your browser (`localStorage`), never on the server.
2. **Instance key** (if self-hosting): set `OPENROUTER_API_KEY` (or
   `OPENCODE_GO_API_KEY` / `OPENAI_API_KEY`) in `.env` (see `.env.example`) —
   enables a free default model for every visitor of your instance.

Without either, `/resumer` and `/qa` return an explicit error — never a made-up
summary.

## Limitations (V1)

- YouTube only (no Twitch/Vimeo/TikTok/file upload) — requires captions
  (auto-generated or not) on the video.
- No real playlist support (enumerating one would require a YouTube Data API key)
  — paste multiple links instead.
- No audio transcription (Whisper) — incompatible with a serverless deployment
  without persistent disk.

## License

Apache 2.0 — see `LICENSE` and `NOTICE`.
```

- [ ] **Step 3: Commit**

```bash
git add README.md README.en.md
git commit -m "docs: README bilingue"
```

---

### Task 11: Créer le repo GitHub public et pousser

**Files:** aucun (opération git/GitHub)

**Interfaces:** aucune — tâche d'infrastructure

- [ ] **Step 1: Vérifier qu'aucun secret n'est présent avant de pousser**

```bash
cd /Users/garinat_t/Desktop/synopsis
git log --all --oneline -- .env
grep -rl "sk-or-\|sk-proj-\|sk-ant-" --include="*.py" --include="*.md" --include="*.json" . 2>/dev/null
```

Expected : aucune sortie (aucun `.env` commité, aucune clé en dur dans le code).

- [ ] **Step 2: Créer le repo GitHub public**

```bash
gh repo create toussaintgarinat-crypto/synopsis --public \
  --description "Résumé de vidéo YouTube par IA — gratuit, auto-hébergeable, déployable sur Vercel, FR/EN" \
  --source . --remote origin
```

- [ ] **Step 3: Pousser**

```bash
git branch -M main
git push -u origin main
```

- [ ] **Step 4: Vérifier sur GitHub**

```bash
gh repo view toussaintgarinat-crypto/synopsis --web
```

Confirmer visuellement que tous les fichiers sont présents (pas de `.venv/`, pas de `.env`, pas de `__pycache__/`).

---

### Task 12: Déployer sur Vercel et prouver le bout-en-bout

**Files:** aucun (déploiement + vérification manuelle — c'est le point le moins éprouvé du design, à valider en conditions réelles avant de considérer le travail terminé)

**Interfaces:** aucune

- [ ] **Step 1: Connecter le projet à Vercel**

```bash
cd /Users/garinat_t/Desktop/synopsis
vercel login   # si pas déjà connecté
vercel link    # associe ce dossier à un nouveau projet Vercel, répondre aux prompts (nom : synopsis)
```

- [ ] **Step 2: Configurer la variable d'environnement OpenRouter sur Vercel (optionnel mais recommandé pour une démo publique)**

```bash
vercel env add OPENROUTER_API_KEY production
# coller une clé OpenRouter gratuite quand demandé
```

- [ ] **Step 3: Déployer en production**

```bash
vercel --prod
```

Noter l'URL affichée en sortie (ex. `https://synopsis-xxxx.vercel.app`).

- [ ] **Step 4: Vérifier `/sante` en production**

```bash
curl -s https://<URL-VERCEL>/sante
```

Expected: `{"statut":"ok","service":"synopsis",...}`

- [ ] **Step 5: Preuve bout-en-bout — un vrai résumé contre une vraie vidéo YouTube publique avec sous-titres**

```bash
curl -s -X POST https://<URL-VERCEL>/resumer \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "langue": "Français"}' | head -c 500
```

Expected : un JSON avec `video_id`, `titre`, `rapport` contenant du markdown structuré
(`# 📺 ANALYSE VIDÉO`, `## 📍 Chapitrage Temporel`, etc.). Si `resume_configure` est
`false` (aucune clé configurée à l'étape 2), tester plutôt avec un `llm: {base_url,
cle, modele}` BYOK dans le body pour prouver le chemin BYOK plutôt que le chemin
gratuit.

Si cette étape échoue (timeout, erreur d'import ASGI, etc.), c'est le signal
explicite que le pattern FastAPI-ASGI-on-Vercel ne fonctionne pas tel quel pour ce
projet — documenter l'erreur exacte avant de chercher un correctif (ne pas
supposer que le code est correct simplement parce qu'il l'était en local).

- [ ] **Step 6: Vérifier la page d'accueil dans un navigateur**

Ouvrir `https://<URL-VERCEL>/` : soumettre une vraie URL YouTube dans le
formulaire, confirmer que le résultat s'affiche avec le thème sombre/violet, que
l'export HTML/Markdown fonctionne, que le chat Q&A répond.

- [ ] **Step 7: Mettre à jour les README avec l'URL de démo**

Remplacer `*(à compléter après le déploiement Vercel — Task 12)*` dans
`README.md` et `README.en.md` par l'URL réelle obtenue à l'étape 3.

```bash
git add README.md README.en.md
git commit -m "docs: ajoute l'URL de démo Vercel"
git push
```

---

## Résumé des tâches

| Task | Livrable | Test |
|---|---|---|
| 0 | Scaffolding repo | — |
| 1 | `engine/extractor.py` | 8 tests |
| 2 | `engine/chunker.py` | 5 tests |
| 3 | `engine/analyzer.py` + prompt | 2 tests |
| 4 | `llm.py` | 8 tests |
| 5 | `engine/fusion.py` + prompt | 4 tests |
| 6 | `main.py` (endpoints) | 8 tests |
| 7 | `static/index.html` (front) | vérification manuelle |
| 8 | `api/index.py` + `vercel.json` | import manuel |
| 9 | Docker (self-host) | build + `/sante` manuel |
| 10 | README bilingue | — |
| 11 | Repo GitHub public + push | — |
| 12 | Déploiement Vercel + preuve bout-en-bout | `/resumer` réel en prod |
