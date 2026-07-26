# S199 — Veille : digests par thématique + audio global + envoi email — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre de générer un audio unique concaténant plusieurs digests de veille
(avec un interlude parlé annonçant chaque thématique) et de l'envoyer par email — ce qui
suppose d'abord que les digests existent PAR THÉMATIQUE (aujourd'hui un seul digest fusionné
par jour et par personne).

**Architecture:** (1) `sources` gagne une colonne `thematique` ; le pipeline quotidien de
`digest.py` produit désormais un digest **par thématique** ayant du nouveau contenu, chacun
avec son propre audio (mécanisme `_generer_audio` existant, inchangé). (2) Un nouveau
module `audio_global.py` télécharge (`httpx`, pas de volume Docker partagé) l'audio de
chaque digest sélectionné + un interlude TTS de transition, les concatène (`ffmpeg -f
concat`, motif déjà en prod dans `briques/voix/main.py`), et le sert via son propre
endpoint protégé par jeton (pas de chiffrement E2E — motif `briques/voix::telecharger_episode`,
pas `briques/transferts` qui est chiffré et inadapté à un appel serveur-à-serveur). (3)
L'envoi email réutilise `mail_composer` + `mail_brouillon_envoyer` de la brique Mail
existante (motif d'appel cross-brique de `digest.py::_pousser_memoire`).

**Tech Stack:** FastAPI (Python), SQLite via `stockage.py`, `httpx` pour les appels
cross-brique, `ffmpeg`/`ffprobe` en subprocess, JS vanilla dans `briques/atelier-veille`.

## Global Constraints

- Isolation par personne : toutes les nouvelles tables/fonctions utilisent `user_id`
  (motif `tenant_actuel`, PAS `cle_api` — ce motif est propre à `briques/personnages`,
  pas à `veille-info`).
- Aucune modification de signature existante ne doit casser les appels positionnels déjà
  en test : tout nouveau paramètre (`thematique`) est ajouté en **fin de signature avec
  une valeur par défaut rétro-compatible** (`""` pour une colonne, `None` pour un filtre
  optionnel), jamais inséré au milieu.
- Best-effort strict partout où l'existant l'est déjà (génération audio, push mémoire) :
  un échec sur UN item ne bloque jamais les autres (déjà le principe posé en S189/S193).
- Le lien de l'audio global n'est PAS chiffré (contenu non confidentiel) : jeton
  `secrets.token_urlsafe` non devinable + expiration vérifiée à l'accès, motif
  `briques/voix/main.py::telecharger_episode` — surtout PAS d'appel à `briques/transferts`
  (chiffré E2E, inadapté ici).

---

### Task 1: Migration schéma — `thematique` sur `sources` et `digests`

**Files:**
- Modify: `briques/veille-info/stockage.py` (schéma `_SCHEMA`, fonction `init`,
  `creer_source`, `_source_dict`, `articles_non_digestes`, `digest_existe`,
  `inserer_digest`, `_digest_dict`)
- Test: `briques/veille-info/test_stockage.py`

**Interfaces:**
- Consumes : rien (fondation du plan).
- Produces : `creer_source(user_id, nom, url, thematique="") -> dict` (dict inclut
  `thematique`), `digest_existe(user_id, date=None, thematique="") -> bool`,
  `inserer_digest(user_id, texte_resume, nb_articles, date=None, thematique="") -> dict`
  (dict inclut `thematique`), `articles_non_digestes(user_id, thematique=None) ->
  list[dict]` (`thematique=None` = comportement historique inchangé, toutes thématiques ;
  une valeur précise filtre par thématique via jointure `sources`), `thematiques_actives(user_id)
  -> list[str]` (nouveau) — utilisés par Task 2.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à la fin de `briques/veille-info/test_stockage.py` :

```python
def test_creer_source_avec_thematique():
    s = stockage.creer_source("thematique-alice", "Flux Tech", "https://t.example/rss",
                              thematique="Tech")
    assert s["thematique"] == "Tech"


def test_creer_source_sans_thematique_defaut_vide():
    s = stockage.creer_source("thematique-bob", "Flux", "https://b.example/rss")
    assert s["thematique"] == ""


def test_thematiques_actives_distinctes_et_ignore_desactivees():
    stockage.creer_source("thematique-carol", "Flux Tech", "https://tc.example/rss", thematique="Tech")
    stockage.creer_source("thematique-carol", "Flux Tech 2", "https://tc2.example/rss", thematique="Tech")
    off = stockage.creer_source("thematique-carol", "Flux Cosmétique",
                                "https://cc.example/rss", thematique="Cosmétique")
    with stockage._conn() as c:
        c.execute("UPDATE sources SET enabled = 0 WHERE id = ?", (off["id"],))
    assert stockage.thematiques_actives("thematique-carol") == ["Tech"]


def test_digest_existe_isole_par_thematique():
    assert stockage.digest_existe("thematique-dave", thematique="Tech") is False
    stockage.inserer_digest("thematique-dave", "Résumé tech.", 1, thematique="Tech")
    assert stockage.digest_existe("thematique-dave", thematique="Tech") is True
    assert stockage.digest_existe("thematique-dave", thematique="Cosmétique") is False


def test_deux_thematiques_meme_jour_meme_user():
    d1 = stockage.inserer_digest("thematique-erin", "Résumé tech.", 1, thematique="Tech")
    d2 = stockage.inserer_digest("thematique-erin", "Résumé cosmétique.", 1, thematique="Cosmétique")
    assert d1["id"] != d2["id"]
    digests = stockage.lister_digests("thematique-erin")
    assert len(digests) == 2
    assert {d["thematique"] for d in digests} == {"Tech", "Cosmétique"}


def test_articles_non_digestes_filtre_par_thematique():
    s_tech = stockage.creer_source("thematique-frank", "Flux Tech", "https://ft.example/rss",
                                   thematique="Tech")
    s_cosmo = stockage.creer_source("thematique-frank", "Flux Cosmétique",
                                    "https://fc.example/rss", thematique="Cosmétique")
    stockage.inserer_article("thematique-frank", s_tech["id"], "Article Tech",
                             "https://ft.example/1", "")
    stockage.inserer_article("thematique-frank", s_cosmo["id"], "Article Cosmétique",
                             "https://fc.example/1", "")

    tech = stockage.articles_non_digestes("thematique-frank", thematique="Tech")
    assert len(tech) == 1 and tech[0]["titre"] == "Article Tech"

    toutes = stockage.articles_non_digestes("thematique-frank")
    assert len(toutes) == 2  # thematique=None (défaut) : comportement historique inchangé


def test_migration_ajoute_thematique_sur_digests_existant(tmp_path, monkeypatch):
    """Simule une base ANCIENNE (avant thematique, contrainte UNIQUE(user_id, date)) — la
    forme réelle de la prod S193 — et vérifie que `init()` la met à niveau sans perte."""
    import sqlite3
    db_path = str(tmp_path / "ancienne.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE digests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, date TEXT NOT NULL,
        texte_resume TEXT NOT NULL, nb_articles INTEGER NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(user_id, date))""")
    conn.execute("INSERT INTO digests (user_id, date, texte_resume, nb_articles, created_at) "
                 "VALUES ('migr-user', '2026-07-20', 'Ancien résumé', 3, '2026-07-20T00:00:00')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(stockage, "_DB", db_path)
    stockage.init()

    digests = stockage.lister_digests("migr-user")
    assert len(digests) == 1
    assert digests[0]["thematique"] == ""
    assert digests[0]["texte_resume"] == "Ancien résumé"
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/veille-info && python -m pytest test_stockage.py -k thematique -v`
Expected: FAIL — `TypeError: creer_source() got an unexpected keyword argument 'thematique'`
(et échecs similaires sur les autres fonctions).

- [ ] **Step 3: Migrer le schéma**

Dans `briques/veille-info/stockage.py`, remplacer le bloc `_SCHEMA` (lignes 31-74) par :

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    nom TEXT NOT NULL,
    url TEXT NOT NULL,
    thematique TEXT NOT NULL DEFAULT '',
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
    digested INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, url)
);
CREATE INDEX IF NOT EXISTS idx_articles_user ON articles(user_id);

CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    thematique TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL,
    texte_resume TEXT NOT NULL,
    nb_articles INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, thematique, date)
);
CREATE INDEX IF NOT EXISTS idx_digests_user ON digests(user_id);

CREATE TABLE IF NOT EXISTS digest_audio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_id INTEGER NOT NULL REFERENCES digests(id),
    url TEXT NOT NULL,
    duree REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_digest_audio_digest ON digest_audio(digest_id);
"""


def _migrer_thematiques(c: sqlite3.Connection) -> None:
    """Met à niveau une base créée AVANT l'ajout de `thematique` (S199). `sources` : simple
    ALTER TABLE ADD COLUMN. `digests` : nécessite de recréer la table, SQLite ne permet pas
    de modifier une contrainte UNIQUE existante via ALTER TABLE. No-op sur une base déjà à
    jour (CREATE TABLE IF NOT EXISTS de `_SCHEMA` l'a créée directement dans sa forme finale)."""
    cols_sources = {r[1] for r in c.execute("PRAGMA table_info(sources)").fetchall()}
    if "thematique" not in cols_sources:
        c.execute("ALTER TABLE sources ADD COLUMN thematique TEXT NOT NULL DEFAULT ''")

    cols_digests = {r[1] for r in c.execute("PRAGMA table_info(digests)").fetchall()}
    if "thematique" not in cols_digests:
        c.executescript("""
            ALTER TABLE digests RENAME TO digests_old;
            CREATE TABLE digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                thematique TEXT NOT NULL DEFAULT '',
                date TEXT NOT NULL,
                texte_resume TEXT NOT NULL,
                nb_articles INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, thematique, date)
            );
            INSERT INTO digests (id, user_id, thematique, date, texte_resume, nb_articles, created_at)
                SELECT id, user_id, '', date, texte_resume, nb_articles, created_at FROM digests_old;
            DROP TABLE digests_old;
            CREATE INDEX IF NOT EXISTS idx_digests_user ON digests(user_id);
        """)
```

Remplacer la fonction `init` (lignes 77-83) par :

```python
def init() -> None:
    os.makedirs(os.path.dirname(_DB) or ".", exist_ok=True)
    with _conn() as c:
        c.executescript(_SCHEMA)
        _migrer_thematiques(c)


init()  # schéma prêt dès l'import (robuste même sous TestClient)
```

- [ ] **Step 4: Mettre à jour les fonctions sources/digests/articles**

Dans `briques/veille-info/stockage.py`, remplacer `_source_dict` (lignes 87-89) par :

```python
def _source_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "nom": r["nom"], "url": r["url"], "thematique": r["thematique"],
            "enabled": bool(r["enabled"]), "created_at": r["created_at"]}
