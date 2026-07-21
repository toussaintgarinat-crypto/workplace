# Audio du digest veille-info Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Générer automatiquement un MP3 du résumé quotidien via la brique `voix` déjà existante, sans jamais bloquer la création du digest texte si l'audio échoue.

**Architecture:** Une nouvelle table `digest_audio` (SQLite) reliée à `digests` par clé étrangère ; `digest.py` appelle `POST {VOIX_URL}/rendre` (motif exact `briques/studio/main.py:1010-1028`, httpx synchrone) juste après avoir créé un digest, en best-effort strict ; `stockage.lister_digests`/`digest_get` exposent `audio_url`/`audio_duree` via une jointure, sans changement de route dans `main.py`.

**Tech Stack:** Python 3.12, FastAPI (déjà en place), httpx, sqlite3 (stdlib), pytest.

## Global Constraints

- Aucune modification de `briques/voix/` — `POST /rendre` existant suffit tel quel.
- L'appel audio est **strictement best-effort** : sa réussite ou son échec ne doit JAMAIS
  changer la valeur de retour de `_traiter_utilisateur` (le digest texte, déjà créé avant
  l'appel audio, compte comme « digest créé » quel que soit le sort de l'audio). Concrètement :
  l'appel HTTP vers `voix` a son PROPRE `try/except` local dans `_traiter_utilisateur`, il ne
  doit PAS remonter jusqu'au filet `_traiter_utilisateur_sans_planter` — sinon un échec audio
  ferait compter « pas de digest » pour une personne qui EN A pourtant un, et le prochain
  passage de l'horloge la sauterait (`digest_existe` déjà vrai) sans jamais retenter l'audio.
- Aucun réseau réel dans les tests — l'appel vers `voix` est mocké (`monkeypatch` sur `digest.httpx.post`, même convention que `rss.py`/`lib/llm_client.py`).
- `VOIX_URL` : défaut `http://host.docker.internal:5985` (le port réel déployé, confirmé dans `briques/studio/docker-compose.yml:19` — PAS le défaut Python erroné de `briques/studio/studio.py:41`, port 5810, incohérence préexistante ailleurs, hors périmètre).
- Motif d'appel : aucune clé API envoyée (cohérent avec `briques/studio/main.py:1010-1028`, qui n'en envoie pas non plus — le parc entier tourne aujourd'hui sans ces clés de service configurées).
- `digest_id` n'est PAS `UNIQUE` dans `digest_audio` (schéma ouvert à plusieurs versions futures), mais la logique applicative de cette version n'en insère jamais qu'une par digest.

---

### Task 1: Table `digest_audio` + enrichissement du stockage

**Files:**
- Modify: `briques/veille-info/stockage.py`
- Test: `briques/veille-info/test_stockage.py`

**Interfaces:**
- Consumes: rien de nouveau (étend le module existant)
- Produces (consommé par Task 2) :
  - `stockage.inserer_audio_digest(digest_id: int, url: str, duree: float | None) -> dict` → `{"id", "digest_id", "url", "duree", "created_at"}`
  - `stockage.lister_digests(user_id: str) -> list[dict]` (signature inchangée) — chaque dict porte désormais aussi `"audio_url"` et `"audio_duree"` (`None`/`None` si aucun audio)
  - `stockage.digest_get(user_id: str, digest_id: int) -> dict | None` (signature inchangée) — même enrichissement

- [ ] **Step 1: Write the failing test**

Ajouter à la fin de `briques/veille-info/test_stockage.py` :

```python
def test_digest_sans_audio_a_des_champs_audio_none():
    d = stockage.inserer_digest("iris", "Résumé.", 1)
    assert stockage.digest_get("iris", d["id"])["audio_url"] is None
    assert stockage.digest_get("iris", d["id"])["audio_duree"] is None
    assert stockage.lister_digests("iris")[0]["audio_url"] is None


def test_inserer_audio_digest_apparait_dans_lister_et_get():
    d = stockage.inserer_digest("jules", "Résumé.", 1)
    stockage.inserer_audio_digest(d["id"], "https://voix.example/episodes/x.mp3", 42.5)

    lu = stockage.digest_get("jules", d["id"])
    assert lu["audio_url"] == "https://voix.example/episodes/x.mp3"
    assert lu["audio_duree"] == 42.5

    liste = stockage.lister_digests("jules")
    assert liste[0]["audio_url"] == "https://voix.example/episodes/x.mp3"


def test_audio_digest_isole_par_digest_id():
    d1 = stockage.inserer_digest("karim", "Résumé 1.", 1)
    d2 = stockage.inserer_digest("karim", "Résumé 2.", 1, date="2020-01-01")
    stockage.inserer_audio_digest(d1["id"], "https://voix.example/1.mp3", 10.0)

    assert stockage.digest_get("karim", d1["id"])["audio_url"] == "https://voix.example/1.mp3"
    assert stockage.digest_get("karim", d2["id"])["audio_url"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/veille-info && python3 -m pytest test_stockage.py -v`
