# Brique veille-info Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Créer la brique autonome `veille-info` (port 6120) : sources RSS par personne, fetch+dédup quotidien automatique, résumé consolidé par LLM (via la Gateway) — sans audio.

**Architecture:** Service FastAPI + SQLite indépendant (aucune dépendance de code vers Forge ou une autre brique), isolé par personne (`X-User-Id`, motif `mail` S185), déclenché par l'horloge du Cœur (motif `geo`'s `ingestion-quotidienne`) via une tâche déclarée dans `manifest.json`.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, httpx, sqlite3 (stdlib), pytest.

## Global Constraints

- Aucune modification de `briques/forge/` — le code RSS existant dans Forge reste inchangé, les deux implémentations coexistent (décision actée, cf. design doc).
- Isolation par personne dès la création : motif `tenant_actuel` de `briques/mail/main.py:44-67` (clé `VEILLE_INFO_KEY` empruntée par le Cœur + `X-User-Id`, fail-closed si `API_KEYS` défini).
- Pipeline quotidien : idempotent par `(user_id, date du jour)` — un digest déjà créé aujourd'hui pour une personne ⇒ on ne refait rien pour elle (ni fetch, ni résumé).
- Aucun échec ne doit faire planter le pipeline : une source RSS injoignable est journalisée et ignorée (les autres sources de la même personne continuent) ; un échec de l'appel LLM (Gateway indisponible) ⇒ pas de digest créé pour cette personne ce jour, jamais de digest partiel.
- Pas de génération audio dans ce spec — hors périmètre explicite.
- Port `6120`, famille de manifest `"veille"`, nom de dossier `briques/veille-info/`.
- Tests sans réseau réel (RSS fetch et appel LLM mockés).

---

### Task 1: Stockage SQLite (sources, articles, digests)

**Files:**
- Create: `briques/veille-info/stockage.py`
- Test: `briques/veille-info/conftest.py`
- Test: `briques/veille-info/test_stockage.py`

**Interfaces:**
- Consumes: rien (module racine, aucune dépendance interne)
- Produces (consommé par les Tasks 2, 4, 5) :
  - `stockage.creer_source(user_id: str, nom: str, url: str) -> dict` → `{"id", "nom", "url", "enabled", "created_at"}`
  - `stockage.lister_sources(user_id: str, *, actives_seulement: bool = False) -> list[dict]`
  - `stockage.supprimer_source(user_id: str, source_id: int) -> bool`
  - `stockage.lister_user_ids_actifs() -> list[str]`
  - `stockage.inserer_article(user_id: str, source_id: int, titre: str, url: str, published_at: str) -> bool` (`False` si doublon)
  - `stockage.articles_du_jour(user_id: str, date: str | None = None) -> list[dict]` → `[{"id", "titre", "url", "published_at"}]`
  - `stockage.digest_existe(user_id: str, date: str | None = None) -> bool`
  - `stockage.inserer_digest(user_id: str, texte_resume: str, nb_articles: int, date: str | None = None) -> dict`
  - `stockage.lister_digests(user_id: str) -> list[dict]`
  - `stockage.digest_get(user_id: str, digest_id: int) -> dict | None`

- [ ] **Step 1: Write the failing test**

Créer `briques/veille-info/conftest.py` :

```python
"""Config de test : DB temporaire AVANT tout import des modules applicatifs."""
import os
import tempfile

_db = os.path.join(tempfile.gettempdir(), "veille_info_test.db")
os.environ["VEILLE_INFO_DB"] = _db
os.environ.pop("API_KEYS", None)         # clés libres en test (isolation par empreinte)
os.environ.pop("GATEWAY_KEY", None)      # pas d'appel LLM réel : repli honnête testé
os.environ.pop("GATEWAY_URL", None)
os.environ.pop("VEILLE_INFO_KEY", None)  # /digest/executer ouvert en test

if os.path.exists(_db):
    os.remove(_db)
```

Créer `briques/veille-info/test_stockage.py` :

```python
"""Tests de la persistance (S189-2 brique veille-info). Isolation par user_id, dédup
articles par URL, idempotence des digests par (user_id, date)."""
import stockage


def test_creer_et_lister_sources():
    s = stockage.creer_source("alice", "Le Monde Tech", "https://example.com/rss")
    assert s["nom"] == "Le Monde Tech"
    assert s["enabled"] is True
    sources = stockage.lister_sources("alice")
    assert len(sources) == 1
    assert sources[0]["id"] == s["id"]


def test_lister_sources_isole_par_user_id():
    stockage.creer_source("bob", "Source de Bob", "https://example.com/bob-rss")
    assert all(s["nom"] != "Source de Bob" for s in stockage.lister_sources("alice"))


def test_supprimer_source_isole_par_user_id():
    s = stockage.creer_source("carol", "À supprimer", "https://example.com/x")
    assert stockage.supprimer_source("mallory", s["id"]) is False
    assert stockage.supprimer_source("carol", s["id"]) is True
    assert stockage.lister_sources("carol") == []


def test_lister_user_ids_actifs_ignore_sources_desactivees():
    stockage.creer_source("dave", "Active", "https://example.com/dave-active")
    seule = stockage.creer_source("dave-seul-desactive", "Va être désactivée",
                                  "https://example.com/dave-off")
    # Pas de toggle public dans cette version (YAGNI, cf. design doc) : on simule l'état
    # via une écriture directe, pour prouver que le filtre `WHERE enabled = 1` marche
    # vraiment — c'est la requête dont dépend tout le pipeline quotidien (digest.py).
    with stockage._conn() as c:
        c.execute("UPDATE sources SET enabled = 0 WHERE id = ?", (seule["id"],))
    ids = stockage.lister_user_ids_actifs()
    assert "dave" in ids
    assert "dave-seul-desactive" not in ids


def test_inserer_article_dedup_par_url():
    s = stockage.creer_source("erin", "Flux", "https://example.com/erin-rss")
    premiere = stockage.inserer_article("erin", s["id"], "Titre A", "https://a.example/1", "")
    doublon = stockage.inserer_article("erin", s["id"], "Titre A bis", "https://a.example/1", "")
    assert premiere is True
    assert doublon is False


def test_articles_du_jour_isole_par_user_id():
    s = stockage.creer_source("frank", "Flux", "https://example.com/frank-rss")
    stockage.inserer_article("frank", s["id"], "Titre", "https://frank.example/1", "")
    assert len(stockage.articles_du_jour("frank")) == 1
    assert stockage.articles_du_jour("grace") == []


def test_digest_idempotent_par_user_et_date():
    assert stockage.digest_existe("heidi") is False
    stockage.inserer_digest("heidi", "Résumé du jour.", 3)
    assert stockage.digest_existe("heidi") is True


def test_lister_et_lire_digest_isole_par_user_id():
    d = stockage.inserer_digest("ivan", "Résumé.", 2)
    assert len(stockage.lister_digests("ivan")) == 1
    assert stockage.digest_get("ivan", d["id"])["texte_resume"] == "Résumé."
    assert stockage.digest_get("judy", d["id"]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/veille-info && python3 -m pytest test_stockage.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'stockage'`