```

Remplacer `creer_source` (lignes 92-98) par :

```python
def creer_source(user_id: str, nom: str, url: str, thematique: str = "") -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO sources (user_id, nom, url, thematique, enabled, created_at) "
            "VALUES (?,?,?,?,1,?)",
            (user_id, nom, url, thematique, _maintenant()))
        row = c.execute("SELECT * FROM sources WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _source_dict(row)
```

Ajouter, juste après `lister_user_ids_actifs` (après la ligne 120) :

```python
def thematiques_actives(user_id: str) -> list[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT thematique FROM sources WHERE user_id = ? AND enabled = 1",
            (user_id,)).fetchall()
    return [r["thematique"] for r in rows]


def retagger_source(user_id: str, source_id: int, thematique: str) -> bool:
    with _conn() as c:
        cur = c.execute("UPDATE sources SET thematique = ? WHERE id = ? AND user_id = ?",
                        (thematique, source_id, user_id))
    return cur.rowcount > 0
```

Remplacer `articles_non_digestes` (lignes 135-141) par :

```python
def articles_non_digestes(user_id: str, thematique: str | None = None) -> list[dict]:
    """`thematique=None` (défaut) : tous les articles non digérés, toutes thématiques
    confondues (comportement historique). Une valeur précise (y compris `""`) filtre sur
    cette thématique via jointure `sources` — c'est ce qu'utilise digest.py, qui traite
    thématique par thématique."""
    if thematique is None:
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM articles WHERE user_id = ? AND digested = 0 ORDER BY created_at ASC",
                (user_id,)).fetchall()
    else:
        with _conn() as c:
            rows = c.execute(
                "SELECT a.* FROM articles a JOIN sources s ON s.id = a.source_id "
                "WHERE a.user_id = ? AND a.digested = 0 AND s.thematique = ? "
                "ORDER BY a.created_at ASC",
                (user_id, thematique)).fetchall()
    return [{"id": r["id"], "titre": r["titre"], "url": r["url"],
            "published_at": r["published_at"]} for r in rows]
```

Remplacer `_digest_dict` (lignes 153-158) par :

```python
def _digest_dict(r: sqlite3.Row) -> dict:
    cols = r.keys()
    return {"id": r["id"], "date": r["date"], "thematique": r["thematique"] if "thematique" in cols else "",
            "texte_resume": r["texte_resume"], "nb_articles": r["nb_articles"],
            "created_at": r["created_at"],
            "audio_url": r["audio_url"] if "audio_url" in cols else None,
            "audio_duree": r["audio_duree"] if "audio_duree" in cols else None}
```

Remplacer `digest_existe` (lignes 170-175) par :

```python
def digest_existe(user_id: str, date: str | None = None, thematique: str = "") -> bool:
    date = date or _aujourdhui()
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM digests WHERE user_id = ? AND date = ? AND thematique = ?",
            (user_id, date, thematique)).fetchone()
    return row is not None