Expected: FAIL — `test_digest_sans_audio_a_des_champs_audio_none` échoue avec `KeyError: 'audio_url'` (le champ n'existe pas encore) ; `test_inserer_audio_digest_apparait_dans_lister_et_get` et `test_audio_digest_isole_par_digest_id` échouent avec `AttributeError: module 'stockage' has no attribute 'inserer_audio_digest'`.

- [ ] **Step 3: Write minimal implementation**

Dans `briques/veille-info/stockage.py`, ajouter la table `digest_audio` à `_SCHEMA` (juste après la table `digests`, avant la fermeture des triples guillemets) :

```python
CREATE TABLE IF NOT EXISTS digest_audio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_id INTEGER NOT NULL REFERENCES digests(id),
    url TEXT NOT NULL,
    duree REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_digest_audio_digest ON digest_audio(digest_id);
```

Remplacer `_digest_dict` par une version qui lit aussi les colonnes jointes (présentes uniquement quand la requête appelante fait la jointure — cf. Step 3 suite) :

```python
def _digest_dict(r: sqlite3.Row) -> dict:
    cols = r.keys()
    return {"id": r["id"], "date": r["date"], "texte_resume": r["texte_resume"],
            "nb_articles": r["nb_articles"], "created_at": r["created_at"],
            "audio_url": r["audio_url"] if "audio_url" in cols else None,
            "audio_duree": r["audio_duree"] if "audio_duree" in cols else None}
```

Remplacer `lister_digests` et `digest_get` pour joindre le dernier audio de chaque digest (sous-requête corrélée — volume personnel, pas besoin d'optimiser davantage) :

```python
_DIGEST_AVEC_AUDIO = """
    SELECT d.*, da.url AS audio_url, da.duree AS audio_duree
    FROM digests d
    LEFT JOIN digest_audio da ON da.id = (
        SELECT id FROM digest_audio WHERE digest_id = d.id ORDER BY id DESC LIMIT 1
    )
"""


def lister_digests(user_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(_DIGEST_AVEC_AUDIO + " WHERE d.user_id = ? ORDER BY d.date DESC",
                         (user_id,)).fetchall()
    return [_digest_dict(r) for r in rows]


def digest_get(user_id: str, digest_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(_DIGEST_AVEC_AUDIO + " WHERE d.id = ? AND d.user_id = ?",
                        (digest_id, user_id)).fetchone()
    return _digest_dict(row) if row else None
```

Ajouter, à la fin du fichier (section « Audio ») :

```python
# ── Audio ─────────────────────────────────────────────────────
def inserer_audio_digest(digest_id: int, url: str, duree: float | None) -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO digest_audio (digest_id, url, duree, created_at) VALUES (?,?,?,?)",
            (digest_id, url, duree, _maintenant()))
        row = c.execute("SELECT * FROM digest_audio WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"id": row["id"], "digest_id": row["digest_id"], "url": row["url"],
            "duree": row["duree"], "created_at": row["created_at"]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/veille-info && python3 -m pytest test_stockage.py -v`
Expected: `11 passed` (8 existants + 3 nouveaux)

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/stockage.py briques/veille-info/test_stockage.py
git commit -m "feat(veille-info): table digest_audio + enrichissement lister_digests/digest_get"
```

---

### Task 2: Génération audio dans le pipeline (digest.py)

**Files:**
- Modify: `briques/veille-info/digest.py`
- Test: `briques/veille-info/test_digest.py`

**Interfaces:**
- Consumes:
  - `stockage.inserer_audio_digest(digest_id: int, url: str, duree: float | None) -> dict` (Task 1)
  - `stockage.inserer_digest(...) -> dict` (déjà existant, renvoie maintenant un dict avec `"id"` — inchangé, déjà utilisé)
- Produces: aucune nouvelle fonction publique — `_traiter_utilisateur`/`executer_digest_quotidien` gardent exactement leurs signatures actuelles ; l'audio est un effet de bord best-effort à l'intérieur de `_traiter_utilisateur`.

- [ ] **Step 1: Write the failing test**

Ajouter à la fin de `briques/veille-info/test_digest.py` :

```python
def test_audio_genere_apres_un_digest_reussi(monkeypatch):
    stockage.creer_source("digest-iris", "Flux", "https://iris.example/rss")
    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "<flux/>")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article", "url": "https://iris.example/1", "published_at": ""},
    ])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé du jour.")

    class _Rep:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"url": "https://voix.example/episodes/veille-info-1.mp3", "duree": 30.0}
    monkeypatch.setattr(digest.httpx, "post", lambda *a, **k: _Rep())

    resultat = digest.executer_digest_quotidien(user_ids=["digest-iris"])
    assert resultat == {"utilisateurs_traites": 1, "digests_crees": 1}

    d = stockage.lister_digests("digest-iris")[0]
    assert d["audio_url"] == "https://voix.example/episodes/veille-info-1.mp3"
    assert d["audio_duree"] == 30.0