- [ ] **Step 3: Write minimal implementation**

Créer `briques/veille-info/stockage.py` :

```python
"""Persistance de la brique veille-info (SQLite). Cloisonné par `user_id` : une personne ne
voit jamais les sources, articles ni digests d'une autre — même motif que `briques/mail`.

Trois tables : `sources` (flux RSS suivis), `articles` (dédup par `(user_id, url)`) et
`digests` (un résumé consolidé par jour et par personne — `UNIQUE(user_id, date)` porte
l'idempotence de la tâche horloge, cf. `digest.py`)."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

_DB = os.getenv("VEILLE_INFO_DB", "/data/veille_info.db")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _aujourdhui() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    nom TEXT NOT NULL,
    url TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sources_user ON sources(user_id);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    titre TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, url)
);
CREATE INDEX IF NOT EXISTS idx_articles_user ON articles(user_id);

CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    texte_resume TEXT NOT NULL,
    nb_articles INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, date)
);
CREATE INDEX IF NOT EXISTS idx_digests_user ON digests(user_id);
"""


def init() -> None:
    os.makedirs(os.path.dirname(_DB) or ".", exist_ok=True)
    with _conn() as c:
        c.executescript(_SCHEMA)


init()  # schéma prêt dès l'import (robuste même sous TestClient)


# ── Sources ───────────────────────────────────────────────────
def _source_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "nom": r["nom"], "url": r["url"], "enabled": bool(r["enabled"]),
            "created_at": r["created_at"]}


def creer_source(user_id: str, nom: str, url: str) -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO sources (user_id, nom, url, enabled, created_at) VALUES (?,?,?,1,?)",
            (user_id, nom, url, _maintenant()))
        row = c.execute("SELECT * FROM sources WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _source_dict(row)


def lister_sources(user_id: str, *, actives_seulement: bool = False) -> list[dict]:
    q = "SELECT * FROM sources WHERE user_id = ?"
    if actives_seulement:
        q += " AND enabled = 1"
    q += " ORDER BY created_at DESC"
    with _conn() as c:
        rows = c.execute(q, (user_id,)).fetchall()
    return [_source_dict(r) for r in rows]


def supprimer_source(user_id: str, source_id: int) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM sources WHERE id = ? AND user_id = ?", (source_id, user_id))
    return cur.rowcount > 0


def lister_user_ids_actifs() -> list[str]:
    with _conn() as c:
        rows = c.execute("SELECT DISTINCT user_id FROM sources WHERE enabled = 1").fetchall()
    return [r["user_id"] for r in rows]


# ── Articles ──────────────────────────────────────────────────
def inserer_article(user_id: str, source_id: int, titre: str, url: str,
                    published_at: str) -> bool:
    """Insère un article. Renvoie False si déjà présent pour cet utilisateur (dédup par URL)."""
    with _conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO articles (user_id, source_id, titre, url, published_at, "
            "created_at) VALUES (?,?,?,?,?,?)",
            (user_id, source_id, titre, url, published_at, _maintenant()))
    return cur.rowcount > 0


def articles_du_jour(user_id: str, date: str | None = None) -> list[dict]:
    date = date or _aujourdhui()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM articles WHERE user_id = ? AND created_at LIKE ? ORDER BY created_at ASC",
            (user_id, f"{date}%")).fetchall()
    return [{"id": r["id"], "titre": r["titre"], "url": r["url"],
            "published_at": r["published_at"]} for r in rows]


# ── Digests ───────────────────────────────────────────────────
def _digest_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "date": r["date"], "texte_resume": r["texte_resume"],
            "nb_articles": r["nb_articles"], "created_at": r["created_at"]}


def digest_existe(user_id: str, date: str | None = None) -> bool:
    date = date or _aujourdhui()
    with _conn() as c:
        row = c.execute("SELECT 1 FROM digests WHERE user_id = ? AND date = ?",
                        (user_id, date)).fetchone()
    return row is not None


def inserer_digest(user_id: str, texte_resume: str, nb_articles: int,
                   date: str | None = None) -> dict:
    date = date or _aujourdhui()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO digests (user_id, date, texte_resume, nb_articles, created_at) "
            "VALUES (?,?,?,?,?)",
            (user_id, date, texte_resume, nb_articles, _maintenant()))
        row = c.execute("SELECT * FROM digests WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _digest_dict(row)


def lister_digests(user_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM digests WHERE user_id = ? ORDER BY date DESC",
                         (user_id,)).fetchall()
    return [_digest_dict(r) for r in rows]


def digest_get(user_id: str, digest_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM digests WHERE id = ? AND user_id = ?",
                        (digest_id, user_id)).fetchone()
    return _digest_dict(row) if row else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/veille-info && python3 -m pytest test_stockage.py -v`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/stockage.py briques/veille-info/conftest.py briques/veille-info/test_stockage.py
git commit -m "feat(veille-info): stockage SQLite sources/articles/digests"
```

---

### Task 2: Fetch + parsing RSS

**Files:**
- Create: `briques/veille-info/rss.py`
- Test: `briques/veille-info/test_rss.py`

**Interfaces:**
- Consumes: rien (module autonome)
- Produces (consommé par Task 4) :
  - `rss.parser_items(texte: str) -> list[dict]` → `[{"titre": str, "url": str, "published_at": str}]`
  - `rss.fetcher(url: str) -> str` (lève une exception `httpx.HTTPError`/`httpx.RequestError` en cas d'échec — à l'appelant de journaliser et continuer)

- [ ] **Step 1: Write the failing test**

Créer `briques/veille-info/test_rss.py` :

```python
"""Tests du parseur RSS (regex, indépendant du parseur de Forge — réécriture, pas de
partage de code entre les deux briques, cf. design doc)."""
import httpx
import pytest