```

Remplacer `inserer_digest` (lignes 178-187) par :

```python
def inserer_digest(user_id: str, texte_resume: str, nb_articles: int,
                   date: str | None = None, thematique: str = "") -> dict:
    date = date or _aujourdhui()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO digests (user_id, thematique, date, texte_resume, nb_articles, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, thematique, date, texte_resume, nb_articles, _maintenant()))
        row = c.execute("SELECT * FROM digests WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _digest_dict(row)
```

- [ ] **Step 5: Lancer les tests, vérifier qu'ils passent**

Run: `cd briques/veille-info && python -m pytest test_stockage.py -v`
Expected: PASS (toutes les fonctions, y compris les 7 nouvelles).

- [ ] **Step 6: Commit**

```bash
git add briques/veille-info/stockage.py briques/veille-info/test_stockage.py
git commit -m "feat(veille-info): thématique par source + digests isolés par thématique"
```

---

### Task 2: Pipeline quotidien — un digest par thématique

**Files:**
- Modify: `briques/veille-info/digest.py` (`_traiter_utilisateur`,
  `_traiter_utilisateur_sans_planter`, `executer_digest_quotidien`)
- Test: `briques/veille-info/test_digest.py`

**Interfaces:**
- Consumes : `stockage.thematiques_actives(user_id) -> list[str]`,
  `stockage.digest_existe(user_id, thematique=...) -> bool`,
  `stockage.articles_non_digestes(user_id, thematique) -> list[dict]`,
  `stockage.inserer_digest(user_id, texte_resume, nb_articles, thematique=...) -> dict`
  (Task 1).
- Produces : `_traiter_utilisateur(user_id) -> int` (nombre de digests créés, plus un bool)
  — utilisé par `executer_digest_quotidien`, qui garde sa forme de retour externe
  `{"utilisateurs_traites": int, "digests_crees": int}` inchangée.

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à la fin de `briques/veille-info/test_digest.py` :

```python
def test_digest_separe_par_thematique(monkeypatch):
    stockage.creer_source("digest-multi", "Flux Tech", "https://tech-multi.example/rss",
                          thematique="Tech")
    stockage.creer_source("digest-multi", "Flux Cosmétique", "https://cosmo-multi.example/rss",
                          thematique="Cosmétique")

    # L'URL fetchée sert d'identifiant : chaque source produit un article à SA propre URL
    # (évite une collision UNIQUE(user_id, url) entre les deux sources du test).
    monkeypatch.setattr(digest.rss, "fetcher", lambda url: url)
    monkeypatch.setattr(digest.rss, "parser_items",
                        lambda texte: [{"titre": "Article", "url": texte + "/1", "published_at": ""}])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé.")

    resultat = digest.executer_digest_quotidien(user_ids=["digest-multi"])
    assert resultat == {"utilisateurs_traites": 1, "digests_crees": 2}

    digests = stockage.lister_digests("digest-multi")
    assert {d["thematique"] for d in digests} == {"Tech", "Cosmétique"}


def test_digest_idempotent_par_thematique_independamment(monkeypatch):
    stockage.creer_source("digest-idem", "Flux Tech", "https://tech-idem.example/rss",
                          thematique="Tech")
    stockage.creer_source("digest-idem", "Flux Cosmétique", "https://cosmo-idem.example/rss",
                          thematique="Cosmétique")
    stockage.inserer_digest("digest-idem", "Déjà fait pour Tech.", 1, thematique="Tech")

    monkeypatch.setattr(digest.rss, "fetcher", lambda url: url)
    monkeypatch.setattr(digest.rss, "parser_items",
                        lambda texte: [{"titre": "Article", "url": texte + "/1", "published_at": ""}])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé Cosmétique.")

    resultat = digest.executer_digest_quotidien(user_ids=["digest-idem"])
    assert resultat["digests_crees"] == 1  # seulement Cosmétique, Tech déjà fait aujourd'hui

    par_thematique = {d["thematique"]: d["texte_resume"] for d in stockage.lister_digests("digest-idem")}
    assert par_thematique["Tech"] == "Déjà fait pour Tech."
    assert par_thematique["Cosmétique"] == "Résumé Cosmétique."


def test_digest_aucun_fetch_si_toutes_thematiques_deja_faites(monkeypatch):
    """Restaure l'optimisation historique : si TOUT est déjà digéré aujourd'hui, on ne
    refait aucun appel RSS (évite de marteler les flux à chaque exécution de l'horloge)."""
    stockage.creer_source("digest-complet", "Flux", "https://complet.example/rss", thematique="Tech")
    stockage.inserer_digest("digest-complet", "Déjà fait.", 1, thematique="Tech")

    appele = {"fetch": False}
    def _fetcher(url):
        appele["fetch"] = True
        return url
    monkeypatch.setattr(digest.rss, "fetcher", _fetcher)

    resultat = digest.executer_digest_quotidien(user_ids=["digest-complet"])
    assert resultat["digests_crees"] == 0
    assert appele["fetch"] is False
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/veille-info && python -m pytest test_digest.py -k thematique -v`
Expected: FAIL — un seul digest créé au lieu de 2 (le pipeline fusionne encore tout).

- [ ] **Step 3: Réécrire `_traiter_utilisateur`**

Dans `briques/veille-info/digest.py`, remplacer `_traiter_utilisateur` (lignes 76-119) par :

```python
def _traiter_utilisateur(user_id: str) -> int:
    """Traite un utilisateur : fetch ses sources actives, résume PAR THÉMATIQUE s'il y a du
    nouveau (S199 — une thématique = un groupe de sources partageant `sources.thematique`,
    "" = thématique par défaut). Renvoie le nombre de digests créés (0, 1, ou plusieurs)."""
    thematiques = stockage.thematiques_actives(user_id)
    if thematiques and all(stockage.digest_existe(user_id, thematique=t) for t in thematiques):
        return 0  # tout est déjà fait aujourd'hui : pas la peine de fetcher (motif historique)

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

    digests_crees = 0
    for thematique in thematiques:
        if stockage.digest_existe(user_id, thematique=thematique):
            continue

        articles = stockage.articles_non_digestes(user_id, thematique)
        if not articles:
            continue

        try:
            resume = llm_complete(_construire_prompt(articles), system=_SYSTEM)
        except Exception as e:  # noqa: BLE001 — Gateway indisponible : pas de digest partiel
            logger.warning("Veille-info résumé LLM (user=%s, thematique=%r) : %s",
                           user_id, thematique, e)
            continue

        d = stockage.inserer_digest(user_id, resume, len(articles), thematique=thematique)
        try:
            stockage.marquer_articles_digestes([a["id"] for a in articles])
            _generer_audio(d["id"], resume)
            _pousser_memoire(user_id, resume, d["date"])
        except Exception as e:  # noqa: BLE001 — le digest (déjà créé ci-dessus) doit compter
            # comme créé même si le marquage des articles ou l'audio échoue ensuite (même
            # filet que l'ancienne version mono-digest, cf. commentaire d'origine préservé
            # dans l'historique git).
            logger.warning("Veille-info marquage articles/audio (user=%s, digest_id=%s) : %s",
                           user_id, d["id"], e)
        digests_crees += 1
    return digests_crees
```

- [ ] **Step 4: Mettre à jour `_traiter_utilisateur_sans_planter` et `executer_digest_quotidien`**

Dans `briques/veille-info/digest.py`, remplacer `_traiter_utilisateur_sans_planter` (lignes
122-133) par :

```python
def _traiter_utilisateur_sans_planter(user_id: str) -> int:
    """Enrobe `_traiter_utilisateur` : une panne inattendue (ex. un appel `stockage.*` qui
    lève, en dehors des chemins déjà gardés dans `_traiter_utilisateur`) est journalisée
    et compte 0 digest créé pour cette personne, jamais propagée."""
    try:
        return _traiter_utilisateur(user_id)
    except Exception as e:  # noqa: BLE001 — une personne en échec inattendu ne doit jamais arrêter le lot
        logger.warning("Veille-info échec inattendu (user=%s) : %s", user_id, e)
        return 0
```

Dans `executer_digest_quotidien` (lignes 136-145), remplacer :

```python
    digests_crees = sum(1 for uid in cibles if _traiter_utilisateur_sans_planter(uid))
```

par :

```python
    digests_crees = sum(_traiter_utilisateur_sans_planter(uid) for uid in cibles)
```

- [ ] **Step 5: Lancer TOUTE la suite de tests de la brique, vérifier qu'ils passent**

Run: `cd briques/veille-info && python -m pytest -v`
Expected: PASS — les tests historiques (une seule thématique implicite `""`) continuent de
produire exactement 1 digest par jour comme avant ; les 3 nouveaux tests passent.

- [ ] **Step 6: Commit**

```bash
git add briques/veille-info/digest.py briques/veille-info/test_digest.py
git commit -m "feat(veille-info): pipeline quotidien génère un digest par thématique"
```

---

### Task 3: API — thématique sur les sources

**Files:**
- Modify: `briques/veille-info/main.py` (`CreerSource`, route `POST /sources`, nouvelle
  route `PATCH /sources/{source_id}/thematique`)
- Test: `briques/veille-info/test_main.py`

**Interfaces:**
- Consumes : `stockage.creer_source(tenant, nom, url, thematique) -> dict`,
  `stockage.retagger_source(tenant, source_id, thematique) -> bool` (Task 1).
- Produces : `POST /sources` accepte `thematique` optionnel ; `PATCH
  /sources/{id}/thematique` — body `{"thematique": str}` — consommé par l'UI (Task 10).

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à la fin de `briques/veille-info/test_main.py` :

```python
def test_creer_source_avec_thematique(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    r = client.post("/sources", headers=_entetes("main-thematique"),
                    json={"nom": "Flux Tech", "url": "https://mt.example/rss", "thematique": "Tech"})
    assert r.status_code == 201
    assert r.json()["thematique"] == "Tech"


def test_retagger_source(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    r = client.post("/sources", headers=_entetes("main-retag"),
                    json={"nom": "Flux", "url": "https://mr.example/rss"})
    source_id = r.json()["id"]

    r = client.patch(f"/sources/{source_id}/thematique", headers=_entetes("main-retag"),
                     json={"thematique": "Cosmétique"})
    assert r.status_code == 200

    r = client.get("/sources", headers=_entetes("main-retag"))
    assert r.json()[0]["thematique"] == "Cosmétique"


def test_retagger_source_dune_autre_personne_echoue(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    r = client.post("/sources", headers=_entetes("main-retag-a"),
                    json={"nom": "Flux privé", "url": "https://mra.example/rss"})
    source_id = r.json()["id"]
    r = client.patch(f"/sources/{source_id}/thematique", headers=_entetes("main-retag-b"),
                     json={"thematique": "Piraté"})
    assert r.status_code == 404
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/veille-info && python -m pytest test_main.py -k "thematique or retagger" -v`
Expected: FAIL — 404 sur la route `PATCH` (inexistante), `thematique` absent de la réponse
de création.

- [ ] **Step 3: Ajouter le champ et la route**

Dans `briques/veille-info/main.py`, remplacer `class CreerSource` (lignes 73-75) par :

```python
class CreerSource(BaseModel):
    nom: str = Field(min_length=1)
    url: str = Field(min_length=1)
    thematique: str = ""
```

Remplacer `creer_source_route` (lignes 83-85) par :

```python
@app.post("/sources", tags=["sources"], status_code=201)
def creer_source_route(body: CreerSource, tenant: str = Depends(tenant_actuel)):
    return stockage.creer_source(tenant, body.nom, body.url, body.thematique)
```

Ajouter, juste après `supprimer_source_route` (après la ligne 93) :

```python
class RetaggerSource(BaseModel):
    thematique: str = ""


@app.patch("/sources/{source_id}/thematique", tags=["sources"])
def retagger_source_route(source_id: int, body: RetaggerSource,
                          tenant: str = Depends(tenant_actuel)):
    ok = stockage.retagger_source(tenant, source_id, body.thematique)
    if not ok:
        raise HTTPException(404, "Source introuvable.")
    return {"ok": True}
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `cd briques/veille-info && python -m pytest test_main.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/main.py briques/veille-info/test_main.py
git commit -m "feat(veille-info): API thématique sur les sources (création + retag)"
```

---

### Task 4: Dockerfile — installer ffmpeg

**Files:**
- Modify: `briques/veille-info/Dockerfile`

**Interfaces:**
- Consumes : rien.
- Produces : binaires `ffmpeg`/`ffprobe` sur le `PATH`, requis par Task 5.

- [ ] **Step 1: Ajouter ffmpeg à l'image**

Dans `briques/veille-info/Dockerfile`, remplacer :

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```

par :

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# ffmpeg/ffprobe : concaténation de l'audio global (Task 5, motif déjà en prod dans
# briques/voix — même dépendance, cf. briques/voix/Dockerfile).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```

- [ ] **Step 2: Vérifier que l'image se construit et expose ffmpeg**

Run: `cd briques/veille-info && docker build -t workplace/veille-info:test . && docker run --rm workplace/veille-info:test ffmpeg -version`
Expected: la commande affiche une version ffmpeg (pas de « command not found »).

- [ ] **Step 3: Commit**

```bash
git add briques/veille-info/Dockerfile
git commit -m "build(veille-info): installe ffmpeg (requis par l'audio global)"
```

---

### Task 5: Module `audio_global.py` — génération (concaténation + interludes)

**Files:**
- Create: `briques/veille-info/audio_global.py`
- Test: `briques/veille-info/test_audio_global.py`

**Interfaces:**
- Consumes : `stockage.digest_get(user_id, digest_id) -> dict | None` (Task 1, champ
  `audio_url`/`thematique`), `stockage.inserer_audio_global(...)` (Task 6, définie AVANT
  ce module dans l'ordre d'exécution des tests — Task 6 doit livrer sa fonction pour que
  ce module s'exécute ; dans l'ordre du plan, Task 6 vient après pour rester groupée avec
  le reste du schéma d'envoi, mais son implémentation de `inserer_audio_global` doit
  exister avant de lancer les tests de CE module — voir note d'ordre d'exécution ci-dessous).
- Produces : `generer(user_id: str, ordre_digest_ids: list[int]) -> dict`,
  `AudioGlobalError` (exception) — utilisés par Task 8 (endpoint).

> **Note d'ordre d'exécution :** ce module appelle `stockage.inserer_audio_global`, qui
> n'existe pas encore avant Task 6. Pour garder chaque tâche indépendamment testable, ce
> Task 5 mocke `stockage.inserer_audio_global` dans ses propres tests (`monkeypatch`) — la
> fonction réelle est livrée par Task 6. Si les tâches sont exécutées dans l'ordre du plan
> (5 puis 6), c'est transparent ; si un exécutant préfère faire Task 6 avant Task 5, ça
> fonctionne aussi (le mock reste valide dans les deux cas).

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `briques/veille-info/test_audio_global.py` :

```python
"""Tests du module audio_global (S199) : concaténation ffmpeg de plusieurs digests déjà
audio-générés + interludes TTS par thématique. Aucun appel réseau réel (httpx et
subprocess.run sont mockés) ; ffmpeg/ffprobe RÉELS sont utilisés pour le test bout-en-bout
minimal (disponibles dans l'image, cf. Task 4)."""
import stockage
import audio_global


def test_generer_sans_digest_selectionne_leve():
    try:
        audio_global.generer("audio-vide", [])
        assert False, "devrait lever AudioGlobalError"
    except audio_global.AudioGlobalError as e:
        assert "sélectionné" in str(e)


def test_generer_digest_introuvable_leve():
    try:
        audio_global.generer("audio-intro", [999999])
        assert False, "devrait lever AudioGlobalError"
    except audio_global.AudioGlobalError as e:
        assert "introuvable" in str(e)


def test_generer_digest_sans_audio_leve(monkeypatch):
    d = stockage.inserer_digest("audio-sansaudio", "Résumé.", 1, thematique="Tech")
    try:
        audio_global.generer("audio-sansaudio", [d["id"]])
        assert False, "devrait lever AudioGlobalError"
    except audio_global.AudioGlobalError as e:
        assert "audio" in str(e).lower()


def test_generer_concatene_deux_digests(monkeypatch, tmp_path):
    d1 = stockage.inserer_digest("audio-ok", "Résumé tech.", 1, thematique="Tech")
    d2 = stockage.inserer_digest("audio-ok", "Résumé cosmétique.", 1, thematique="Cosmétique")
    stockage.inserer_audio_digest(d1["id"], "https://voix.example/1.mp3", 5.0)
    stockage.inserer_audio_digest(d2["id"], "https://voix.example/2.mp3", 5.0)

    monkeypatch.setattr(audio_global, "_AUDIO_GLOBAL_DIR", tmp_path)

    # Fabrique un vrai petit MP3 silencieux (1s) réutilisé pour tous les segments (interludes
    # + digests) — évite de dépendre d'un vrai réseau tout en exerçant le VRAI ffmpeg concat.
    import subprocess
    segment = tmp_path / "silence.mp3"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
                    "-t", "1", "-c:a", "libmp3lame", str(segment)], check=True, capture_output=True)
    octets_segment = segment.read_bytes()

    def _fausse_synthese_interlude(texte):
        return octets_segment
    monkeypatch.setattr(audio_global, "_synthetiser_interlude", _fausse_synthese_interlude)

    def _faux_telecharger(url):
        return octets_segment
    monkeypatch.setattr(audio_global, "_telecharger", _faux_telecharger)

    appels = []
    def _faux_inserer_audio_global(user_id, jeton, ordre_digest_ids, fichier_path, duree, expire_le):
        appels.append((user_id, jeton, ordre_digest_ids, fichier_path, duree, expire_le))
        return {"id": 1, "user_id": user_id, "jeton": jeton, "ordre_thematiques": ordre_digest_ids,
                "fichier_path": fichier_path, "duree_secondes": duree, "expire_le": expire_le}
    monkeypatch.setattr(stockage, "inserer_audio_global", _faux_inserer_audio_global)

    resultat = audio_global.generer("audio-ok", [d1["id"], d2["id"]])

    assert resultat["id"] == 1
    assert len(appels) == 1
    _, jeton, ordre, fichier_path, duree, _ = appels[0]
    assert ordre == [d1["id"], d2["id"]]
    assert Path(fichier_path).exists()
    assert duree is not None and duree > 0


from pathlib import Path  # noqa: E402 — import groupé en bas pour rester lisible dans le diff
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/veille-info && python -m pytest test_audio_global.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audio_global'`.

- [ ] **Step 3: Écrire le module**

Créer `briques/veille-info/audio_global.py` :

```python
"""Audio global (S199) : concatène plusieurs digests DÉJÀ audio-générés (dans un ordre
choisi), avec un interlude TTS annonçant chaque thématique. Best-effort de bout en bout au
sens strict : toute étape manquante (digest sans audio, téléchargement en échec, ffmpeg en
échec) lève une erreur explicite avant de produire un résultat partiel — pas de "presque
bon" silencieux, contrairement à l'audio par digest qui, lui, reste best-effort (le digest
texte existe déjà sans lui)."""
from __future__ import annotations

import os
import secrets
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import stockage

VOIX_URL = os.getenv("VOIX_URL", "http://host.docker.internal:5985")
_AUDIO_GLOBAL_DIR = Path(os.getenv("VEILLE_INFO_AUDIO_GLOBAL_DIR", "/data/audio-global"))
_EXPIRATION_JOURS = 7


class AudioGlobalError(Exception):
    """Erreur explicite (digest sans audio, téléchargement/ffmpeg en échec)."""


def _telecharger(url: str) -> bytes:
    """Récupère les octets d'un fichier audio produit par une autre brique — pas de volume
    Docker partagé entre voix et veille-info (motif déjà utilisé par
    briques/transcription/main.py::_telecharger)."""
    try:
        r = httpx.get(url, timeout=60, follow_redirects=True)
        r.raise_for_status()
        return r.content
    except httpx.HTTPError as e:
        raise AudioGlobalError(f"Téléchargement audio impossible ({url}) : {e}") from e


def _synthetiser_interlude(texte: str) -> bytes:
    """Synthétise un court interlude TTS via briques/voix (même endpoint /rendre que
    digest.py::_generer_audio), renvoie directement les octets audio."""
    try:
        r = httpx.post(f"{VOIX_URL}/rendre", timeout=60,
                       json={"segments": [{"voix": None, "texte": texte}]})
        r.raise_for_status()
        url = r.json().get("url")
    except httpx.HTTPError as e:
        raise AudioGlobalError(f"Synthèse de l'interlude impossible : {e}") from e
    if not url:
        raise AudioGlobalError("Synthèse de l'interlude : pas d'URL renvoyée par la voix.")
    return _telecharger(url)


def generer(user_id: str, ordre_digest_ids: list[int]) -> dict:
    if not ordre_digest_ids:
        raise AudioGlobalError("Aucun digest sélectionné.")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fichiers = []
        for i, digest_id in enumerate(ordre_digest_ids):
            d = stockage.digest_get(user_id, digest_id)
            if d is None:
                raise AudioGlobalError(f"Digest {digest_id} introuvable.")
            if not d.get("audio_url"):
                raise AudioGlobalError(
                    f"Le digest « {d.get('thematique') or 'Général'} » du {d['date']} n'a pas "
                    "encore d'audio — génère-le d'abord avant de créer l'audio global.")

            nom_thematique = d.get("thematique") or "Général"
            interlude = _synthetiser_interlude(f"Voici les nouvelles pour la veille {nom_thematique}.")
            p_interlude = tmp_path / f"seg_{i:04d}a_interlude.mp3"
            p_interlude.write_bytes(interlude)
            fichiers.append(str(p_interlude))

            audio = _telecharger(d["audio_url"])
            p_digest = tmp_path / f"seg_{i:04d}b_digest.mp3"
            p_digest.write_bytes(audio)
            fichiers.append(str(p_digest))

        liste = tmp_path / "liste.txt"
        liste.write_text("\n".join(f"file '{f}'" for f in fichiers))
        _AUDIO_GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
        jeton = secrets.token_urlsafe(24)
        sortie = _AUDIO_GLOBAL_DIR / f"{jeton}.mp3"
        try:
            proc = subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", str(liste), "-c:a", "libmp3lame", "-q:a", "4", str(sortie)],
                capture_output=True, timeout=300)
        except FileNotFoundError as e:
            raise AudioGlobalError("ffmpeg introuvable dans l'image.") from e
        if proc.returncode != 0:
            raise AudioGlobalError(f"ffmpeg : {proc.stderr.decode('utf-8', 'ignore')[:300]}")

    duree = None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(sortie)],
            capture_output=True, text=True, timeout=10)
        duree = float(r.stdout.strip())
    except Exception:  # noqa: BLE001 — durée optionnelle, jamais bloquant
        pass

    expire_le = (datetime.now(timezone.utc) + timedelta(days=_EXPIRATION_JOURS)).isoformat()
    return stockage.inserer_audio_global(user_id, jeton, ordre_digest_ids, str(sortie), duree, expire_le)
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `cd briques/veille-info && python -m pytest test_audio_global.py -v`
Expected: PASS. (Nécessite `ffmpeg`/`ffprobe` sur la machine qui exécute les tests — déjà
présents en local d'après l'exploration initiale ; sinon `brew install ffmpeg` avant de
lancer.)

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/audio_global.py briques/veille-info/test_audio_global.py
git commit -m "feat(veille-info): génération de l'audio global (concaténation + interludes)"
```

---

### Task 6: Stockage — tables `veille_audio_global` et `veille_audio_global_envois`

**Files:**
- Modify: `briques/veille-info/stockage.py` (ajout au schéma + nouvelles fonctions)
- Test: `briques/veille-info/test_stockage.py`

**Interfaces:**
- Consumes : rien de nouveau (tables indépendantes des précédentes).
- Produces : `inserer_audio_global(user_id, jeton, ordre_digest_ids, fichier_path, duree,
  expire_le) -> dict`, `audio_global_par_jeton(jeton) -> dict | None`,
  `audio_global_get(user_id, audio_id) -> dict | None`, `lister_audio_global(user_id) ->
  list[dict]`, `inserer_envoi_audio_global(audio_global_id, destinataire, statut, detail) ->
  dict`, `lister_envois_audio_global(audio_global_id) -> list[dict]` — consommés par
  Task 5 (déjà mocké, cette tâche fournit l'implémentation réelle) et Task 8 (endpoints).

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à la fin de `briques/veille-info/test_stockage.py` :

```python
def test_inserer_et_lire_audio_global_par_jeton():
    a = stockage.inserer_audio_global("audioglobal-alice", "jeton-abc", [1, 2],
                                      "/data/audio-global/jeton-abc.mp3", 42.0,
                                      "2026-08-02T00:00:00+00:00")
    assert a["ordre_thematiques"] == [1, 2]
    lu = stockage.audio_global_par_jeton("jeton-abc")
    assert lu["id"] == a["id"]
    assert lu["fichier_path"] == "/data/audio-global/jeton-abc.mp3"
    assert stockage.audio_global_par_jeton("jeton-inexistant") is None


def test_audio_global_get_isole_par_user_id():
    a = stockage.inserer_audio_global("audioglobal-bob", "jeton-bob", [1],
                                      "/data/audio-global/jeton-bob.mp3", 10.0,
                                      "2026-08-02T00:00:00+00:00")
    assert stockage.audio_global_get("audioglobal-bob", a["id"]) is not None
    assert stockage.audio_global_get("audioglobal-mallory", a["id"]) is None


def test_lister_audio_global_ordre_recent_dabord():
    stockage.inserer_audio_global("audioglobal-carol", "jeton-c1", [1],
                                  "/data/audio-global/c1.mp3", 5.0, "2026-08-02T00:00:00+00:00")
    stockage.inserer_audio_global("audioglobal-carol", "jeton-c2", [2],
                                  "/data/audio-global/c2.mp3", 5.0, "2026-08-02T00:00:00+00:00")
    liste = stockage.lister_audio_global("audioglobal-carol")
    assert len(liste) == 2
    assert liste[0]["jeton"] == "jeton-c2"  # le plus récent en premier


def test_envois_audio_global_lies_au_bon_audio():
    a = stockage.inserer_audio_global("audioglobal-dave", "jeton-dave", [1],
                                      "/data/audio-global/dave.mp3", 5.0, "2026-08-02T00:00:00+00:00")
    stockage.inserer_envoi_audio_global(a["id"], "equipe@example.com", "envoye", None)
    stockage.inserer_envoi_audio_global(a["id"], "invalide@@", "echec", "adresse invalide")

    envois = stockage.lister_envois_audio_global(a["id"])
    assert len(envois) == 2
    par_dest = {e["destinataire"]: e["statut"] for e in envois}
    assert par_dest["equipe@example.com"] == "envoye"
    assert par_dest["invalide@@"] == "echec"
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/veille-info && python -m pytest test_stockage.py -k audio_global -v`
Expected: FAIL — `AttributeError: module 'stockage' has no attribute 'inserer_audio_global'`.

- [ ] **Step 3: Ajouter le schéma et les fonctions**

Dans `briques/veille-info/stockage.py`, ajouter `import json` en haut du fichier (après
`import sqlite3`), et étendre `_SCHEMA` (juste avant la fermeture `"""` finale, après le
bloc `digest_audio`) :

```python
CREATE TABLE IF NOT EXISTS veille_audio_global (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    jeton TEXT NOT NULL UNIQUE,
    ordre_thematiques TEXT NOT NULL,
    fichier_path TEXT NOT NULL,
    duree_secondes REAL,
    expire_le TEXT NOT NULL,
    cree_le TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audio_global_user ON veille_audio_global(user_id);
CREATE INDEX IF NOT EXISTS idx_audio_global_jeton ON veille_audio_global(jeton);

CREATE TABLE IF NOT EXISTS veille_audio_global_envois (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audio_global_id INTEGER NOT NULL REFERENCES veille_audio_global(id),
    destinataire TEXT NOT NULL,
    statut TEXT NOT NULL,
    detail TEXT,
    envoye_le TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_envois_audio_global ON veille_audio_global_envois(audio_global_id);
```

Ajouter à la fin de `briques/veille-info/stockage.py` :

```python
# ── Audio global (S199) ──────────────────────────────────────────
def _audio_global_dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "user_id": r["user_id"], "jeton": r["jeton"],
            "ordre_thematiques": json.loads(r["ordre_thematiques"]),
            "fichier_path": r["fichier_path"], "duree_secondes": r["duree_secondes"],
            "expire_le": r["expire_le"], "cree_le": r["cree_le"]}


def inserer_audio_global(user_id: str, jeton: str, ordre_digest_ids: list[int],
                         fichier_path: str, duree: float | None, expire_le: str) -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO veille_audio_global (user_id, jeton, ordre_thematiques, fichier_path, "
            "duree_secondes, expire_le, cree_le) VALUES (?,?,?,?,?,?,?)",
            (user_id, jeton, json.dumps(ordre_digest_ids), fichier_path, duree, expire_le,
             _maintenant()))
        row = c.execute("SELECT * FROM veille_audio_global WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _audio_global_dict(row)


def audio_global_par_jeton(jeton: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM veille_audio_global WHERE jeton = ?", (jeton,)).fetchone()
    return _audio_global_dict(row) if row else None


def audio_global_get(user_id: str, audio_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM veille_audio_global WHERE id = ? AND user_id = ?",
                        (audio_id, user_id)).fetchone()
    return _audio_global_dict(row) if row else None


def lister_audio_global(user_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM veille_audio_global WHERE user_id = ? ORDER BY cree_le DESC",
            (user_id,)).fetchall()
    return [_audio_global_dict(r) for r in rows]


def inserer_envoi_audio_global(audio_global_id: int, destinataire: str, statut: str,
                               detail: str | None) -> dict:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO veille_audio_global_envois (audio_global_id, destinataire, statut, "
            "detail, envoye_le) VALUES (?,?,?,?,?)",
            (audio_global_id, destinataire, statut, detail, _maintenant()))
        row = c.execute("SELECT * FROM veille_audio_global_envois WHERE id = ?",
                        (cur.lastrowid,)).fetchone()
    return dict(row)


def lister_envois_audio_global(audio_global_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM veille_audio_global_envois WHERE audio_global_id = ? "
            "ORDER BY envoye_le DESC", (audio_global_id,)).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `cd briques/veille-info && python -m pytest test_stockage.py -v && python -m pytest test_audio_global.py -v`
Expected: PASS pour les deux fichiers (Task 5 utilisait un mock ; la fonction réelle
livrée ici doit rester compatible avec l'appel fait dans `audio_global.generer`).

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/stockage.py briques/veille-info/test_stockage.py
git commit -m "feat(veille-info): stockage de l'audio global + journal des envois"
```

---

### Task 7: Envoi par email — `envoi_mail.py`

**Files:**
- Create: `briques/veille-info/envoi_mail.py`
- Test: `briques/veille-info/test_envoi_mail.py`

**Interfaces:**
- Consumes : rien de nouveau côté `veille-info` (appelle la brique Mail via HTTP).
- Produces : `envoyer(user_id: str, destinataire: str, lien: str, sujet: str | None,
  message: str | None) -> None`, `EnvoiAudioGlobalError` — utilisés par Task 8.

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `briques/veille-info/test_envoi_mail.py` :

```python
"""Tests de envoi_mail (S199) : appel à la brique Mail (mail_composer + brouillon/envoyer),
motif de digest.py::_pousser_memoire. httpx est mocké, aucun réseau réel."""
import httpx
import pytest

import envoi_mail


class _FausseReponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erreur", request=None, response=self)

    def json(self):
        return self._json


def test_envoyer_compose_puis_envoie_le_brouillon(monkeypatch):
    appels = []

    def _faux_post(url, json=None, headers=None, timeout=None):
        appels.append((url, json, headers))
        if url.endswith("/mail/composer"):
            return _FausseReponse({"ok": True, "brouillon": {"id": "brouillon-1"}})
        if url.endswith("/brouillons/brouillon-1/envoyer"):
            return _FausseReponse({"ok": True, "mode": "reel"})
        raise AssertionError(f"URL inattendue : {url}")

    monkeypatch.setattr(envoi_mail.httpx, "post", _faux_post)

    envoi_mail.envoyer("perso:alice", "equipe@example.com",
                       "https://veille-info.example/audio-global/jeton-x.mp3",
                       "Veille du jour", "Bonne écoute")

    assert len(appels) == 2
    url_compose, body_compose, entetes = appels[0]
    assert url_compose.endswith("/mail/composer")
    assert body_compose["a"] == "equipe@example.com"
    assert "https://veille-info.example/audio-global/jeton-x.mp3" in body_compose["dictee"]
    assert body_compose["sujet"] == "Veille du jour"
    assert entetes["X-User-Id"] == "alice"  # préfixe perso: retiré (motif _pousser_memoire)


def test_envoyer_sujet_et_message_par_defaut(monkeypatch):
    appels = []

    def _faux_post(url, json=None, headers=None, timeout=None):
        appels.append((url, json))
        if url.endswith("/mail/composer"):
            return _FausseReponse({"ok": True, "brouillon": {"id": "brouillon-2"}})
        return _FausseReponse({"ok": True})

    monkeypatch.setattr(envoi_mail.httpx, "post", _faux_post)

    envoi_mail.envoyer("perso:bob", "solo@example.com", "https://x.example/a.mp3", None, None)

    body_compose = appels[0][1]
    assert body_compose["sujet"] == "Veille audio"
    assert "Voici la veille audio du jour." in body_compose["dictee"]


def test_envoyer_echec_reseau_leve_erreur_explicite(monkeypatch):
    def _faux_post(url, json=None, headers=None, timeout=None):
        raise httpx.ConnectError("injoignable", request=None)

    monkeypatch.setattr(envoi_mail.httpx, "post", _faux_post)

    with pytest.raises(envoi_mail.EnvoiAudioGlobalError):
        envoi_mail.envoyer("perso:carol", "x@example.com", "https://x.example/a.mp3", None, None)
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/veille-info && python -m pytest test_envoi_mail.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'envoi_mail'`.

- [ ] **Step 3: Écrire le module**

Créer `briques/veille-info/envoi_mail.py` :

```python
"""Envoi de l'audio global par email via la brique Mail (S199). Motif d'appel identique à
digest.py::_pousser_memoire (S193) : `user_id` est le tenant interne (`f"perso:{x}"`), on
retire le préfixe avant de le transmettre en X-User-Id à Mail, qui recompose le même
tenant `perso:{x}` de son côté via son propre dialecte Cœur (`tenant_actuel`)."""
from __future__ import annotations

import os

import httpx

MAIL_URL = os.getenv("MAIL_URL", "http://host.docker.internal:6030")
MAIL_KEY = os.getenv("MAIL_KEY", "")


class EnvoiAudioGlobalError(Exception):
    """Échec d'un envoi (réseau, brouillon non composé, envoi refusé)."""


def envoyer(user_id: str, destinataire: str, lien: str, sujet: str | None,
           message: str | None) -> None:
    identite = user_id.removeprefix("perso:")
    entetes = {"X-User-Id": identite}
    if MAIL_KEY:
        entetes["X-API-Key"] = MAIL_KEY
    corps_dicte = (message or "Voici la veille audio du jour.") + f"\n\nÉcouter : {lien}"
    try:
        r = httpx.post(f"{MAIL_URL}/mail/composer",
                       json={"a": destinataire, "dictee": corps_dicte,
                             "sujet": sujet or "Veille audio"},
                       headers=entetes, timeout=30)
        r.raise_for_status()
        brouillon_id = r.json()["brouillon"]["id"]
        r2 = httpx.post(f"{MAIL_URL}/brouillons/{brouillon_id}/envoyer",
                        headers=entetes, timeout=30)
        r2.raise_for_status()
    except httpx.HTTPError as e:
        raise EnvoiAudioGlobalError(f"Envoi mail impossible ({destinataire}) : {e}") from e
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `cd briques/veille-info && python -m pytest test_envoi_mail.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/envoi_mail.py briques/veille-info/test_envoi_mail.py
git commit -m "feat(veille-info): envoi de l'audio global par email (brique Mail)"
```

---

### Task 8: Endpoints `/audio-global/*`

**Files:**
- Modify: `briques/veille-info/main.py` (imports, modèles, routes)
- Test: `briques/veille-info/test_main.py`

**Interfaces:**
- Consumes : `audio_global.generer(tenant, ordre) -> dict`, `audio_global.AudioGlobalError`
  (Task 5) ; `envoi_mail.envoyer(tenant, dest, lien, sujet, message) -> None`,
  `envoi_mail.EnvoiAudioGlobalError` (Task 7) ; `stockage.audio_global_par_jeton`,
  `stockage.audio_global_get`, `stockage.lister_audio_global`,
  `stockage.inserer_envoi_audio_global` (Task 6).
- Produces : `POST /audio-global/generer`, `GET /audio-global`, `GET
  /audio-global/{jeton}.mp3`, `POST /audio-global/{audio_id}/envoyer`, `POST
  /audio-global/generer-et-envoyer` — consommés par Task 9 (manifest) et Task 10 (UI).

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à la fin de `briques/veille-info/test_main.py` :

```python
def test_generer_audio_global_digest_sans_audio_422(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    d = stockage.inserer_digest("perso:main-audioglobal-1", "Résumé.", 1, thematique="Tech")
    r = client.post("/audio-global/generer", headers=_entetes("main-audioglobal-1"),
                    json={"ordre_thematiques": [d["id"]]})
    assert r.status_code == 422


def test_generer_audio_global_appelle_le_module(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    appele = {}
    def _faux_generer(user_id, ordre):
        appele["user_id"] = user_id
        appele["ordre"] = ordre
        return {"id": 1, "user_id": user_id, "jeton": "jeton-test", "ordre_thematiques": ordre,
                "fichier_path": "/data/audio-global/jeton-test.mp3", "duree_secondes": 12.0,
                "expire_le": "2099-01-01T00:00:00+00:00", "cree_le": "2026-07-26T00:00:00"}
    monkeypatch.setattr(main.audio_global, "generer", _faux_generer)

    r = client.post("/audio-global/generer", headers=_entetes("main-audioglobal-2"),
                    json={"ordre_thematiques": [1, 2]})
    assert r.status_code == 200
    assert r.json()["jeton"] == "jeton-test"
    assert appele["user_id"] == "perso:main-audioglobal-2"
    assert appele["ordre"] == [1, 2]


def test_telecharger_audio_global_expire_404(monkeypatch, tmp_path):
    fichier = tmp_path / "expire.mp3"
    fichier.write_bytes(b"faux-mp3")
    stockage.inserer_audio_global("perso:main-audioglobal-3", "jeton-expire", [1],
                                  str(fichier), 5.0, "2020-01-01T00:00:00+00:00")
    r = client.get("/audio-global/jeton-expire.mp3")
    assert r.status_code == 404


def test_telecharger_audio_global_valide_sert_le_fichier(tmp_path):
    fichier = tmp_path / "valide.mp3"
    fichier.write_bytes(b"faux-contenu-mp3")
    stockage.inserer_audio_global("perso:main-audioglobal-4", "jeton-valide", [1],
                                  str(fichier), 5.0, "2099-01-01T00:00:00+00:00")
    r = client.get("/audio-global/jeton-valide.mp3")
    assert r.status_code == 200
    assert r.content == b"faux-contenu-mp3"


def test_envoyer_audio_global_journalise_resultat_par_destinataire(monkeypatch, tmp_path):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    fichier = tmp_path / "envoi.mp3"
    fichier.write_bytes(b"x")
    a = stockage.inserer_audio_global("perso:main-audioglobal-5", "jeton-envoi", [1],
                                      str(fichier), 5.0, "2099-01-01T00:00:00+00:00")

    def _faux_envoyer(user_id, dest, lien, sujet, message):
        if dest == "echoue@example.com":
            raise main.envoi_mail.EnvoiAudioGlobalError("boom")
    monkeypatch.setattr(main.envoi_mail, "envoyer", _faux_envoyer)

    r = client.post(f"/audio-global/{a['id']}/envoyer", headers=_entetes("main-audioglobal-5"),
                    json={"destinataires": ["ok@example.com", "echoue@example.com"]})
    assert r.status_code == 200
    j = r.json()
    par_dest = {x["destinataire"]: x["ok"] for x in j["resultats"]}
    assert par_dest["ok@example.com"] is True
    assert par_dest["echoue@example.com"] is False


def test_envoyer_audio_global_introuvable_404(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    r = client.post("/audio-global/999999/envoyer", headers=_entetes("main-audioglobal-6"),
                    json={"destinataires": ["x@example.com"]})
    assert r.status_code == 404
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/veille-info && python -m pytest test_main.py -k audio_global -v`
Expected: FAIL — 404 sur toutes les routes `/audio-global/*` (inexistantes).

- [ ] **Step 3: Ajouter les imports, modèles et routes**

Dans `briques/veille-info/main.py`, remplacer le bloc d'imports (lignes 8-19) par :

```python
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import audio_global
import digest
import envoi_mail
import stockage
```

Ajouter, juste après `lire_digest_route` (après la ligne 106, avant la route
`/digest/executer`) :

```python
class GenererAudioGlobal(BaseModel):
    ordre_thematiques: list[int] = Field(min_length=1)


class EnvoyerAudioGlobal(BaseModel):
    destinataires: list[str] = Field(min_length=1)
    sujet: str | None = None
    message: str | None = None


class GenererEtEnvoyerAudioGlobal(BaseModel):
    ordre_thematiques: list[int] = Field(min_length=1)
    destinataires: list[str] = Field(min_length=1)
    sujet: str | None = None
    message: str | None = None


@app.post("/audio-global/generer", tags=["audio-global"])
def generer_audio_global_route(body: GenererAudioGlobal, tenant: str = Depends(tenant_actuel)):
    try:
        return audio_global.generer(tenant, body.ordre_thematiques)
    except audio_global.AudioGlobalError as e:
        raise HTTPException(422, str(e))


@app.get("/audio-global", tags=["audio-global"])
def lister_audio_global_route(tenant: str = Depends(tenant_actuel)):
    return stockage.lister_audio_global(tenant)


@app.get("/audio-global/{jeton}.mp3", tags=["audio-global"], include_in_schema=False)
def telecharger_audio_global_route(jeton: str):
    a = stockage.audio_global_par_jeton(jeton)
    if a is None:
        raise HTTPException(404, "Audio introuvable.")
    if datetime.fromisoformat(a["expire_le"]) <= datetime.now(timezone.utc):
        raise HTTPException(404, "Ce lien a expiré.")
    return FileResponse(a["fichier_path"], media_type="audio/mpeg")


def _envoyer_audio_global(tenant: str, audio_id: int, destinataires: list[str],
                          sujet: str | None, message: str | None, base_url: str) -> dict:
    a = stockage.audio_global_get(tenant, audio_id)
    if a is None:
        raise HTTPException(404, "Audio introuvable.")
    base = os.getenv("VEILLE_INFO_PUBLIC_URL", "").rstrip("/") or base_url.rstrip("/")
    lien = f"{base}/audio-global/{a['jeton']}.mp3"
    resultats = []
    for dest in destinataires:
        try:
            envoi_mail.envoyer(tenant, dest, lien, sujet, message)
            stockage.inserer_envoi_audio_global(audio_id, dest, "envoye", None)
            resultats.append({"destinataire": dest, "ok": True})
        except envoi_mail.EnvoiAudioGlobalError as e:  # noqa: BLE001 — un échec par destinataire
            stockage.inserer_envoi_audio_global(audio_id, dest, "echec", str(e))
            resultats.append({"destinataire": dest, "ok": False, "erreur": str(e)})
    return {"resultats": resultats}


@app.post("/audio-global/{audio_id}/envoyer", tags=["audio-global"])
def envoyer_audio_global_route(audio_id: int, body: EnvoyerAudioGlobal, request: Request,
                               tenant: str = Depends(tenant_actuel)):
    return _envoyer_audio_global(tenant, audio_id, body.destinataires, body.sujet,
                                 body.message, str(request.base_url))


@app.post("/audio-global/generer-et-envoyer", tags=["audio-global"])
def generer_et_envoyer_audio_global_route(body: GenererEtEnvoyerAudioGlobal, request: Request,
                                          tenant: str = Depends(tenant_actuel)):
    try:
        audio = audio_global.generer(tenant, body.ordre_thematiques)
    except audio_global.AudioGlobalError as e:
        raise HTTPException(422, str(e))
    envoi = _envoyer_audio_global(tenant, audio["id"], body.destinataires, body.sujet,
                                  body.message, str(request.base_url))
    return {**audio, "envoi": envoi}
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `cd briques/veille-info && python -m pytest test_main.py -v`
Expected: PASS.

- [ ] **Step 5: Lancer TOUTE la suite de la brique**

Run: `cd briques/veille-info && python -m pytest -v`
Expected: PASS (toutes les tâches précédentes incluses).

- [ ] **Step 6: Commit**

```bash
git add briques/veille-info/main.py briques/veille-info/test_main.py
git commit -m "feat(veille-info): endpoints /audio-global (générer, lister, télécharger, envoyer)"
```

---

### Task 9: Manifest — 3 capacités assistant

**Files:**
- Modify: `briques/veille-info/manifest.json`
- Test: `briques/veille-info/test_manifest_capacites.py` (si ce fichier existe déjà avec
  un motif de validation générique du manifest — sinon cette étape reste une vérification
  manuelle du JSON)

**Interfaces:**
- Consumes : les endpoints de Task 8.
- Produces : capacités assistant `veille_audio_global_generer`,
  `veille_audio_global_envoyer`, `veille_audio_global_generer_et_envoyer`.

- [ ] **Step 1: Vérifier s'il existe un test générique de validation du manifest**

Run: `ls /Users/garinat_t/Desktop/Workplace/briques/*/test_manifest*.py 2>/dev/null | head -3`

S'il existe un tel fichier dans une AUTRE brique (motif à suivre), l'adapter tel quel dans
`briques/veille-info/` ; sinon, passer directement à l'étape 2 (le JSON est vérifié par
lecture, pas de test automatisé requis pour un fichier de configuration statique dans ce
repo).

- [ ] **Step 2: Ajouter les 3 capacités**

Dans `briques/veille-info/manifest.json`, remplacer le tableau `"capacites"` (dernier
élément se termine ligne 86, juste avant `]`) en ajoutant après `veille_info_digest_lire` :

```json
    },
    {
      "nom": "veille_audio_global_generer",
      "description": "Génère un audio unique concaténant plusieurs digests DÉJÀ audio-générés, dans un ordre choisi, avec un interlude parlé annonçant chaque thématique (« Voici les nouvelles pour la veille tech »). Chaque digest doit déjà avoir son audio (vérifier via veille_info_digests_lister). Sert « fais-moi un audio récapitulatif de mes veilles tech et cosmétique ».",
      "methode": "POST",
      "chemin": "/audio-global/generer",
      "params": {
        "ordre_thematiques": {"type": "array", "description": "Liste ordonnée des identifiants de digest (champ id de veille_info_digests_lister) à concaténer, dans l'ordre d'écoute souhaité.", "requis": true}
      },
      "action": true,
      "niveau": 1,
      "socle": false
    },
    {
      "nom": "veille_audio_global_envoyer",
      "description": "Envoie par email un audio global déjà généré (via veille_audio_global_generer), sous forme d'un lien d'écoute valable 7 jours. Sert « envoie cet audio à mon équipe ».",
      "methode": "POST",
      "chemin": "/audio-global/{audio_id}/envoyer",
      "params": {
        "audio_id": {"type": "integer", "description": "Identifiant de l'audio global (renvoyé par veille_audio_global_generer).", "requis": true},
        "destinataires": {"type": "array", "description": "Liste d'adresses email destinataires.", "requis": true},
        "sujet": {"type": "string", "description": "Objet de l'email (optionnel, défaut « Veille audio »)."},
        "message": {"type": "string", "description": "Message d'accompagnement (optionnel)."}
      },
      "action": true,
      "niveau": 1,
      "socle": false
    },
    {
      "nom": "veille_audio_global_generer_et_envoyer",
      "description": "Enchaîne génération ET envoi d'un audio global en un seul appel : génère l'audio à partir des digests choisis, puis l'envoie par email. Sert « génère l'audio de ma veille et envoie-le à mon équipe ».",
      "methode": "POST",
      "chemin": "/audio-global/generer-et-envoyer",
      "params": {
        "ordre_thematiques": {"type": "array", "description": "Liste ordonnée des identifiants de digest à concaténer.", "requis": true},
        "destinataires": {"type": "array", "description": "Liste d'adresses email destinataires.", "requis": true},
        "sujet": {"type": "string", "description": "Objet de l'email (optionnel)."},
        "message": {"type": "string", "description": "Message d'accompagnement (optionnel)."}
      },
      "action": true,
      "niveau": 1,
      "socle": false
    }
  ]
}
```

- [ ] **Step 3: Valider le JSON**

Run: `python -c "import json; json.load(open('briques/veille-info/manifest.json'))" && echo OK`
Expected: `OK` (pas d'erreur de parsing).

- [ ] **Step 4: Commit**

```bash
git add briques/veille-info/manifest.json
git commit -m "feat(veille-info): expose l'audio global (générer/envoyer) à l'assistant"
```

---

### Task 10: UI `atelier-veille` — thématique sur les sources + onglet « Audio global »

**Files:**
- Modify: `briques/atelier-veille/main.py` (proxy routes), `briques/atelier-veille/front.html`
  (formulaire source, liste digests, nouvel onglet)

**Interfaces:**
- Consumes : `/veille/sources` (POST accepte `thematique`), nouveau `PATCH
  /veille/sources/{id}/thematique`, `/veille/digests` (renvoie désormais `thematique` par
  digest), nouveaux `POST /veille/audio-global/generer`, `GET /veille/audio-global`, `POST
  /veille/audio-global/{id}/envoyer` (tous proxifiés vers `veille-info`, motif des routes
  existantes `main.py:111-190`).
- Produces : rien consommé par une tâche suivante (dernière tâche du plan).

- [ ] **Step 1: Ajouter les routes proxy dans `atelier-veille/main.py`**

Dans `briques/atelier-veille/main.py`, ajouter juste après la route `@app.post("/veille/digest/executer"...)` (fin de fichier, après la ligne 190) :

```python
@app.patch("/veille/sources/{source_id}/thematique", tags=["veille"])
async def veille_retagger_source(source_id: int, request: Request):
    corps = await request.json()
    entetes = {"X-API-Key": VEILLE_INFO_KEY, "X-User-Id": _x_user_id(request)} if VEILLE_INFO_KEY else {}
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.patch(f"{VEILLE_INFO_URL}/sources/{source_id}/thematique",
                              headers=entetes, json=corps)
        except httpx.HTTPError as e:
            raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@app.post("/veille/audio-global/generer", tags=["veille"])
async def veille_generer_audio_global(request: Request):
    corps = await request.json()
    entetes = {"X-API-Key": VEILLE_INFO_KEY, "X-User-Id": _x_user_id(request)} if VEILLE_INFO_KEY else {}
    async with httpx.AsyncClient(timeout=300) as c:
        try:
            r = await c.post(f"{VEILLE_INFO_URL}/audio-global/generer", headers=entetes, json=corps)
        except httpx.HTTPError as e:
            raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@app.get("/veille/audio-global", tags=["veille"])
async def veille_lister_audio_global(request: Request):
    entetes = {"X-API-Key": VEILLE_INFO_KEY, "X-User-Id": _x_user_id(request)} if VEILLE_INFO_KEY else {}
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.get(f"{VEILLE_INFO_URL}/audio-global", headers=entetes)
        except httpx.HTTPError as e:
            raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@app.post("/veille/audio-global/{audio_id}/envoyer", tags=["veille"])
async def veille_envoyer_audio_global(audio_id: int, request: Request):
    corps = await request.json()
    entetes = {"X-API-Key": VEILLE_INFO_KEY, "X-User-Id": _x_user_id(request)} if VEILLE_INFO_KEY else {}
    async with httpx.AsyncClient(timeout=60) as c:
        try:
            r = await c.post(f"{VEILLE_INFO_URL}/audio-global/{audio_id}/envoyer",
                             headers=entetes, json=corps)
        except httpx.HTTPError as e:
            raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()
```

> **Note :** ce step suppose l'existence d'un helper `_x_user_id(request)` et d'une
> constante `VEILLE_INFO_KEY` dans `atelier-veille/main.py`, sur le motif des routes
> existantes (`main.py:111-190` transmettent déjà des en-têtes vers `VEILLE_INFO_URL`).
> **Avant d'écrire ce step**, lire les 30 lignes précédant la route `/veille/sources`
> existante (`main.py:100-117`) pour reprendre EXACTEMENT le nom des variables déjà
> utilisées par ce fichier (le nom peut différer de `_x_user_id`/`VEILLE_INFO_KEY` selon
> la convention réelle du fichier) et ajuster les 4 nouvelles routes en conséquence avant
> de les coller.

- [ ] **Step 2: Ajouter le champ Thématique au formulaire d'ajout de source**

Dans `briques/atelier-veille/front.html`, remplacer (ligne 50-56) :

```html
    <h3 style="margin-top:20px">Ajouter une source</h3>
    <div style="display:flex;gap:10px;flex-wrap:wrap">
      <input id="nouvelle-source-nom" placeholder="Nom (ex. Le Monde Tech)" style="flex:1;min-width:180px;padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)">
      <input id="nouvelle-source-url" placeholder="URL du flux RSS" style="flex:2;min-width:220px;padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)">
      <button onclick="ajouterSource()" style="padding:8px 16px;border-radius:8px;border:none;background:var(--accent);color:#0b1622;font-weight:600;cursor:pointer">Ajouter</button>
    </div>
    <div id="erreur-sources" style="color:var(--bad);margin-top:8px;font-size:.85rem"></div>
```

par :

```html
    <h3 style="margin-top:20px">Ajouter une source</h3>
    <div style="display:flex;gap:10px;flex-wrap:wrap">
      <input id="nouvelle-source-nom" placeholder="Nom (ex. Le Monde Tech)" style="flex:1;min-width:180px;padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)">
      <input id="nouvelle-source-url" placeholder="URL du flux RSS" style="flex:2;min-width:220px;padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)">
      <input id="nouvelle-source-thematique" placeholder="Thématique (ex. Tech) — optionnel" style="flex:1;min-width:160px;padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)">
      <button onclick="ajouterSource()" style="padding:8px 16px;border-radius:8px;border:none;background:var(--accent);color:#0b1622;font-weight:600;cursor:pointer">Ajouter</button>
    </div>
    <p style="color:var(--mut);font-size:.8rem;margin-top:6px">La thématique regroupe les sources : un digest audio séparé est généré par thématique chaque jour.</p>
    <div id="erreur-sources" style="color:var(--bad);margin-top:8px;font-size:.85rem"></div>
```

Remplacer la fonction `ajouterSource` (ligne 116-134) par :

```javascript
async function ajouterSource() {
  const nom = document.getElementById('nouvelle-source-nom').value.trim();
  const url = document.getElementById('nouvelle-source-url').value.trim();
  const thematique = document.getElementById('nouvelle-source-thematique').value.trim();
  const erreur = document.getElementById('erreur-sources');
  erreur.textContent = '';
  if (!nom || !url) { erreur.textContent = 'Nom et URL requis.'; return; }
  try {
    const r = await fetch('/veille/sources', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({nom, url, thematique})
    });
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    document.getElementById('nouvelle-source-nom').value = '';
    document.getElementById('nouvelle-source-url').value = '';
    document.getElementById('nouvelle-source-thematique').value = '';
    chargerSources();
  } catch (e) {
    erreur.textContent = String(e.message || e);
  }
}
```

Remplacer `chargerSources` (ligne 98-114) pour afficher la thématique :

```javascript
async function chargerSources() {
  const cible = document.getElementById('liste-sources');
  const erreur = document.getElementById('erreur-sources');
  erreur.textContent = '';
  try {
    const r = await fetch('/veille/sources');
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    const sources = await r.json();
    cible.innerHTML = sources.length ? sources.map(s => `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)">
        <div><b>${esc(s.nom)}</b> ${s.thematique ? `<span style="color:var(--accent);font-size:.75rem">· ${esc(s.thematique)}</span>` : ''}<br><span style="color:var(--mut);font-size:.8rem">${esc(s.url)}</span></div>
        <button onclick="supprimerSource(${s.id})" style="border:1px solid var(--bad);background:transparent;color:var(--bad);border-radius:8px;padding:5px 10px;cursor:pointer">Retirer</button>
      </div>`).join('') : '<p style="color:var(--mut)">Aucune source suivie pour l\'instant.</p>';
  } catch (e) {
    erreur.textContent = String(e.message || e);
  }
}
```

- [ ] **Step 3: Grouper l'affichage des digests par thématique**

Dans `briques/atelier-veille/front.html`, remplacer `chargerDigests` (ligne 148-165) par :

```javascript
async function chargerDigests() {
  const cible = document.getElementById('liste-digests');
  const erreur = document.getElementById('erreur-digests');
  erreur.textContent = '';
  try {
    const r = await fetch('/veille/digests');
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    const digests = await r.json();
    if (!digests.length) { cible.innerHTML = '<p style="color:var(--mut)">Aucun digest généré pour l\'instant.</p>'; return; }
    const groupes = {};
    digests.forEach(d => { const t = d.thematique || 'Général'; (groupes[t] = groupes[t] || []).push(d); });
    cible.innerHTML = Object.keys(groupes).sort().map(t => `
      <h4 style="margin:16px 0 6px;color:var(--accent)">${esc(t)}</h4>
      ${groupes[t].map(d => `
        <div style="padding:12px 0;border-bottom:1px solid var(--line)">
          <b>${esc(d.date)}</b> <span style="color:var(--mut);font-size:.8rem">(${d.nb_articles} article${d.nb_articles > 1 ? 's' : ''})</span>
          <p style="margin:6px 0">${esc(d.texte_resume)}</p>
          ${d.audio_url ? `<audio controls src="${esc(d.audio_url)}"></audio>` : '<span style="color:var(--mut);font-size:.8rem">Pas encore de version audio.</span>'}
        </div>`).join('')}`).join('');
  } catch (e) {
    erreur.textContent = String(e.message || e);
  }
}
```

- [ ] **Step 4: Ajouter l'onglet « Audio global »**

Dans `briques/atelier-veille/front.html`, remplacer le bouton de navigation (ligne 36-37) :

```html
<button id="btn-digests" class="actif" onclick="ouvrirOnglet('digests')">Digests</button>
<button id="btn-sources" onclick="ouvrirOnglet('sources')">Sources RSS</button>
```

par :

```html
<button id="btn-digests" class="actif" onclick="ouvrirOnglet('digests')">Digests</button>
<button id="btn-sources" onclick="ouvrirOnglet('sources')">Sources RSS</button>
<button id="btn-audioglobal" onclick="ouvrirOnglet('audioglobal')">Audio global</button>
```

Ajouter, juste après la fermeture du bloc `<div id="vue-digests" ...>` (après la ligne 69) :

```html
  <div id="vue-audioglobal" class="vue panel">
    <h3>Audio global</h3>
    <p style="color:var(--mut);font-size:.82rem">Concatène plusieurs digests (déjà audio-générés) dans l'ordre choisi, avec un interlude parlé entre chaque thématique.</p>
    <div id="choix-digests"></div>
    <div class="row" style="margin-top:10px">
      <button id="btn-generer-audioglobal" onclick="genererAudioGlobal()" style="padding:8px 16px;border-radius:8px;border:1px solid var(--accent);background:transparent;color:var(--accent);font-weight:600;cursor:pointer">Générer l'audio</button>
    </div>
    <div id="erreur-audioglobal" style="color:var(--bad);margin-top:8px;font-size:.85rem"></div>
    <div id="lecteur-audioglobal" style="margin-top:12px"></div>

    <h3 style="margin-top:24px">Historique</h3>
    <div id="historique-audioglobal"></div>
  </div>
