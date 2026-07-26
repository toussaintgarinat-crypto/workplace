# S194 — Brique export (PDF + PPTX) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new autonomous brique `briques/export/` that renders PDF (WeasyPrint, thèmes `livre`/`rapport`) and PPTX (python-pptx, thème `sobre`) from structured content, deterministic and free (no AI, no external provider).

**Architecture:** FastAPI service on port 6150, mirroring `briques/video/` (CORS+`API_KEYS` auth, `/sante`, `/fichiers/{nom}` file serving). Two pure rendering modules (`rendu_pdf.py`, `rendu_pptx.py`) called by `main.py`. WeasyPrint's native call is isolated behind one function (`_rendu_html_vers_pdf`) so offline tests can mock it without requiring Pango/Cairo/GDK-Pixbuf system libraries on the dev machine — the real end-to-end PDF proof happens via Docker (where those libs are installed by the Dockerfile), consistent with the project's existing "régime preuve Docker différé" and the S188 precedent (ffmpeg mocked in offline tests, proven for real in a container).

**Tech Stack:** Python 3.12, FastAPI, WeasyPrint 69.0, python-pptx 1.0.2, Markdown 3.10.2.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-22-brique-export-pdf-pptx-design.md`.
- Port **6150** (verified free — no other `briques/*/manifest.json` uses it).
- No `shared/` import needed → **local** Docker build context (`build: .`), per `GUIDE-ajouter-une-brique.md` §3.
- Auth: same pattern as `video`/`images` — `API_KEYS` (CSV) + `CORS_ORIGINS` (CSV), both read from the shared root `.env` via `env_file`, **not** set as explicit lines in the brique's own `docker-compose.yml` (verified against `briques/video/docker-compose.yml` and `briques/images/docker-compose.yml` — neither declares them locally).
- No CSS/theme supplied by the caller in v1 — only the named themes below (YAGNI, matches the approved spec).
- **Commit policy: standard per-task commits** (skill default). Each task ends with its own commit once its tests pass — this matches actual practice on `main` for every recent sprint (S193/veille-prospection, atelier-veille, etc., all show one commit per task, never a sprint-wide squash). An earlier version of this plan wrongly claimed a single end-of-sprint commit based on a stale memory note; corrected before Task 1 was dispatched after checking `git log` on `main`.
- Manifest fields must satisfy `tests/test_briques_smoke.py`: `statut: "a_tester"` (known status), `couche: "backend"` ⇒ `port`+`url_sante` required and `url_sante` must contain the port digits, `capacites[].nom` required, no port collision, no duplicate brique name.
- Per `GUIDE-ajouter-une-brique.md` §2: any capacity that **writes** must have `"action": true` (gates it behind the confirmation prompt) even if deterministic/free — verified against the real precedent `video_carte_titre`/`video_sous_titrer` in `briques/video/manifest.json`, which both write a file and both carry `"action": true, "niveau": 0`. **Note:** the approved design spec says `action:false` for `export_pdf`/`export_pptx` — that line is corrected to `action:true` in this plan (Task 5) to match the real codebase convention; the design doc will be patched to match in Task 5 too.

---

### Task 1: Scaffold the brique — manifest, deps, Docker, health endpoint

**Files:**
- Create: `briques/export/manifest.json`
- Create: `briques/export/requirements.txt`
- Create: `briques/export/Dockerfile`
- Create: `briques/export/docker-compose.yml`
- Create: `briques/export/conftest.py`
- Create: `briques/export/main.py` (health/scaffold only — `/pdf`/`/pptx` added in Task 4)
- Test: `briques/export/test_api.py` (health only — expanded in Task 4)

**Interfaces:**
- Produces: FastAPI `app` in `main.py` with `cle_api()` dependency (signature: `(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)) -> str`), `GET /sante`, `GET /` — these are consumed unchanged by Task 4.

- [ ] **Step 1: Create `briques/export/requirements.txt`**

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
markdown==3.10.2
weasyprint==69.0
python-pptx==1.0.2
```

- [ ] **Step 2: Create `briques/export/manifest.json`** (capacités added in Task 5 — empty for now so Task 1's smoke check is meaningful on its own)

```json
{
  "nom": "export",
  "famille": "media",
  "version": "0.1.0",
  "description": "Rendu PDF et PPTX déterministe (WeasyPrint + python-pptx), sans IA ni coût : convertit du contenu structuré (Markdown thémé pour le PDF, diapositives pour le PPTX) en fichier téléchargeable. Service générique appelé par Studio (export livre), Forge (deck client) et les rapports internes — pas absorbé par un consommateur particulier (S194).",
  "role": "export",
  "couche": "backend",
  "statut": "a_tester",
  "chemin_source": "~/Desktop/Workplace/briques/export",
  "port": 6150,
  "url_sante": "http://host.docker.internal:6150/sante",
  "depends_on": [],
  "offre": ["rendu_pdf", "rendu_pptx", "themes_livre_rapport", "theme_pptx_sobre"],
  "besoin": [],
  "capacites": [],
  "taches": []
}
```

- [ ] **Step 3: Create `briques/export/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# WeasyPrint : rendu PDF déterministe (Markdown→HTML→PDF). Ces libs natives sont
# nécessaires au RUNTIME (l'appel HTML(...).write_pdf()), pas au moment du `pip install` —
# c'est pourquoi les tests offline (Task 3) mockent le point d'appel WeasyPrint plutôt que
# d'exiger ces libs sur la machine qui lance pytest en dehors de Docker.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libcairo2 \
    libffi8 shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6150"]
```

- [ ] **Step 4: Create `briques/export/docker-compose.yml`**

```yaml
services:
  export:
    build: .
    container_name: workplace_export
    image: workplace/export:0.1.0          # tag épinglé (pas de :latest flottant)
    env_file:
      # Réglages partagés à la racine (API_KEYS, CORS_ORIGINS). Facultatif.
      - path: ../../.env
        required: false
    ports:
      - "6150:6150"
    extra_hosts:
      - "host.docker.internal:host-gateway"   # joindre les services hôtes sous Linux
    environment:
      - FICHIERS_DIR=/data/fichiers
    volumes:
      - export_data:/data/fichiers            # PDF/PPTX produits
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6150/sante')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

volumes:
  export_data:
```

- [ ] **Step 5: Create `briques/export/conftest.py`**

```python
"""Config de test : stockage temporaire + mode API ouvert (déterministe)."""
import os
import tempfile

os.environ["FICHIERS_DIR"] = os.path.join(tempfile.gettempdir(), "export_brique_test")
os.environ["API_KEYS"] = ""   # mode ouvert : tests n'ont pas à fournir de clé
```

- [ ] **Step 6: Create `briques/export/main.py`** (scaffold: health + CORS/auth only)

```python
"""Brique « export » — rendu PDF et PPTX déterministe (WeasyPrint + python-pptx).

Service autonome sans IA ni coût : convertit du contenu structuré fourni par un
consommateur (Studio, Forge, scripts de rapports) en fichier PDF ou PPTX téléchargeable.
Aucun fournisseur externe, aucune clé de service tiers.
"""
import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

app = FastAPI(title="Export — rendu PDF/PPTX", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


FICHIERS_DIR = Path(os.getenv("FICHIERS_DIR", "/data/fichiers"))
FICHIERS_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return "<h1>📄 Brique export</h1><p>Rendu PDF/PPTX déterministe. Voir <a href='/docs'>/docs</a>.</p>"


@app.get("/sante", tags=["système"])
def sante():
    return {"ok": True}
```

- [ ] **Step 7: Write the failing test — `briques/export/test_api.py`**

```python
"""Tests — API de la brique export."""
from fastapi.testclient import TestClient

import main

c = TestClient(main.app)


def test_sante():
    r = c.get("/sante")
    assert r.status_code == 200
    assert r.json()["ok"] is True
```

- [ ] **Step 8: Run the tests**

```bash
cd briques/export && python3 -m pip install -r requirements.txt -q && python3 -m pytest -q
```
Expected: 1 passed (`test_sante`). If `pip install` fails on `weasyprint`, stop and report the exact pip error before continuing — Task 3 depends on the package being importable (even though its native call is mocked, the module import path must resolve).

- [ ] **Step 9: Validate the manifest against the smoke test**

```bash
cd /Users/garinat_t/Desktop/Workplace && make smoke
```
Expected: all tests pass, including the new `briques/export` entries in `test_manifest_est_un_json_valide`, `test_manifest_porte_les_champs_requis`, `test_brique_backend_porte_le_contrat_reseau`, `test_statut_est_connu`, `test_url_sante_contient_le_port`, `test_noms_de_briques_uniques`, `test_aucune_collision_de_port`.

- [ ] **Step 10: Commit**

```bash
git add briques/export
git commit -m "feat(export): scaffold — manifest, Dockerfile, docker-compose, endpoint /sante (S194)"
```

---

### Task 2: `rendu_pptx.py` — diapositives structurées → PPTX

**Files:**
- Create: `briques/export/rendu_pptx.py`
- Test: `briques/export/test_rendu_pptx.py`

**Interfaces:**
- Produces: `THEMES: set[str]` (`{"sobre"}`), `generer(titre: str, diapositives: list[dict], theme: str = "sobre") -> bytes`. Each `diapositives` entry: `{"titre": str, "points": list[str], "notes": str | None}`. Raises `ValueError` on empty titre, empty diapositives, or unknown theme. Consumed by `main.py` in Task 4.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests — rendu_pptx.py (python-pptx est pur-Python : ces tests appellent le VRAI rendu,
pas de mock — cf. rendu_pdf.py pour la raison du mock côté WeasyPrint)."""
import io

from pptx import Presentation

import rendu_pptx as PP


def test_generer_titre_vide_leve():
    try:
        PP.generer("", [{"titre": "A", "points": ["x"]}])
    except ValueError as e:
        assert "titre" in str(e).lower()
    else:
        raise AssertionError("titre vide aurait dû lever ValueError")


def test_generer_sans_diapositives_leve():
    try:
        PP.generer("Deck", [])
    except ValueError as e:
        assert "diapositive" in str(e).lower()
    else:
        raise AssertionError("diapositives vides auraient dû lever ValueError")


def test_generer_theme_inconnu_leve():
    try:
        PP.generer("Deck", [{"titre": "A", "points": ["x"]}], theme="neon")
    except ValueError as e:
        assert "thème" in str(e).lower() or "theme" in str(e).lower()
    else:
        raise AssertionError("thème inconnu aurait dû lever ValueError")


def test_generer_produit_un_pptx_valide_relisible():
    data = PP.generer("Mon Deck", [
        {"titre": "Diapo 1", "points": ["Point A", "Point B"], "notes": "note interne"},
        {"titre": "Diapo 2", "points": ["Point C"]},
    ])
    assert data[:2] == b"PK"   # signature ZIP/OOXML : c'est un vrai fichier, pas un mock
    prez = Presentation(io.BytesIO(data))
    diapos = list(prez.slides)
    assert len(diapos) == 3   # 1 diapo de titre + 2 diapos de contenu
    assert diapos[0].shapes.title.text == "Mon Deck"
    assert diapos[1].shapes.title.text == "Diapo 1"
    corps = diapos[1].placeholders[1].text_frame
    textes = [p.text for p in corps.paragraphs]
    assert textes == ["Point A", "Point B"]
    assert diapos[1].notes_slide.notes_text_frame.text == "note interne"
    assert diapos[2].shapes.title.text == "Diapo 2"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd briques/export && python3 -m pytest test_rendu_pptx.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'rendu_pptx'`.

- [ ] **Step 3: Implement `briques/export/rendu_pptx.py`**

```python
"""Rendu PPTX DÉTERMINISTE (python-pptx) — diapositives structurées → fichier PPTX.

python-pptx est pur-Python (pas de libs système type Pango/Cairo requises comme pour
WeasyPrint, cf. rendu_pdf.py) : ce module peut être appelé pour de vrai dans les tests
offline, sans mock.

Thème v1 unique : 'sobre' (texte seul, layout titre+contenu standard). Pas de génération
d'images/graphiques (hors périmètre v1, cf. design S194).
"""
from __future__ import annotations

import io

from pptx import Presentation

THEMES = {"sobre"}


def generer(titre: str, diapositives: list[dict], theme: str = "sobre") -> bytes:
    if not (titre or "").strip():
        raise ValueError("Le titre est vide.")
    if not diapositives:
        raise ValueError("Aucune diapositive fournie.")
    if theme not in THEMES:
        raise ValueError(f"Thème inconnu : {theme!r} (attendu : {sorted(THEMES)}).")

    prez = Presentation()
    diapo_titre = prez.slides.add_slide(prez.slide_layouts[0])
    diapo_titre.shapes.title.text = titre

    layout_contenu = prez.slide_layouts[1]   # layout standard "Title and Content"
    for d in diapositives:
        diapo = prez.slides.add_slide(layout_contenu)
        diapo.shapes.title.text = (d.get("titre") or "").strip() or "—"
        points = d.get("points") or []
        corps = diapo.placeholders[1].text_frame
        if points:
            corps.text = points[0]
            for point in points[1:]:
                corps.add_paragraph().text = point
        notes = (d.get("notes") or "").strip()
        if notes:
            diapo.notes_slide.notes_text_frame.text = notes

    buffer = io.BytesIO()
    prez.save(buffer)
    return buffer.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd briques/export && python3 -m pytest test_rendu_pptx.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add briques/export/rendu_pptx.py briques/export/test_rendu_pptx.py
git commit -m "feat(export): rendu_pptx.py — diapositives structurées vers PPTX (S194)"
```

---

### Task 3: `rendu_pdf.py` — Markdown thémé → PDF (WeasyPrint call mocked in offline tests)

**Files:**
- Create: `briques/export/rendu_pdf.py`
- Test: `briques/export/test_rendu_pdf.py`

**Interfaces:**
- Produces: `THEMES: set[str]` (`{"livre", "rapport"}`), `construire_html(titre: str, markdown_src: str) -> str` (pure), `_rendu_html_vers_pdf(html: str, css_str: str) -> bytes` (the WeasyPrint boundary — monkeypatched in tests and, later, testable for real only inside Docker), `generer(titre: str, markdown_src: str, theme: str = "livre") -> bytes`. Raises `ValueError` on empty titre, empty markdown, or unknown theme. Consumed by `main.py` in Task 4.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests — rendu_pdf.py.

WeasyPrint dlopen des libs natives (Pango/Cairo/GDK-Pixbuf) au moment où on l'appelle
pour de vrai — indisponibles sur une machine de dev sans ces paquets système (constaté :
ce Mac ne les a pas). `_rendu_html_vers_pdf` isole cet appel ; ces tests le mockent, comme
`test_habillage.py` mocke `subprocess.run` pour ffmpeg. La preuve d'un VRAI PDF valide se
fait dans Docker (le Dockerfile installe ces libs), cf. plan Task 5.
"""
import rendu_pdf as P


def test_construire_html_convertit_markdown():
    html = P.construire_html("Mon titre", "# Bonjour\n\nUn **texte**.")
    assert "<h1>Bonjour</h1>" in html
    assert "<strong>texte</strong>" in html
    assert "Mon titre" in html


def test_generer_titre_vide_leve():
    try:
        P.generer("", "contenu")
    except ValueError as e:
        assert "titre" in str(e).lower()
    else:
        raise AssertionError("titre vide aurait dû lever ValueError")


def test_generer_markdown_vide_leve():
    try:
        P.generer("Titre", "   ")
    except ValueError as e:
        assert "markdown" in str(e).lower()
    else:
        raise AssertionError("markdown vide aurait dû lever ValueError")


def test_generer_theme_inconnu_leve():
    try:
        P.generer("Titre", "# x", theme="neon")
    except ValueError as e:
        assert "thème" in str(e).lower() or "theme" in str(e).lower()
    else:
        raise AssertionError("thème inconnu aurait dû lever ValueError")


def test_generer_appelle_le_rendu_avec_le_theme_choisi(monkeypatch):
    appels = {}

    def faux_rendu(html, css):
        appels["html"] = html
        appels["css"] = css
        return b"PDFBYTES"

    monkeypatch.setattr(P, "_rendu_html_vers_pdf", faux_rendu)
    resultat = P.generer("Mon Tome", "# Chapitre 1", theme="rapport")
    assert resultat == b"PDFBYTES"
    assert "Mon Tome" in appels["html"] and "Chapitre 1" in appels["html"]
    assert appels["css"] == P._CSS_PAR_THEME["rapport"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd briques/export && python3 -m pytest test_rendu_pdf.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'rendu_pdf'`.

- [ ] **Step 3: Implement `briques/export/rendu_pdf.py`**

```python
"""Rendu PDF DÉTERMINISTE (WeasyPrint) — Markdown → HTML thémé → PDF.

Le thème est un CSS EMBARQUÉ choisi par nom ('livre' ou 'rapport'), jamais un CSS fourni
par l'appelant (pas de surface d'injection libre, cf. design S194).

WeasyPrint est importé PARESSEUSEMENT à l'intérieur de `_rendu_html_vers_pdf` (pas au
niveau module) : ses libs natives (Pango/Cairo/GDK-Pixbuf) ne sont dlopen qu'à cet
instant, jamais au simple `import rendu_pdf`. Ça permet aux tests offline de mocker
`_rendu_html_vers_pdf` sans que ces libs système soient installées sur la machine qui
lance pytest (même logique que `habillage.py` avec `shutil.which("ffmpeg")`).
"""
from __future__ import annotations

import markdown as _markdown

THEMES = {"livre", "rapport"}

_CSS_LIVRE = """
@page { size: A5; margin: 2.5cm 2cm; }
body { font-family: Georgia, 'Times New Roman', serif; font-size: 11pt; line-height: 1.5; }
h1 { page-break-before: always; font-size: 20pt; }
"""

_CSS_RAPPORT = """
@page { size: A4; margin: 2cm; @bottom-center { content: counter(page); } }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10pt; line-height: 1.4; }
h1 { font-size: 18pt; border-bottom: 1px solid #333; }
"""

_CSS_PAR_THEME = {"livre": _CSS_LIVRE, "rapport": _CSS_RAPPORT}


def construire_html(titre: str, markdown_src: str) -> str:
    """Markdown → document HTML complet (pure, testable sans WeasyPrint)."""
    corps = _markdown.markdown(markdown_src or "", extensions=["extra"])
    return f"<html><head><meta charset='utf-8'><title>{titre}</title></head><body>{corps}</body></html>"


def _rendu_html_vers_pdf(html: str, css_str: str) -> bytes:
    from weasyprint import CSS, HTML   # import paresseux : natif, mocké en test offline
    return HTML(string=html).write_pdf(stylesheets=[CSS(string=css_str)])


def generer(titre: str, markdown_src: str, theme: str = "livre") -> bytes:
    if not (titre or "").strip():
        raise ValueError("Le titre est vide.")
    if not (markdown_src or "").strip():
        raise ValueError("Le contenu Markdown est vide.")
    if theme not in THEMES:
        raise ValueError(f"Thème inconnu : {theme!r} (attendu : {sorted(THEMES)}).")
    html = construire_html(titre, markdown_src)
    return _rendu_html_vers_pdf(html, _CSS_PAR_THEME[theme])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd briques/export && python3 -m pytest test_rendu_pdf.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add briques/export/rendu_pdf.py briques/export/test_rendu_pdf.py
git commit -m "feat(export): rendu_pdf.py — Markdown thémé vers PDF, WeasyPrint mocké en test offline (S194)"
```

---

### Task 4: Wire `main.py` — `POST /pdf`, `POST /pptx`, `GET /fichiers/{nom}`

**Files:**
- Modify: `briques/export/main.py`
- Modify: `briques/export/test_api.py`

**Interfaces:**
- Consumes: `rendu_pdf.generer(titre, markdown, theme) -> bytes` / `rendu_pdf.THEMES` (Task 3); `rendu_pptx.generer(titre, diapositives, theme) -> bytes` / `rendu_pptx.THEMES` (Task 2); `FICHIERS_DIR: Path` and `cle_api` (Task 1).
- Produces: `_enregistrer(nom: str, data: bytes) -> str` (writes to `FICHIERS_DIR`, returns `/fichiers/<nom>`) — internal, no other task depends on it.

- [ ] **Step 1: Write the failing tests — append to `briques/export/test_api.py`**

```python
def test_sante_annonce_les_themes():
    r = c.get("/sante")
    d = r.json()
    assert sorted(d["themes_pdf"]) == ["livre", "rapport"]
    assert d["themes_pptx"] == ["sobre"]


def test_pdf_refuse_un_titre_vide():
    assert c.post("/pdf", json={"titre": "", "markdown": "contenu"}).status_code == 422


def test_pdf_refuse_un_theme_inconnu():
    r = c.post("/pdf", json={"titre": "T", "markdown": "c", "theme": "neon"})
    assert r.status_code == 422


def test_pdf_produit_un_fichier_servable(monkeypatch):
    monkeypatch.setattr(main.rendu_pdf, "_rendu_html_vers_pdf", lambda html, css: b"%PDF-FAKE")
    r = c.post("/pdf", json={"titre": "Mon Tome", "markdown": "# Chap 1\n\nTexte."})
    assert r.status_code == 200
    url = r.json()["url"]
    fichier = c.get(url)
    assert fichier.status_code == 200
    assert fichier.headers["content-type"] == "application/pdf"
    assert fichier.content == b"%PDF-FAKE"


def test_pptx_refuse_des_diapositives_vides():
    r = c.post("/pptx", json={"titre": "Deck", "diapositives": []})
    assert r.status_code == 422


def test_pptx_produit_un_fichier_servable():
    r = c.post("/pptx", json={"titre": "Deck",
                              "diapositives": [{"titre": "Un", "points": ["a"]}]})
    assert r.status_code == 200
    url = r.json()["url"]
    fichier = c.get(url)
    assert fichier.status_code == 200
    assert fichier.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.presentationml")


def test_fichier_inconnu_404():
    assert c.get("/fichiers/inexistant.pdf").status_code == 404


def test_fichier_anti_traversee():
    # pas d'évasion hors du dossier de fichiers produits (même garde que briques/video)
    assert c.get("/fichiers/..%2f..%2fetc%2fpasswd").status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd briques/export && python3 -m pytest test_api.py -v
```
Expected: FAIL — `404` on `POST /pdf`/`POST /pptx` (routes don't exist yet), `AttributeError` on `d["themes_pdf"]` (key absent).

- [ ] **Step 3: Modify `briques/export/main.py`** — add imports, models, and the three endpoints. Full resulting file:

```python
"""Brique « export » — rendu PDF et PPTX déterministe (WeasyPrint + python-pptx).

Service autonome sans IA ni coût : convertit du contenu structuré fourni par un
consommateur (Studio, Forge, scripts de rapports) en fichier PDF ou PPTX téléchargeable.
Aucun fournisseur externe, aucune clé de service tiers.
"""
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

import rendu_pdf
import rendu_pptx

app = FastAPI(title="Export — rendu PDF/PPTX", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def cle_api(x_api_key: Optional[str] = Header(None),
            authorization: Optional[str] = Header(None)) -> str:
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if not API_KEYS:
        return presentee or "public"
    if presentee in API_KEYS:
        return presentee
    raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")


FICHIERS_DIR = Path(os.getenv("FICHIERS_DIR", "/data/fichiers"))
FICHIERS_DIR.mkdir(parents=True, exist_ok=True)


def _enregistrer(nom: str, data: bytes) -> str:
    (FICHIERS_DIR / nom).write_bytes(data)
    return f"/fichiers/{nom}"


class RendrePdf(BaseModel):
    titre:    str
    markdown: str
    theme:    str = "livre"


class Diapositive(BaseModel):
    titre:  str = ""
    points: list[str] = []
    notes:  Optional[str] = None


class RendrePptx(BaseModel):
    titre:         str
    diapositives:  list[Diapositive]
    theme:         str = "sobre"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def accueil():
    return "<h1>📄 Brique export</h1><p>Rendu PDF/PPTX déterministe. Voir <a href='/docs'>/docs</a>.</p>"


@app.get("/sante", tags=["système"])
def sante():
    return {"ok": True, "themes_pdf": sorted(rendu_pdf.THEMES),
            "themes_pptx": sorted(rendu_pptx.THEMES)}


@app.post("/pdf", tags=["export"])
def pdf(body: RendrePdf, _cle: str = Depends(cle_api)):
    try:
        data = rendu_pdf.generer(body.titre, body.markdown, body.theme)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:
        raise HTTPException(400, f"Échec du rendu PDF : {e}") from e
    nom = f"export-{uuid.uuid4().hex[:12]}.pdf"
    return {"url": _enregistrer(nom, data), "fichier": nom}


@app.post("/pptx", tags=["export"])
def pptx(body: RendrePptx, _cle: str = Depends(cle_api)):
    try:
        diapos = [d.model_dump() for d in body.diapositives]
        data = rendu_pptx.generer(body.titre, diapos, body.theme)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:
        raise HTTPException(400, f"Échec du rendu PPTX : {e}") from e
    nom = f"export-{uuid.uuid4().hex[:12]}.pptx"
    return {"url": _enregistrer(nom, data), "fichier": nom}


@app.get("/fichiers/{nom}", tags=["système"], include_in_schema=False)
def fichier(nom: str):
    chemin = (FICHIERS_DIR / nom).resolve()
    if not str(chemin).startswith(str(FICHIERS_DIR.resolve())) or not chemin.is_file():
        raise HTTPException(404, "Fichier introuvable.")
    media = {"pdf": "application/pdf",
             "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"
             }.get(nom.rsplit(".", 1)[-1], "application/octet-stream")
    return FileResponse(chemin, media_type=media)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd briques/export && python3 -m pytest -v
```
Expected: all tests in `test_api.py`, `test_rendu_pdf.py`, `test_rendu_pptx.py` pass (16 total).

- [ ] **Step 5: Commit**

```bash
git add briques/export/main.py briques/export/test_api.py
git commit -m "feat(export): endpoints POST /pdf, POST /pptx, GET /fichiers/{nom} (S194)"
```

---

### Task 5: Register the brique with the Cœur — capacités, launcher, docs, final verification

**Files:**
- Modify: `briques/export/manifest.json` (add `capacites`)
- Modify: `Lancer Workplace.command`
- Modify: `.env.example`
- Modify: `docs/superpowers/specs/2026-07-22-brique-export-pdf-pptx-design.md` (correct `action:false` → `action:true`, per Global Constraints)

- [ ] **Step 1: Add `capacites` to `briques/export/manifest.json`** — replace `"capacites": [],` with:

```json
  "capacites": [
    {
      "nom": "export_pdf",
      "description": "Rend un document PDF à partir d'un titre et d'un contenu Markdown, avec un thème de mise en page ('livre' : typographie roman, grandes marges ; 'rapport' : en-tête/pied de page, numérotation). DÉTERMINISTE (WeasyPrint local, aucune IA, aucun coût), mais ÉCRIT un fichier : confirme=true requis.",
      "methode": "POST",
      "chemin": "/pdf",
      "params": {
        "titre": {
          "type": "string",
          "description": "Titre du document (obligatoire).",
          "requis": true
        },
        "markdown": {
          "type": "string",
          "description": "Contenu au format Markdown (obligatoire).",
          "requis": true
        },
        "theme": {
          "type": "string",
          "description": "Thème de mise en page : 'livre' ou 'rapport' (défaut 'livre')."
        }
      },
      "action": true,
      "niveau": 0
    },
    {
      "nom": "export_pptx",
      "description": "Rend une présentation PPTX à partir d'un titre et d'une liste de diapositives (titre + points à puces + notes optionnelles). DÉTERMINISTE (python-pptx local, aucune IA, aucun coût), mais ÉCRIT un fichier : confirme=true requis.",
      "methode": "POST",
      "chemin": "/pptx",
      "params": {
        "titre": {
          "type": "string",
          "description": "Titre de la présentation (obligatoire).",
          "requis": true
        },
        "diapositives": {
          "type": "array",
          "description": "Liste [{titre, points: [str], notes?}], une entrée par diapositive (obligatoire).",
          "requis": true
        },
        "theme": {
          "type": "string",
          "description": "Thème visuel (défaut et seul choix v1 : 'sobre')."
        }
      },
      "action": true,
      "niveau": 0
    }
  ],
```

- [ ] **Step 2: Re-run the smoke test to validate the capacités are well-formed**

```bash
cd /Users/garinat_t/Desktop/Workplace && make smoke
```
Expected: all pass, including `test_capacites_et_taches_bien_formees` for `export`.

- [ ] **Step 3: Add the launcher entry in `Lancer Workplace.command`**

Find the line `"atelier-veille|$RACINE/briques/atelier-veille|http://localhost:6130/sante"` and add immediately after it:

```
  "export|$RACINE/briques/export|http://localhost:6150/sante"
```

- [ ] **Step 4: Document the shared `API_KEYS` scope in `.env.example`**

Find the comment block:
```
# Clés d'API acceptées par les briques autonomes (calcul, images, personnages,
# studio, transcription, video, vision, connexion) — CSV, en-tête X-API-Key.
```
Replace with:
```
# Clés d'API acceptées par les briques autonomes (calcul, images, personnages,
# studio, transcription, video, vision, connexion, export) — CSV, en-tête X-API-Key.
```

- [ ] **Step 5: Correct the design spec's action-gate line**

In `docs/superpowers/specs/2026-07-22-brique-export-pdf-pptx-design.md`, find:
```
- **`manifest.json`** — capacités LLM `export_pdf` et `export_pptx`, niveau 0,
  `action:false` (déterministe, aucun coût — même statut que `video_carte_titre` /
  `video_sous_titrer` en S188, pas de `confirme` requis).
```
Replace with:
```
- **`manifest.json`** — capacités LLM `export_pdf` et `export_pptx`, niveau 0,
  `action:true` (ÉCRIVENT un fichier → gardées par la porte de confirmation, comme toute
  capacité qui écrit — cf. `GUIDE-ajouter-une-brique.md` §2 ; correction par rapport à la
  version initiale de ce document, qui disait `action:false` à tort : le précédent réel,
  `video_carte_titre`/`video_sous_titrer` en S188, a bien `action:true` malgré l'absence
  de coût/IA).
```

- [ ] **Step 6: Run the full offline test suite one more time**

```bash
cd /Users/garinat_t/Desktop/Workplace && make smoke && cd briques/export && python3 -m pytest -v
```
Expected: everything green (smoke + 16 tests in the brique).

- [ ] **Step 7: Manual Docker verification (requires Docker running — do when available, e.g. locally with Docker Desktop open or on the HP; this is the deferred "real proof" step per the project's régime, not a pytest step)**

```bash
cd briques/export
docker compose up -d --build
curl http://localhost:6150/sante
curl -X POST http://localhost:6150/pdf -H "Content-Type: application/json" \
  -d '{"titre":"Test","markdown":"# Chapitre 1\n\nUn paragraphe.","theme":"livre"}'
# → {"url": "/fichiers/export-xxxx.pdf", ...} ; then:
curl -s http://localhost:6150/fichiers/export-xxxx.pdf | file -   # attend: "PDF document"
curl -X POST http://localhost:6150/pptx -H "Content-Type: application/json" \
  -d '{"titre":"Deck","diapositives":[{"titre":"Un","points":["a","b"]}]}'
# → {"url": "/fichiers/export-yyyy.pptx", ...} ; then:
curl -s http://localhost:6150/fichiers/export-yyyy.pptx | file -   # attend: "Microsoft PowerPoint 2007+"
```
Expected: both `curl ... | file -` calls report a real, valid PDF and a real, valid PowerPoint file — this is the proof that the Dockerfile's `apt-get install` list (Pango/Cairo/GDK-Pixbuf) is actually sufficient for WeasyPrint at runtime, which nothing in the offline pytest suite verifies (Task 3's tests mock that exact call). **If this step fails on the `libgdk-pixbuf-2.0-0` package name** (older/different base image than Debian bookworm), retry the `apt-get install` line in the Dockerfile with `libgdk-pixbuf2.0-0` instead (pre-bookworm Debian package name) and rebuild.

- [ ] **Step 8: Commit**

```bash
git add briques/export/manifest.json Lancer\ Workplace.command .env.example \
  docs/superpowers/specs/2026-07-22-brique-export-pdf-pptx-design.md
git commit -m "$(cat <<'EOF'
feat(export): câble la brique au Cœur — capacités, launcher, docs (S194)

export_pdf/export_pptx exposées au LLM (action:true, niveau 0 — écrivent un
fichier, cf. GUIDE-ajouter-une-brique.md), entrée launcher, API_KEYS partagé
documenté. Issu d'une veille du dépôt nexu-io/open-design.
EOF
)"
git status
```

---

## Self-Review Notes

- **Spec coverage:** architecture (brique autonome, port 6150) → Task 1 ; thèmes PDF `livre`/`rapport` + PPTX `sobre` → Tasks 2–3 ; contrat d'entrée/sortie `/pdf`, `/pptx`, `/fichiers/{nom}` → Task 4 ; gestion d'erreurs 422/400 → Task 4 ; tests offline sur fichiers réels valides → Tasks 2–4 (PPTX real, PDF mocked-boundary + Docker-deferred real proof, both justified) ; sécurité `API_KEYS`/`CORS_ORIGINS` (added to spec after self-review) → Task 1 ; hors périmètre v1 → left undone, as designed.
- **Placeholder scan:** no TBD/TODO; every step has literal code or an exact command with expected output.
- **Type consistency:** `rendu_pdf.generer(titre, markdown_src, theme)` (Task 3) matches the call in `main.py` (Task 4) ; `rendu_pptx.generer(titre, diapositives, theme)` (Task 2) matches the call in `main.py` (Task 4, using `.model_dump()` to convert `Diapositive` Pydantic models to the `dict` shape `rendu_pptx.generer` expects) ; `_rendu_html_vers_pdf(html, css_str)` name matches between Task 3's implementation and Task 3/4's test monkeypatches.
- **Commit policy:** adapted from the skill's default "commit every task" to a single end-of-sprint commit, per the user's saved feedback (`feedback-commit-fin-de-sprint`) — flagged explicitly in Global Constraints so an executor doesn't default back to per-task commits.