import rss

_FLUX_VALIDE = """<?xml version="1.0"?>
<rss><channel>
<item>
  <title>Premier article</title>
  <link>https://example.com/1</link>
  <pubDate>Mon, 01 Jan 2026 10:00:00 GMT</pubDate>
</item>
<item>
  <title><![CDATA[Deuxième article &amp; CDATA]]></title>
  <link>https://example.com/2</link>
</item>
</channel></rss>
"""


def test_parser_items_extrait_titre_url_date():
    items = rss.parser_items(_FLUX_VALIDE)
    assert len(items) == 2
    assert items[0]["titre"] == "Premier article"
    assert items[0]["url"] == "https://example.com/1"
    assert "2026" in items[0]["published_at"]


def test_parser_items_gere_cdata():
    items = rss.parser_items(_FLUX_VALIDE)
    assert items[1]["titre"] == "Deuxième article &amp; CDATA"


def test_parser_items_repli_sur_guid_si_pas_de_link():
    flux = """<item>
      <title>Sans link</title>
      <guid>https://example.com/guid-1</guid>
    </item>"""
    items = rss.parser_items(flux)
    assert items[0]["url"] == "https://example.com/guid-1"


def test_parser_items_ignore_item_sans_titre_ou_url():
    flux = "<item><title>Sans URL du tout</title></item>"
    assert rss.parser_items(flux) == []


def test_parser_items_flux_vide():
    assert rss.parser_items("") == []


def test_fetcher_leve_sur_erreur_http(monkeypatch):
    def _get(*a, **k):
        raise httpx.ConnectError("DNS introuvable", request=None)
    monkeypatch.setattr(rss.httpx, "get", _get)
    with pytest.raises(httpx.ConnectError):
        rss.fetcher("https://exemple-invalide.test/rss")


def test_fetcher_leve_sur_status_erreur(monkeypatch):
    class _Rep:
        status_code = 404
        text = ""
        def raise_for_status(self):
            raise httpx.HTTPStatusError("404", request=None, response=None)
    monkeypatch.setattr(rss.httpx, "get", lambda *a, **k: _Rep())
    with pytest.raises(httpx.HTTPStatusError):
        rss.fetcher("https://exemple.test/rss")


def test_fetcher_renvoie_le_texte_si_ok(monkeypatch):
    class _Rep:
        status_code = 200
        text = _FLUX_VALIDE
        def raise_for_status(self):
            pass
    monkeypatch.setattr(rss.httpx, "get", lambda *a, **k: _Rep())
    assert rss.fetcher("https://exemple.test/rss") == _FLUX_VALIDE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/veille-info && python3 -m pytest test_rss.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'rss'`

- [ ] **Step 3: Write minimal implementation**

Créer `briques/veille-info/rss.py` :

```python
"""Fetch + parsing RSS pour la brique veille-info. Réécriture indépendante du parseur déjà
éprouvé dans `briques/forge/forge/core/app/routers/veille.py` — PAS importée depuis Forge
(décision : les deux briques restent indépendantes, cf. design doc)."""
from __future__ import annotations

import re

import httpx