```

Remplacer le bloc `<script>` final (juste avant `chargerConfig(); chargerDigests();` en fin
de fichier, ligne 183-184) — ajouter avant ces deux appels :

```javascript
let DIGESTS_DISPONIBLES = [];
let ORDRE_CHOISI = [];

async function chargerChoixDigests() {
  const box = document.getElementById('choix-digests');
  try {
    const r = await fetch('/veille/digests');
    const digests = await r.json();
    DIGESTS_DISPONIBLES = digests.filter(d => d.audio_url);
    if (!DIGESTS_DISPONIBLES.length) {
      box.innerHTML = '<p style="color:var(--mut)">Aucun digest avec audio pour l\'instant — génère d\'abord des digests (onglet Digests).</p>';
      return;
    }
    box.innerHTML = DIGESTS_DISPONIBLES.map(d => `
      <label style="display:flex;align-items:center;gap:8px;padding:4px 0">
        <input type="checkbox" value="${d.id}" onchange="toggleDigestChoisi(${d.id}, this.checked)">
        <span><b>${esc(d.thematique || 'Général')}</b> — ${esc(d.date)}</span>
      </label>`).join('');
  } catch (e) {
    box.innerHTML = '<p style="color:var(--bad)">' + esc(e.message || e) + '</p>';
  }
}