def test_audio_injoignable_ne_bloque_pas_le_digest(monkeypatch):
    stockage.creer_source("digest-jules", "Flux", "https://jules.example/rss")
    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "<flux/>")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article", "url": "https://jules.example/1", "published_at": ""},
    ])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé du jour.")

    def _post_qui_casse(*a, **k):
        raise ConnectionError("voix injoignable")
    monkeypatch.setattr(digest.httpx, "post", _post_qui_casse)

    resultat = digest.executer_digest_quotidien(user_ids=["digest-jules"])
    # Le digest texte compte comme créé même si l'audio a échoué.
    assert resultat == {"utilisateurs_traites": 1, "digests_crees": 1}

    d = stockage.lister_digests("digest-jules")[0]
    assert d["texte_resume"] == "Résumé du jour."
    assert d["audio_url"] is None


def test_audio_place_holder_sans_moteur_ne_bloque_pas_le_digest(monkeypatch):
    """`voix` répond 200 mais sans URL (aucun moteur TTS configuré, place_holder honnête) —
    même dégradation propre que l'injoignabilité."""
    stockage.creer_source("digest-karim", "Flux", "https://karim.example/rss")
    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "<flux/>")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article", "url": "https://karim.example/1", "published_at": ""},
    ])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé du jour.")

    class _RepPlaceholder:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"place_holder": True, "note": "Aucun moteur de synthèse configuré"}
    monkeypatch.setattr(digest.httpx, "post", lambda *a, **k: _RepPlaceholder())

    resultat = digest.executer_digest_quotidien(user_ids=["digest-karim"])
    assert resultat["digests_crees"] == 1
    assert stockage.lister_digests("digest-karim")[0]["audio_url"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/veille-info && python3 -m pytest test_digest.py -v`
Expected: FAIL sur les 3 nouveaux tests — `AttributeError: module 'digest' has no attribute 'httpx'` (le module ne l'importe pas encore).

- [ ] **Step 3: Write minimal implementation**

Dans `briques/veille-info/digest.py`, ajouter les imports et la constante `VOIX_URL` en haut du fichier (juste après les imports existants) :

```python
import os

import httpx
import rss
import stockage
from lib.llm_client import llm_complete

logger = logging.getLogger(__name__)

VOIX_URL = os.getenv("VOIX_URL", "http://host.docker.internal:5985")
```

Ajouter une fonction `_generer_audio` juste après `_construire_prompt` :

```python
def _generer_audio(digest_id: int, texte: str) -> None:
    """Génère l'audio du digest via la brique voix (motif briques/studio/main.py:1010-1028,
    aucune clé — cohérent avec le reste du parc). Best-effort STRICT : un échec est
    journalisé, jamais propagé — le digest texte (déjà créé par l'appelant) reste utilisable
    sans audio. Pas de retry automatique dans cette version."""
    try:
        r = httpx.post(f"{VOIX_URL}/rendre", timeout=180,
                       json={"episode_id": f"veille-info-{digest_id}",
                             "segments": [{"voix": None, "texte": texte}]})
        r.raise_for_status()
        res = r.json()
    except Exception as e:  # noqa: BLE001 — audio best-effort, le digest texte reste utilisable
        logger.warning("Veille-info audio digest_id=%s : %s", digest_id, e)
        return
    if not res.get("url"):
        logger.warning("Veille-info audio digest_id=%s : pas d'URL (place_holder=%s)",
                       digest_id, res.get("place_holder"))
        return
    stockage.inserer_audio_digest(digest_id, res["url"], res.get("duree"))
```

Modifier la fin de `_traiter_utilisateur` (remplacer les 3 dernières lignes) :

```python
    d = stockage.inserer_digest(user_id, resume, len(articles))
    stockage.marquer_articles_digestes([a["id"] for a in articles])
    _generer_audio(d["id"], resume)
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd briques/veille-info && python3 -m pytest test_digest.py -v`
Expected: `12 passed` (9 existants + 3 nouveaux)

Puis lancer toute la suite de la brique pour confirmer l'absence de régression :

Run: `cd briques/veille-info && python3 -m pytest -v`
Expected: `41 passed` (11 test_stockage + 8 test_rss + 3 test_llm_client + 12 test_digest + 8 test_main — aucun échec)

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/digest.py briques/veille-info/test_digest.py
git commit -m "feat(veille-info): génère l'audio du digest via voix (best-effort)"
```

---

### Task 3: Vérification API end-to-end (test seul, aucun changement de main.py)

**Files:**
- Test: `briques/veille-info/test_main.py`

**Interfaces:**
- Consumes: `stockage.inserer_audio_digest` (Task 1) — appelé directement dans le test pour préparer les données, comme le fait déjà `test_lister_et_lire_digest` avec `stockage.inserer_digest`.
- Produces: rien de nouveau — ce test prouve seulement que `GET /digests` et `GET /digests/{id}` (routes déjà existantes, code inchangé) exposent bien `audio_url`/`audio_duree` maintenant que `stockage.lister_digests`/`digest_get` les renvoient (Task 1).

- [ ] **Step 1: Write the failing test**

Ajouter à la fin de `briques/veille-info/test_main.py` :

```python
def test_digest_expose_audio_url_via_lapi(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    d = stockage.inserer_digest("perso:main-iris", "Résumé.", 1)
    stockage.inserer_audio_digest(d["id"], "https://voix.example/episodes/y.mp3", 12.0)

    r = client.get(f"/digests/{d['id']}", headers=_entetes("main-iris"))
    assert r.json()["audio_url"] == "https://voix.example/episodes/y.mp3"
    assert r.json()["audio_duree"] == 12.0
```

Note : ce test suit le motif déjà en place dans ce fichier (`monkeypatch.setenv` par test,
pas de fixture autouse — voir `test_creer_lister_supprimer_source` et les 4 autres tests
d'isolation existants pour le même motif) — `_entetes(utilisateur)` construit
`{"X-API-Key": "cle-coeur", "X-User-Id": utilisateur}`, et le seed direct utilise
`"perso:main-iris"` (le tenant que `tenant_actuel` résout réellement pour un appel
authentifié avec `X-User-Id: main-iris`), pas `"main-iris"` brut — exactement comme
`test_lister_et_lire_digest` le fait déjà pour `"perso:main-erin"`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd briques/veille-info && python3 -m pytest test_main.py -v`
Expected: FAIL — `KeyError: 'audio_url'` tant que Task 1 (déjà mergée à ce stade du plan)
serait absente ; à ce stade du plan (Task 1 et 2 déjà faites), ce test doit en fait PASSER
dès l'écriture — c'est un test de non-régression/couverture, pas un vrai cycle RED/GREEN sur
du code neuf. Si le test échoue ici, c'est le signal que Task 1 n'a pas correctement propagé
`audio_url` jusqu'à la route HTTP — investiguer avant de continuer plutôt que de considérer
ça comme normal.

- [ ] **Step 3: Confirm it already passes (no production code change needed)**

Run: `cd briques/veille-info && python3 -m pytest test_main.py -v`
Expected: `9 passed` (8 existants + 1 nouveau) — sans avoir touché `main.py`, la preuve que
l'enrichissement de Task 1 traverse déjà correctement toute la pile HTTP.

- [ ] **Step 4: Run the whole brique suite one last time**

Run: `cd briques/veille-info && python3 -m pytest -v`
Expected: `42 passed` (11 test_stockage + 8 test_rss + 3 test_llm_client + 12 test_digest + 9 test_main)

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/test_main.py
git commit -m "test(veille-info): vérifie audio_url bout-en-bout via l'API /digests"
```