_ITEM_RE = re.compile(r"<item[^>]*>([\s\S]*?)</item>", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", re.IGNORECASE | re.DOTALL)
_LINK_RE = re.compile(r"<link[^>]*>(.*?)</link>", re.IGNORECASE | re.DOTALL)
_GUID_RE = re.compile(r"<guid[^>]*>(https?://[^<]+)</guid>", re.IGNORECASE)
_PUBDATE_RE = re.compile(r"<pubDate[^>]*>(.*?)</pubDate>", re.IGNORECASE | re.DOTALL)


def parser_items(texte: str) -> list[dict]:
    """Parse les <item> d'un flux RSS → [{titre, url, published_at}]."""
    items: list[dict] = []
    for m in _ITEM_RE.finditer(texte):
        item = m.group(1)
        title_m = _TITLE_RE.search(item)
        titre = (title_m.group(1).strip() if title_m else "")
        link_m = _LINK_RE.search(item)
        url = link_m.group(1).strip() if link_m and link_m.group(1).strip() else ""
        if not url:
            guid_m = _GUID_RE.search(item)
            url = guid_m.group(1).strip() if guid_m else ""
        pub_m = _PUBDATE_RE.search(item)
        published_at = pub_m.group(1).strip() if pub_m else ""
        if titre and url:
            items.append({"titre": titre, "url": url, "published_at": published_at})
    return items


def fetcher(url: str) -> str:
    """Récupère le contenu brut d'un flux RSS. Lève en cas d'échec réseau/HTTP — à
    l'appelant de journaliser et continuer avec les autres sources."""
    r = httpx.get(url, timeout=10.0, headers={"User-Agent": "VeilleInfo/1.0 RSS Reader"},
                  follow_redirects=True)
    r.raise_for_status()
    return r.text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/veille-info && python3 -m pytest test_rss.py -v`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/rss.py briques/veille-info/test_rss.py
git commit -m "feat(veille-info): fetch + parsing RSS"
```

---

### Task 3: Client LLM (Gateway-aware)

**Files:**
- Create: `briques/veille-info/lib/__init__.py`
- Create: `briques/veille-info/lib/llm_client.py`
- Test: `briques/veille-info/test_llm_client.py`

**Interfaces:**
- Consumes: rien (module autonome)
- Produces (consommé par Task 4) : `llm_client.llm_complete(prompt: str, model: str = "", system: str = "", temperature: float = 0.3) -> str` (lève `RuntimeError` si aucun fournisseur configuré ou si l'appel échoue après retries)

- [ ] **Step 1: Write the failing test**

Créer `briques/veille-info/test_llm_client.py` :

```python
"""Tests du client LLM Gateway-aware (copie adaptée de briques/synopsis/lib/llm_client.py —
même motif, brique indépendante). Aucun réseau réel."""
import os

import pytest

from lib import llm_client


def test_leve_si_aucun_fournisseur_configure(monkeypatch):
    monkeypatch.delenv("GATEWAY_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Aucun fournisseur"):
        llm_client.llm_complete("bonjour")


def test_appel_gateway_ok(monkeypatch):
    monkeypatch.setenv("GATEWAY_URL", "http://gateway.local:4001")
    monkeypatch.setenv("GATEWAY_KEY", "test-key")

    captured = {}

    class _Rep:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "Résumé généré."}}]}

    def _post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _Rep()

    monkeypatch.setattr(llm_client.httpx, "post", _post)
    resultat = llm_client.llm_complete("Résume ceci.", system="Tu es concis.")
    assert resultat == "Résumé généré."
    assert captured["url"] == "http://gateway.local:4001/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["messages"][0] == {"role": "system", "content": "Tu es concis."}
    assert captured["json"]["messages"][1] == {"role": "user", "content": "Résume ceci."}


def test_appel_gateway_erreur_http_leve_apres_retries(monkeypatch):
    monkeypatch.setenv("GATEWAY_URL", "http://gateway.local:4001")
    monkeypatch.setenv("GATEWAY_KEY", "test-key")

    class _Rep:
        status_code = 500
        text = "erreur serveur"

    monkeypatch.setattr(llm_client.httpx, "post", lambda *a, **k: _Rep())
    monkeypatch.setattr(llm_client.time, "sleep", lambda *a: None)
    with pytest.raises(RuntimeError, match="LLM call failed"):
        llm_client.llm_complete("bonjour")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/veille-info && python3 -m pytest test_llm_client.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'lib'`

- [ ] **Step 3: Write minimal implementation**

Créer `briques/veille-info/lib/__init__.py` (vide) :

```python
```

Créer `briques/veille-info/lib/llm_client.py` :

```python
"""LLM Client — Gateway-aware with standalone fallback (copie adaptée de
briques/synopsis/lib/llm_client.py — chaque brique duplique sa propre petite lib client,
pas de package partagé entre conteneurs de briques).

Priority:
  1. GATEWAY_URL (Workplace LiteLLM) — OpenAI-compatible /v1/chat/completions
  2. OPENROUTER_API_KEY — direct OpenRouter API
  3. OPENCODE_GO_API_KEY — direct OpenCode Go API
"""

import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("LLM_MODEL", "deepseek/deepseek-v4-flash")
MAX_RETRIES = 2


def llm_complete(prompt: str, model: str = "", system: str = "", temperature: float = 0.3) -> str:
    model = model or DEFAULT_MODEL
    gateway_url = os.getenv("GATEWAY_URL", "").rstrip("/")
    gateway_key = os.getenv("GATEWAY_KEY", os.getenv("LITELLM_MASTER_KEY", ""))

    if gateway_url:
        return _complete_openai_compatible(
            f"{gateway_url}/v1/chat/completions",
            prompt, model, system, temperature,
            api_key=gateway_key,
        )

    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if openrouter_key:
        return _complete_openai_compatible(
            "https://openrouter.ai/api/v1/chat/completions",
            prompt, model, system, temperature,
            api_key=openrouter_key,
            extra_headers={"HTTP-Referer": "https://veille-info.local", "X-Title": "VeilleInfo"},
        )

    opencode_key = os.getenv("OPENCODE_GO_API_KEY", "")
    if opencode_key:
        return _complete_openai_compatible(
            "https://opencode.ai/zen/go/v1/chat/completions",
            prompt, model, system, temperature,
            api_key=opencode_key,
        )

    raise RuntimeError(
        "Aucun fournisseur LLM configuré. "
        "Définissez GATEWAY_URL, OPENROUTER_API_KEY ou OPENCODE_GO_API_KEY."
    )


def _complete_openai_compatible(
    base_url: str,
    prompt: str,
    model: str,
    system: str = "",
    temperature: float = 0.3,
    api_key: str = "",
    extra_headers: dict = None,
) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 32000,
    }

    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = httpx.post(base_url, json=payload, headers=headers, timeout=180)
            if r.status_code == 200:
                data = r.json()
                return data["choices"][0]["message"]["content"]
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                last_err = f"Rate limited (attempt {attempt + 1})"
                continue
            last_err = f"HTTP {r.status_code}: {r.text[:300]}"
        except httpx.RequestError as e:
            last_err = str(e)
            if attempt < MAX_RETRIES:
                time.sleep(2)

    raise RuntimeError(f"LLM call failed after {MAX_RETRIES + 1} attempts: {last_err}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/veille-info && python3 -m pytest test_llm_client.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/lib/ briques/veille-info/test_llm_client.py
git commit -m "feat(veille-info): client LLM Gateway-aware (motif synopsis)"
```

---

### Task 4: Pipeline quotidien (digest.py)

**Files:**
- Create: `briques/veille-info/digest.py`
- Test: `briques/veille-info/test_digest.py`

**Interfaces:**
- Consumes:
  - `stockage.lister_user_ids_actifs() -> list[str]` (Task 1)
  - `stockage.digest_existe(user_id: str, date: str | None = None) -> bool` (Task 1)
  - `stockage.lister_sources(user_id: str, *, actives_seulement: bool = False) -> list[dict]` (Task 1)
  - `stockage.inserer_article(user_id: str, source_id: int, titre: str, url: str, published_at: str) -> bool` (Task 1)
  - `stockage.articles_du_jour(user_id: str, date: str | None = None) -> list[dict]` (Task 1)
  - `stockage.inserer_digest(user_id: str, texte_resume: str, nb_articles: int, date: str | None = None) -> dict` (Task 1)
  - `rss.fetcher(url: str) -> str`, `rss.parser_items(texte: str) -> list[dict]` (Task 2)
  - `lib.llm_client.llm_complete(prompt: str, system: str = "") -> str` (Task 3)
- Produces (consommé par Task 5) : `digest.executer_digest_quotidien(user_ids: list[str] | None = None) -> dict` → `{"utilisateurs_traites": int, "digests_crees": int}`

**Note d'isolation des tests** : `executer_digest_quotidien` accepte un paramètre optionnel
`user_ids` — si fourni, seuls CES utilisateurs sont traités (au lieu de la découverte via
`stockage.lister_user_ids_actifs()`). La route HTTP de Task 5 n'utilisera JAMAIS ce
paramètre (elle traite toujours tout le monde, conformément au design). Il existe
uniquement pour que les tests puissent cibler précisément l'utilisateur qu'ils viennent de
créer, SANS jamais toucher aux sources laissées par d'autres fichiers de test dans la même
base SQLite partagée (convention du projet : une seule DB par session de test, cf.
`briques/mail/conftest.py`) — sans ce paramètre, un appel non scopé traiterait aussi les
sources (aux URLs factices) créées par `test_stockage.py`/`test_main.py`, déclenchant de
vrais appels réseau en test.

- [ ] **Step 1: Write the failing test**

Créer `briques/veille-info/test_digest.py` :

```python
"""Tests du pipeline quotidien (S189-2). Idempotence, dégradation propre (source en échec,
Gateway en échec), aucun réseau réel.

Chaque test passe explicitement `user_ids=[...]` à `executer_digest_quotidien` pour ne
JAMAIS traiter les sources laissées par d'autres fichiers de test dans la DB partagée
(sinon : vrais appels réseau vers leurs URLs factices). Identifiants préfixés `digest-`
pour ne jamais entrer en collision avec les identifiants d'autres fichiers de test."""
import digest
import stockage


def test_user_ids_none_decouvre_via_stockage(monkeypatch):
    """Sans argument, le pipeline découvre les utilisateurs actifs via stockage (c'est le
    seul chemin emprunté par la route HTTP réelle) — vérifié en isolation via un faux
    stockage.lister_user_ids_actifs, sans toucher la vraie DB partagée."""
    monkeypatch.setattr(stockage, "lister_user_ids_actifs", lambda: [])
    resultat = digest.executer_digest_quotidien()
    assert resultat == {"utilisateurs_traites": 0, "digests_crees": 0}


def test_pipeline_complet_cree_un_digest(monkeypatch):
    stockage.creer_source("digest-alice", "Flux A", "https://a.example/rss")

    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "<flux/>")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article 1", "url": "https://a.example/1", "published_at": ""},
        {"titre": "Article 2", "url": "https://a.example/2", "published_at": ""},
    ])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé du jour.")

    resultat = digest.executer_digest_quotidien(user_ids=["digest-alice"])
    assert resultat == {"utilisateurs_traites": 1, "digests_crees": 1}

    digests = stockage.lister_digests("digest-alice")
    assert len(digests) == 1
    assert digests[0]["texte_resume"] == "Résumé du jour."
    assert digests[0]["nb_articles"] == 2


def test_idempotent_si_digest_deja_cree_aujourdhui(monkeypatch):
    stockage.creer_source("digest-bob", "Flux B", "https://b.example/rss")
    stockage.inserer_digest("digest-bob", "Déjà fait aujourd'hui.", 1)

    appele = {"llm": False}
    def _llm(prompt, system=""):
        appele["llm"] = True
        return "Ne devrait jamais être appelé."
    monkeypatch.setattr(digest, "llm_complete", _llm)

    resultat = digest.executer_digest_quotidien(user_ids=["digest-bob"])
    assert resultat["digests_crees"] == 0
    assert appele["llm"] is False
    assert len(stockage.lister_digests("digest-bob")) == 1  # pas de doublon


def test_aucun_nouvel_article_pas_de_digest(monkeypatch):
    stockage.creer_source("digest-carol", "Flux vide", "https://c.example/rss")
    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [])

    resultat = digest.executer_digest_quotidien(user_ids=["digest-carol"])
    assert resultat["digests_crees"] == 0
    assert stockage.lister_digests("digest-carol") == []


def test_source_en_echec_continue_avec_les_autres(monkeypatch):
    stockage.creer_source("digest-dave", "Casse", "https://en-panne.example/rss")
    stockage.creer_source("digest-dave", "OK", "https://ok.example/rss")

    def _fetcher(url):
        if "en-panne" in url:
            raise ConnectionError("injoignable")
        return "<flux/>"
    monkeypatch.setattr(digest.rss, "fetcher", _fetcher)
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article OK", "url": "https://ok.example/1", "published_at": ""},
    ])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé partiel.")

    resultat = digest.executer_digest_quotidien(user_ids=["digest-dave"])
    assert resultat["digests_crees"] == 1
    assert stockage.lister_digests("digest-dave")[0]["nb_articles"] == 1


def test_echec_llm_ne_cree_pas_de_digest_partiel(monkeypatch):
    stockage.creer_source("digest-erin", "Flux", "https://erin.example/rss")
    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "<flux/>")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article", "url": "https://erin.example/1", "published_at": ""},
    ])
    def _llm_qui_echoue(prompt, system=""):
        raise RuntimeError("Gateway indisponible")
    monkeypatch.setattr(digest, "llm_complete", _llm_qui_echoue)

    resultat = digest.executer_digest_quotidien(user_ids=["digest-erin"])
    assert resultat["digests_crees"] == 0
    assert stockage.lister_digests("digest-erin") == []
    # Les articles ont quand même été stockés (dispo pour le prochain passage)
    assert len(stockage.articles_du_jour("digest-erin")) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/veille-info && python3 -m pytest test_digest.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'digest'`

- [ ] **Step 3: Write minimal implementation**

Créer `briques/veille-info/digest.py` :

```python
"""Pipeline quotidien de la brique veille-info. Orchestration pure : fetch RSS pour chaque
personne ayant des sources actives → dédup → résumé LLM consolidé si nouveautés → digest
idempotent par (user_id, date). Ne lève jamais : toute panne (source injoignable, Gateway
indisponible) est journalisée et l'utilisateur suivant continue d'être traité."""
from __future__ import annotations

import logging

import rss
import stockage
from lib.llm_client import llm_complete

logger = logging.getLogger(__name__)

_SYSTEM = ("Tu es un assistant de veille informationnelle. Résume en français, en quelques "
          "phrases synthétiques, les nouveaux articles listés ci-dessous. Regroupe par thème "
          "si pertinent, cite les points notables, reste factuel et concis.")


def _construire_prompt(articles: list[dict]) -> str:
    lignes = [f"- {a['titre']} ({a['url']})" for a in articles]
    return "Nouveaux articles du jour :\n" + "\n".join(lignes)


def _traiter_utilisateur(user_id: str) -> bool:
    """Traite un utilisateur : fetch ses sources actives, résume s'il y a du nouveau.
    Renvoie True si un digest a été créé."""
    if stockage.digest_existe(user_id):
        return False

    for source in stockage.lister_sources(user_id, actives_seulement=True):
        try:
            texte = rss.fetcher(source["url"])
            items = rss.parser_items(texte)
        except Exception as e:  # noqa: BLE001 — une source en échec ne bloque pas les autres
            logger.warning("Veille-info fetch source %r (user=%s) : %s",
                          source["nom"], user_id, e)
            continue
        for item in items:
            stockage.inserer_article(user_id, source["id"], item["titre"], item["url"],
                                     item["published_at"])

    articles = stockage.articles_du_jour(user_id)
    if not articles:
        return False

    try:
        resume = llm_complete(_construire_prompt(articles), system=_SYSTEM)
    except Exception as e:  # noqa: BLE001 — Gateway indisponible : pas de digest partiel
        logger.warning("Veille-info résumé LLM (user=%s) : %s", user_id, e)
        return False

    stockage.inserer_digest(user_id, resume, len(articles))
    return True


def executer_digest_quotidien(user_ids: list[str] | None = None) -> dict:
    """Point d'entrée appelé par l'horloge du Cœur (ou à la main). Traite TOUTES les
    personnes ayant au moins une source active, ou seulement `user_ids` si fourni.

    `user_ids` existe pour les tests (cibler précisément un utilisateur sans toucher aux
    sources laissées par d'autres fichiers de test dans la même DB partagée) — la route HTTP
    de `main.py` ne le fournit JAMAIS, elle traite toujours tout le monde."""
    cibles = user_ids if user_ids is not None else stockage.lister_user_ids_actifs()
    digests_crees = sum(1 for uid in cibles if _traiter_utilisateur(uid))
    return {"utilisateurs_traites": len(cibles), "digests_crees": digests_crees}
```

Note : `test_digest.py` monkeypatch `digest.llm_complete` (le nom importé dans le module,
via `from lib.llm_client import llm_complete`), pas `lib.llm_client.llm_complete` — c'est le
nom résolu au moment de l'appel dans `digest.py` qui compte.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/veille-info && python3 -m pytest test_digest.py -v`
Expected: `6 passed`

(Étape déjà couverte : le test de découverte via `stockage.lister_user_ids_actifs` mocké,
plus les 5 tests scopés par `user_ids=[...]`.)

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/digest.py briques/veille-info/test_digest.py
git commit -m "feat(veille-info): pipeline quotidien (fetch + dédup + résumé consolidé)"
```

---

### Task 5: API FastAPI (main.py)

**Files:**
- Create: `briques/veille-info/main.py`
- Test: `briques/veille-info/test_main.py`

**Interfaces:**
- Consumes:
  - `stockage.creer_source`, `stockage.lister_sources`, `stockage.supprimer_source`, `stockage.lister_digests`, `stockage.digest_get` (Task 1)
  - `digest.executer_digest_quotidien(user_ids: list[str] | None = None) -> dict` (Task 4) — la route HTTP l'appelle SANS argument (traite tout le monde)
- Produces: l'app FastAPI `main.app`, montable par uvicorn (`CMD` du Dockerfile, Task 6)

- [ ] **Step 1: Write the failing test**

Créer `briques/veille-info/test_main.py` :

```python
"""Tests API de la brique veille-info : CRUD sources isolé par personne, digests, gate du
déclenchement horloge. TestClient direct (pas de Docker).

Identifiants préfixés `main-` (jamais utilisés dans test_stockage.py/test_digest.py) : la
DB SQLite est partagée sur toute la session de test (une seule, cf. conftest.py), donc tout
identifiant réutilisé entre fichiers fausserait les comptages exacts (`len(...) == 1`).

Les deux tests `/digest/executer` mockent `main.digest.executer_digest_quotidien` : ils ne
vérifient QUE le gate d'authentification (401 vs 200), pas le pipeline lui-même (déjà
exhaustivement couvert par test_digest.py) — sans ce mock, l'appel réel traiterait TOUTES
les sources de la DB partagée, y compris celles (URLs factices) laissées par d'autres
fichiers de test, déclenchant de vrais appels réseau."""
from fastapi.testclient import TestClient

import main
import stockage

client = TestClient(main.app)


def test_sante():
    r = client.get("/sante")
    assert r.status_code == 200
    assert r.json()["statut"] == "ok"


def test_creer_lister_supprimer_source():
    r = client.post("/sources", headers={"X-User-Id": "main-alice"},
                    json={"nom": "Flux A", "url": "https://a.example/rss"})
    assert r.status_code == 201
    source_id = r.json()["id"]

    r = client.get("/sources", headers={"X-User-Id": "main-alice"})
    assert len(r.json()) == 1

    r = client.delete(f"/sources/{source_id}", headers={"X-User-Id": "main-alice"})
    assert r.status_code == 200
    assert client.get("/sources", headers={"X-User-Id": "main-alice"}).json() == []


def test_sources_isolees_par_x_user_id():
    client.post("/sources", headers={"X-User-Id": "main-bob"},
               json={"nom": "Flux de Bob", "url": "https://bob.example/rss"})
    r = client.get("/sources", headers={"X-User-Id": "main-carol"})
    assert all(s["nom"] != "Flux de Bob" for s in r.json())


def test_supprimer_source_dune_autre_personne_echoue():
    r = client.post("/sources", headers={"X-User-Id": "main-dave"},
                    json={"nom": "Flux privé", "url": "https://dave.example/rss"})
    source_id = r.json()["id"]
    r = client.delete(f"/sources/{source_id}", headers={"X-User-Id": "main-mallory"})
    assert r.status_code == 404


def test_lister_et_lire_digest():
    stockage.inserer_digest("main-erin", "Résumé du jour.", 3)
    r = client.get("/digests", headers={"X-User-Id": "main-erin"})
    assert len(r.json()) == 1
    digest_id = r.json()[0]["id"]
    r = client.get(f"/digests/{digest_id}", headers={"X-User-Id": "main-erin"})
    assert r.json()["texte_resume"] == "Résumé du jour."


def test_lire_digest_dune_autre_personne_404():
    d = stockage.inserer_digest("main-frank", "Privé.", 1)
    r = client.get(f"/digests/{d['id']}", headers={"X-User-Id": "main-grace"})
    assert r.status_code == 404


def test_digest_executer_ouvert_si_pas_de_cle_configuree(monkeypatch):
    monkeypatch.setattr(main.digest, "executer_digest_quotidien",
                        lambda: {"utilisateurs_traites": 0, "digests_crees": 0})
    r = client.post("/digest/executer")
    assert r.status_code == 200
    assert "utilisateurs_traites" in r.json()


def test_digest_executer_gate_si_cle_configuree(monkeypatch):
    monkeypatch.setattr(main.digest, "executer_digest_quotidien",
                        lambda: {"utilisateurs_traites": 0, "digests_crees": 0})
    monkeypatch.setenv("VEILLE_INFO_KEY", "secret-horloge")
    r = client.post("/digest/executer")
    assert r.status_code == 401
    r = client.post("/digest/executer", headers={"Authorization": "Bearer secret-horloge"})
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/veille-info && python3 -m pytest test_main.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Write minimal implementation**

Créer `briques/veille-info/main.py` :

```python
"""Brique « veille-info » — RSS multi-sources → résumé quotidien consolidé, v0.1.0.

Produit autonome (port 6120), isolé par personne (X-User-Id, motif mail S185/agenda S182).
Fetch programmé (tâche horloge quotidienne déclarée dans manifest.json) : voir digest.py.
Aucune génération audio dans cette version — spec séparé
(docs/superpowers/specs/2026-07-21-veille-info-brique-design.md).
"""
from __future__ import annotations

import hashlib
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import digest
import stockage

app = FastAPI(title="Veille-info — RSS multi-sources → résumé quotidien", version="0.1.0")

_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"])

API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}


def tenant_actuel(x_api_key: Optional[str] = Header(None),
                  authorization: Optional[str] = Header(None),
                  x_user_id: Optional[str] = Header(None)) -> str:
    """Résout la personne. Même motif que briques/mail (S185) : la clé du Cœur
    (VEILLE_INFO_KEY) fait EMPRUNTER l'identité X-User-Id (isolation par personne au sein du
    foyer) ; toute autre clé retombe sur une empreinte (tenant externe). Fail-closed si
    API_KEYS est défini ; sinon (dev) « public »."""
    presentee = x_api_key or (authorization or "").removeprefix("Bearer ").strip() or None
    if API_KEYS:
        if presentee not in API_KEYS:
            raise HTTPException(401, "Clé API manquante ou invalide (header X-API-Key).")
    elif not presentee:
        return "public"
    cle_coeur = os.environ.get("VEILLE_INFO_KEY")
    if cle_coeur and presentee == cle_coeur:
        return f"perso:{x_user_id or 'perso'}"
    return hashlib.sha256((presentee or "public").encode()).hexdigest()[:16]


def verifier_cle_horloge(authorization: Optional[str] = Header(None)) -> None:
    """Gate de /digest/executer : jeton partagé VEILLE_INFO_KEY, PAS tenant_actuel — cette
    route traite TOUTES les personnes en un seul appel (motif horloge), elle n'est donc pas
    scopée à un seul tenant. Fail-closed si VEILLE_INFO_KEY est défini."""
    attendu = os.environ.get("VEILLE_INFO_KEY")
    if not attendu:
        return
    presentee = (authorization or "").removeprefix("Bearer ").strip()
    if presentee != attendu:
        raise HTTPException(401, "Jeton horloge invalide (header Authorization: Bearer ...).")


@app.get("/sante", tags=["système"])
def sante():
    return {"statut": "ok", "version": "0.1.0"}


class CreerSource(BaseModel):
    nom: str = Field(min_length=1)
    url: str = Field(min_length=1)


@app.get("/sources", tags=["sources"])
def lister_sources_route(tenant: str = Depends(tenant_actuel)):
    return stockage.lister_sources(tenant)


@app.post("/sources", tags=["sources"], status_code=201)
def creer_source_route(body: CreerSource, tenant: str = Depends(tenant_actuel)):
    return stockage.creer_source(tenant, body.nom, body.url)


@app.delete("/sources/{source_id}", tags=["sources"])
def supprimer_source_route(source_id: int, tenant: str = Depends(tenant_actuel)):
    ok = stockage.supprimer_source(tenant, source_id)
    if not ok:
        raise HTTPException(404, "Source introuvable.")
    return {"ok": True}


@app.get("/digests", tags=["digests"])
def lister_digests_route(tenant: str = Depends(tenant_actuel)):
    return stockage.lister_digests(tenant)


@app.get("/digests/{digest_id}", tags=["digests"])
def lire_digest_route(digest_id: int, tenant: str = Depends(tenant_actuel)):
    d = stockage.digest_get(tenant, digest_id)
    if d is None:
        raise HTTPException(404, "Digest introuvable.")
    return d


@app.post("/digest/executer", tags=["digest"])
def executer_digest_route(_: None = Depends(verifier_cle_horloge)):
    return digest.executer_digest_quotidien()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/veille-info && python3 -m pytest test_main.py -v`
Expected: `8 passed`

Puis lancer toute la suite de la brique pour confirmer l'absence de régression entre tâches :

Run: `cd briques/veille-info && python3 -m pytest -v`
Expected: `33 passed` (8 test_stockage + 8 test_rss + 3 test_llm_client + 6 test_digest +
8 test_main, aucun échec, aucun test sauté)

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/main.py briques/veille-info/test_main.py
git commit -m "feat(veille-info): API FastAPI (sources, digests, déclenchement horloge)"
```

---

### Task 6: Scaffolding brique (manifest, Docker, .env.example)

**Files:**
- Create: `briques/veille-info/requirements.txt`
- Create: `briques/veille-info/Dockerfile`
- Create: `briques/veille-info/docker-compose.yml`
- Create: `briques/veille-info/manifest.json`
- Modify: `.env.example` (nouvelle section, en fin de fichier ou à côté d'une brique voisine)

**Interfaces:**
- Consumes: `main:app` (Task 5, référencé par la commande uvicorn du Dockerfile)
- Produces: brique découvrable par le Cœur (`core/registre.py` scanne `briques/*/manifest.json` — aucune inscription centrale à faire ailleurs) et déployable par `docker compose`.

- [ ] **Step 1: Write the failing test**

Il n'y a pas de test pytest pour du JSON/YAML statique — la vérification est un script
one-shot qui échoue tant que les fichiers n'existent pas :

Run: `python3 -c "import json; json.load(open('briques/veille-info/manifest.json'))"`
Expected: FAIL avec `FileNotFoundError`

- [ ] **Step 2: Confirm the failure**

(Étape déjà couverte par le Run ci-dessus — le fichier n'existe pas encore.)

- [ ] **Step 3: Write the files**

Créer `briques/veille-info/requirements.txt` :

```
# Brique veille-info — RSS multi-sources → résumé quotidien. Dépendances minces et épinglées.
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
```

Créer `briques/veille-info/Dockerfile` :

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "6120"]
```

Créer `briques/veille-info/docker-compose.yml` :

```yaml
services:
  veille-info:
    build: .
    container_name: workplace_veille_info
    image: workplace/veille-info:0.1.0   # tag épinglé (pas de :latest flottant)
    env_file:
      - path: ../../.env
        required: false
    ports:
      - "6120:6120"
    environment:
      - PORT=6120
      - VEILLE_INFO_DB=/data/veille_info.db
      - CORS_ORIGINS=${CORS_ORIGINS:-*}
      # API_KEYS, VEILLE_INFO_KEY, GATEWAY_URL/KEY/MODEL : ABSENTS du `environment` exprès —
      # viennent du .env racine via env_file (piège « env shadow » : ne PAS les redéclarer
      # en `=${VAR:-}`, cf. fix-env-shadow-composes). Sans GATEWAY_URL : le résumé échoue
      # proprement (pas de digest ce jour-là, retry au prochain passage horloge).
    volumes:
      - veille_info_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6120/sante')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

volumes:
  veille_info_data:
```

Créer `briques/veille-info/manifest.json` :

```json
{
  "nom": "veille-info",
  "famille": "veille",
  "version": "0.1.0",
  "description": "Veille informationnelle : suit des sources RSS par personne, fetch quotidien automatique, résumé consolidé par IA (Gateway) des nouveaux articles. Isolé par personne (X-User-Id, motif mail S185). Pas de génération audio dans cette version (spec séparé prévu, appellera la brique voix).",
  "role": "veille-info",
  "couche": "backend",
  "statut": "a_tester",
  "chemin_source": "~/Desktop/Workplace/briques/veille-info",
  "port": 6120,
  "url_sante": "http://host.docker.internal:6120/sante",
  "depends_on": [],
  "offre": [
    "sources_rss_par_personne",
    "fetch_quotidien_automatique",
    "resume_consolide_llm",
    "isolation_par_personne"
  ],
  "taches": [
    {
      "nom": "digest-quotidien",
      "description": "Fetch RSS + résumé consolidé du jour pour chaque personne ayant des sources actives.",
      "methode": "POST",
      "chemin": "/digest/executer",
      "cadence_heures": 24,
      "idempotent": true,
      "entete_token_env": "VEILLE_INFO_KEY",
      "tolere_echec": true
    }
  ],
  "capacites": [
    {
      "nom": "veille_info_sources_lister",
      "description": "Liste les sources RSS suivies par la personne connectée. Sert « quelles sont mes sources de veille », « qu'est-ce que je suis en train de suivre ». Lecture seule.",
      "methode": "GET",
      "chemin": "/sources",
      "action": false,
      "niveau": 0,
      "socle": false
    },
    {
      "nom": "veille_info_source_ajouter",
      "description": "Ajoute une source RSS à suivre (nom + URL du flux). Sert « suis ce flux RSS », « ajoute cette source à ma veille ».",
      "methode": "POST",
      "chemin": "/sources",
      "params": {
        "nom": {"type": "string", "description": "Nom lisible de la source (ex. « Le Monde Tech »).", "requis": true},
        "url": {"type": "string", "description": "URL du flux RSS.", "requis": true}
      },
      "action": true,
      "niveau": 1,
      "socle": false
    },
    {
      "nom": "veille_info_source_supprimer",
      "description": "Retire une source RSS de la veille (ne supprime pas les articles déjà collectés).",
      "methode": "DELETE",
      "chemin": "/sources/{source_id}",
      "params": {
        "source_id": {"type": "integer", "description": "Identifiant de la source à retirer.", "requis": true}
      },
      "action": true,
      "niveau": 1,
      "socle": false
    },
    {
      "nom": "veille_info_digests_lister",
      "description": "Liste les digests quotidiens déjà générés (date + nombre d'articles). Sert « qu'est-ce qu'il y a eu comme veille récemment ».",
      "methode": "GET",
      "chemin": "/digests",
      "action": false,
      "niveau": 0,
      "socle": false
    },
    {
      "nom": "veille_info_digest_lire",
      "description": "Lit le texte complet d'un digest quotidien. Sert « lis-moi le résumé de la veille d'aujourd'hui/du [date] ».",
      "methode": "GET",
      "chemin": "/digests/{digest_id}",
      "params": {
        "digest_id": {"type": "integer", "description": "Identifiant du digest à lire.", "requis": true}
      },
      "action": false,
      "niveau": 0,
      "socle": false
    }
  ]
}
```

Ajouter à `.env.example`, juste après la section « Brique « mail » » (repérer la ligne
`MAIL_UI_URL=http://localhost:6030/` et insérer la nouvelle section immédiatement après) :

```
# ── Brique « veille-info » (RSS multi-sources → résumé quotidien, port 6120) ──
# Fetch quotidien automatique (tâche horloge) de sources RSS par personne + résumé consolidé
# via la Gateway (GATEWAY_URL/GATEWAY_KEY déjà définis plus haut, aucune clé propre requise
# pour le résumé). Sans Gateway configurée : pas de digest ce jour-là (dégradation propre,
# retry au prochain passage). Clé que le Cœur présente (X-API-Key) : VIDE en mono-utilisateur.
# Définie : le Cœur emprunte l'identité de la personne connectée (X-User-Id) — chaque membre
# du foyer a SES sources et SES digests, isolés des autres (motif mail S185). Fail-closed
# (API_KEYS non vide côté veille-info) : lister aussi cette clé dans l'API_KEYS de la brique.
VEILLE_INFO_KEY=
```

- [ ] **Step 4: Verify**

Run: `python3 -c "import json; d = json.load(open('briques/veille-info/manifest.json')); assert d['famille'] == 'veille'; assert d['port'] == 6120; assert d['taches'][0]['chemin'] == '/digest/executer'; assert d['taches'][0]['cadence_heures'] == 24; print('manifest OK')"`
Expected: `manifest OK`

Run: `docker compose -f briques/veille-info/docker-compose.yml config --quiet && echo "compose OK"`
Expected: `compose OK` (valide la syntaxe YAML et la résolution des variables — ne nécessite
PAS que le daemon Docker tourne). Si `docker` n'est pas disponible dans l'environnement
d'exécution du plan, noter ce point dans le rapport et le signaler comme à vérifier avant le
déploiement — ne pas bloquer la tâche pour ça (régime « preuve Docker différé » du projet :
coder + tester ici, prouver le déploiement sur le HP séparément).

Run: `cd briques/veille-info && python3 -m pytest -v`
Expected: tous les tests des Tasks 1 à 5 passent toujours (aucune régression — cette tâche
n'a touché aucun fichier `.py`).

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/requirements.txt briques/veille-info/Dockerfile \
       briques/veille-info/docker-compose.yml briques/veille-info/manifest.json .env.example
git commit -m "feat(veille-info): manifest, Dockerfile, docker-compose, .env.example"
```