function toggleDigestChoisi(id, coche) {
  if (coche) { if (!ORDRE_CHOISI.includes(id)) ORDRE_CHOISI.push(id); }
  else { ORDRE_CHOISI = ORDRE_CHOISI.filter(x => x !== id); }
}

async function genererAudioGlobal() {
  const erreur = document.getElementById('erreur-audioglobal');
  const bouton = document.getElementById('btn-generer-audioglobal');
  erreur.textContent = '';
  if (!ORDRE_CHOISI.length) { erreur.textContent = 'Choisis au moins un digest.'; return; }
  bouton.disabled = true;
  try {
    const r = await fetch('/veille/audio-global/generer', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ordre_thematiques: ORDRE_CHOISI})
    });
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    const audio = await r.json();
    document.getElementById('lecteur-audioglobal').innerHTML = `
      <audio controls src="/veille/audio-global/${audio.jeton}.mp3" style="width:100%"></audio>
      <div class="row" style="margin-top:8px;gap:8px">
        <input id="destinataires-audioglobal" placeholder="Destinataires (séparés par des virgules)" style="flex:2;padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)">
        <input id="sujet-audioglobal" placeholder="Sujet (optionnel)" style="flex:1;padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)">
        <button onclick="envoyerAudioGlobal(${audio.id})" style="padding:8px 16px;border-radius:8px;border:none;background:var(--accent);color:#0b1622;font-weight:600;cursor:pointer">Envoyer par email</button>
      </div>
      <div id="resultat-envoi-audioglobal" style="margin-top:6px;font-size:.85rem"></div>`;
    await chargerHistoriqueAudioGlobal();
  } catch (e) {
    erreur.textContent = String(e.message || e);
  } finally {
    bouton.disabled = false;
  }
}

async function envoyerAudioGlobal(audioId) {
  const dest = document.getElementById('destinataires-audioglobal').value
    .split(',').map(s => s.trim()).filter(Boolean);
  const sujet = document.getElementById('sujet-audioglobal').value.trim();
  const resultat = document.getElementById('resultat-envoi-audioglobal');
  if (!dest.length) { resultat.textContent = 'Indique au moins un destinataire.'; return; }
  resultat.textContent = 'Envoi…';
  try {
    const r = await fetch(`/veille/audio-global/${audioId}/envoyer`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({destinataires: dest, sujet: sujet || undefined})
    });
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    const j = await r.json();
    const echecs = j.resultats.filter(x => !x.ok);
    resultat.textContent = echecs.length
      ? `${j.resultats.length - echecs.length} envoyé(s), ${echecs.length} échec(s).`
      : `${j.resultats.length} envoyé(s) ✓`;
    await chargerHistoriqueAudioGlobal();
  } catch (e) {
    resultat.textContent = String(e.message || e);
  }
}

async function chargerHistoriqueAudioGlobal() {
  const box = document.getElementById('historique-audioglobal');
  try {
    const r = await fetch('/veille/audio-global');
    const liste = await r.json();
    box.innerHTML = liste.length ? liste.map(a => `
      <div style="padding:8px 0;border-bottom:1px solid var(--line);font-size:.85rem">
        <b>${esc(a.cree_le.slice(0, 10))}</b> — ${a.ordre_thematiques.length} digest(s)
        <audio controls src="/veille/audio-global/${a.jeton}.mp3" style="display:block;margin-top:4px;width:100%"></audio>
      </div>`).join('') : '<p style="color:var(--mut)">Aucun audio global généré pour l\'instant.</p>';
  } catch (e) {
    box.innerHTML = '<p style="color:var(--bad)">' + esc(e.message || e) + '</p>';
  }
}
```

Remplacer `ouvrirOnglet` (ligne 72-79) par :

```javascript
function ouvrirOnglet(nom) {
  for (const n of ['carte', 'sources', 'digests', 'audioglobal']) {
    document.getElementById('vue-' + n).classList.toggle('actif', n === nom);
    document.getElementById('btn-' + n).classList.toggle('actif', n === nom);
  }
  if (nom === 'sources') chargerSources();
  if (nom === 'digests') chargerDigests();
  if (nom === 'audioglobal') { chargerChoixDigests(); chargerHistoriqueAudioGlobal(); }
}
```

- [ ] **Step 5: Vérifier manuellement dans le navigateur**

Lancer `veille-info` (port 6120) et `atelier-veille` (port 6130) en local (voir
`docker-compose.yml` de chaque brique pour les variables d'environnement, ou `uvicorn
main:app --reload` avec `VEILLE_INFO_URL=http://localhost:6120` exporté pour
`atelier-veille`). Ajouter 2 sources avec des thématiques différentes (ex. « Tech » et
« Cosmétique »), déclencher un digest (bouton « Générer le digest maintenant »), vérifier
dans l'onglet Digests que les deux thématiques apparaissent séparément avec chacune son
audio. Aller dans l'onglet « Audio global », cocher les deux digests, cliquer « Générer
l'audio », vérifier que le lecteur audio joue bien interlude + digest1 + interlude +
digest2. Saisir une adresse email de test, cliquer « Envoyer par email », vérifier le
résultat affiché et l'entrée dans l'historique.

- [ ] **Step 6: Commit**

```bash
git add briques/atelier-veille/main.py briques/atelier-veille/front.html
git commit -m "feat(atelier-veille): thématique sur les sources + onglet Audio global"
```

## Self-Review

1. **Spec coverage** :
   - Digests par thématique (préalable ajouté au spec) → Tasks 1-3.
   - ffmpeg disponible → Task 4.
   - Génération concaténée + interludes → Task 5.
   - Stockage audio global + journal d'envois → Task 6.
   - Envoi via brique Mail existante → Task 7.
   - Endpoints (générer/lister/télécharger/envoyer/combiné) → Task 8.
   - 3 capacités assistant → Task 9.
   - UI (thématique sur sources, digests groupés, onglet Audio global) → Task 10.
   - Lien sans chiffrement E2E, jeton + expiration 7j → Task 5/6/8 (`_EXPIRATION_JOURS`,
     vérification à l'accès dans `telecharger_audio_global_route`).
   - Permissions « membres du workspace » → couvert par l'isolation `tenant_actuel`
     existante (aucun mécanisme séparé nécessaire, cf. spec « YAGNI ») — pas de tâche
     dédiée, déjà assuré par le fait que `tenant` scope toutes les requêtes.
   Tout couvert.
2. **Placeholder scan** : aucun TODO/TBD ; la seule note explicite (Task 10 Step 1) documente
   une dépendance à vérifier dans le code existant AVANT d'écrire le step, ce n'est pas un
   TODO du plan lui-même mais une instruction de lecture préalable — cohérent avec la
   contrainte « suivre les motifs existants » de writing-plans.
3. **Type consistency** : `ordre_digest_ids: list[int]` (Task 5 `generer`) ↔
   `ordre_thematiques: list[int]` (Task 8 `GenererAudioGlobal`, nommage conservé du spec
   malgré le contenu = digest_id, documenté dans le spec) ↔ `ordre_thematiques` colonne
   JSON stockée (Task 6) — cohérent bout en bout. `audio_global.generer(user_id, ordre) ->
   dict` avec clés `id/user_id/jeton/ordre_thematiques/fichier_path/duree_secondes/
   expire_le/cree_le` (Task 5/6) ↔ consommé identiquement dans Task 8 (`audio["id"]`,
   `a['jeton']`, `a["fichier_path"]`, `a["expire_le"]`). `envoi_mail.envoyer(user_id, dest,
   lien, sujet, message)` (Task 7) ↔ appelé avec les mêmes 5 arguments positionnels dans
   Task 8 `_envoyer_audio_global`.
