# Veille-info — consolidation des sources sous le compte réel de Toussaint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Regrouper, dans la base `veille-info` du HP, toutes les sources RSS existantes (actuellement éparpillées sur 3 tenants différents) sous le VRAI compte web de Toussaint (`perso:f6541180-6751-4cb0-9ac8-dcf3c6a3f08e`, son `sub` Keycloak), avec une `thematique` posée sur chacune.

**Architecture:** Script de migration Python **pur** (une fonction `migrer(conn) -> dict`, testable sans réseau ni Docker, contre une base SQLite en mémoire construite avec le VRAI schéma de `stockage.py`), exécuté une seule fois à la main sur le HP via `docker exec`. Pas de route API, pas de code applicatif permanent — c'est une opération ponctuelle sur des données constatées le 2026-07-27 (cf. mémoire `sprint-s199-audio-global-suppression-mail-personnages`).

**Tech Stack:** Python 3.12, `sqlite3` (stdlib), pytest.

## Global Constraints

- Cible de consolidation : `perso:f6541180-6751-4cb0-9ac8-dcf3c6a3f08e` (le VRAI compte web de Toussaint, confirmé par l'utilisateur — PAS `perso:Toussaint`, qui est un bucket distinct créé hors du parcours Keycloak).
- État constaté en prod (HP, `docker exec workplace_veille_info`, `/data/veille_info.db`) au 2026-07-27, table `sources` :
  - `perso:Toussaint` (5 lignes, à absorber) : id 12 CosmeticOBS, id 13 COSMED, id 14 Annel - Blog Réglementaire, id 15 Care Europe - Blog, id 16 Commission Européenne - Cosmétiques.
  - `public` (1 ligne, à absorber) : id 8 TechCrunch AI.
  - `perso:f6541180-6751-4cb0-9ac8-dcf3c6a3f08e` (9 lignes déjà en place, thematique='' à poser) : id 2, 3, 4, 5, 6, 7, 9, 10, 11.
- **Ne PAS toucher aux tables `articles`, `digests`, `digest_audio`, `veille_audio_global`, `veille_audio_global_envois`** — seule la table `sources` est modifiée. L'historique des anciens digests sous `public`/`perso:Toussaint` (4 digests constatés sous `public`, dates 2026-07-23 à 2026-07-26) reste orphelin mais inoffensif (pas de FK depuis `sources` vers `digests`) ; les prochains digests générés par le pipeline seront correctement rattachés au bon tenant + thématique puisque les SOURCES pointeront désormais vers `perso:f6541180-...`.
- Le script doit être **idempotent** : le relancer une deuxième fois ne doit RIEN casser (les `UPDATE ... WHERE` ciblent des états précis qui ne matchent plus après la première exécution → 0 ligne affectée, pas d'erreur).
- Le script doit supporter un mode `--dry-run` (affiche ce qui SERAIT fait, ROLLBACK au lieu de COMMIT) — passage obligatoire avant l'exécution réelle sur le HP.

---

## File Structure

- Create: `briques/veille-info/scripts/__init__.py` — package vide (le dossier `scripts/` n'existe pas encore).
- Create: `briques/veille-info/scripts/migration_20260727_consolidation_toussaint.py` — logique de migration + CLI.
- Test: `briques/veille-info/scripts/test_migration_20260727_consolidation_toussaint.py`

---

### Task 1: Fonction de migration pure + tests

**Files:**
- Create: `briques/veille-info/scripts/__init__.py`
- Create: `briques/veille-info/scripts/migration_20260727_consolidation_toussaint.py`
- Test: `briques/veille-info/scripts/test_migration_20260727_consolidation_toussaint.py`

**Interfaces:**
- Consumes: `stockage.init()` / `stockage._SCHEMA` (existant, `briques/veille-info/stockage.py`) pour construire une base de test avec le VRAI schéma.
- Produces: `migrer(conn: sqlite3.Connection, *, dry_run: bool = False) -> dict` — renvoie `{"cosmetique_migrees": int, "techcrunch_migree": int, "ia_retaguees": int}`. Ne commite ni ne rollback elle-même (laisse l'appelant décider) — la CLI (Step 5) gère la transaction.

- [ ] **Step 1: Créer le package**

```bash
mkdir -p briques/veille-info/scripts
touch briques/veille-info/scripts/__init__.py
```

- [ ] **Step 2: Écrire le test qui échoue**

Créer `briques/veille-info/scripts/test_migration_20260727_consolidation_toussaint.py` :

```python
"""Migration ponctuelle (2026-07-27) : consolide les sources RSS éparpillées sur 3
tenants (perso:Toussaint, public, perso:<uuid>) sous le VRAI compte web de Toussaint.
État constaté en prod documenté dans le docstring du module de migration lui-même."""
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import stockage  # noqa: E402

from migration_20260727_consolidation_toussaint import CIBLE, migrer  # noqa: E402

AUTRE_UUID = CIBLE  # alias lisible dans les assertions ci-dessous


def _db_avec_etat_constate() -> sqlite3.Connection:
    """Reproduit l'état EXACT constaté en prod le 2026-07-27 (ids, tenants, thématiques)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(stockage._SCHEMA)
    lignes = [
        (2, CIBLE, "OpenAI News", "https://openai.com/news/rss.xml", ""),
        (3, CIBLE, "Google AI Blog", "https://blog.google/innovation-and-ai/technology/ai/rss/", ""),
        (4, CIBLE, "Mistral AI Blog", "https://mistral.ai/rss.xml", ""),
        (5, CIBLE, "Anthropic News", "https://www.anthropic.com/news", ""),
        (6, CIBLE, "Qwen Blog", "https://qwenlm.github.io/blog/", ""),
        (7, CIBLE, "Zhipu AI (GLM) Blog", "https://zhipuai.ai/blog/", ""),
        (8, "public", "TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", ""),
        (9, CIBLE, "Renaud Dékode (Substack)", "https://renauddekode.substack.com/feed", ""),
        (10, CIBLE, "Planet AI (agrégateur IA)", "https://planet-ai.net/ai-rss-feed.html", ""),
        (11, CIBLE, "Google DeepMind Blog", "https://deepmind.google/blog/rss.xml", ""),
        (12, "perso:Toussaint", "CosmeticOBS", "https://cosmeticobs.com/fr/feed/", ""),
        (13, "perso:Toussaint", "COSMED", "https://www.cosmed.eu/feed/", ""),
        (14, "perso:Toussaint", "Annel - Blog Réglementaire", "https://www.annel.fr/feed/", ""),
        (15, "perso:Toussaint", "Care Europe - Blog", "https://care-europe.com/feed/", ""),
        (16, "perso:Toussaint", "Commission Européenne - Cosmétiques", "https://ec.europa.eu/growth/sectors/cosmetics_en/rss", ""),
    ]
    conn.executemany(
        "INSERT INTO sources (id, user_id, nom, url, thematique, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, '2026-07-01T00:00:00+00:00')", lignes)
    conn.commit()
    return conn


def test_migre_les_5_sources_cosmetique_vers_la_cible():
    conn = _db_avec_etat_constate()
    resultat = migrer(conn)
    assert resultat["cosmetique_migrees"] == 5
    rows = conn.execute(
        "SELECT id, user_id, thematique FROM sources WHERE id IN (12,13,14,15,16)").fetchall()
    assert len(rows) == 5
    for r in rows:
        assert r["user_id"] == CIBLE
        assert r["thematique"] == "Cosmétique"


def test_migre_techcrunch_vers_la_cible_avec_thematique_ia():
    conn = _db_avec_etat_constate()
    migrer(conn)
    r = conn.execute("SELECT user_id, thematique FROM sources WHERE id = 8").fetchone()
    assert r["user_id"] == CIBLE
    assert r["thematique"] == "IA"


def test_retague_ia_les_9_sources_deja_sur_la_cible():
    conn = _db_avec_etat_constate()
    resultat = migrer(conn)
    assert resultat["ia_retaguees"] == 9
    rows = conn.execute(
        "SELECT thematique FROM sources WHERE id IN (2,3,4,5,6,7,9,10,11)").fetchall()
    assert all(r["thematique"] == "IA" for r in rows)


def test_tout_le_monde_regroupe_sous_2_thematiques_a_la_fin():
    conn = _db_avec_etat_constate()
    migrer(conn)
    rows = conn.execute(
        "SELECT DISTINCT user_id FROM sources").fetchall()
    assert [r["user_id"] for r in rows] == [CIBLE]
    thematiques = {r["thematique"] for r in conn.execute("SELECT DISTINCT thematique FROM sources")}
    assert thematiques == {"Cosmétique", "IA"}


def test_idempotent_deuxieme_passage_ne_change_rien():
    conn = _db_avec_etat_constate()
    migrer(conn)
    avant = [dict(r) for r in conn.execute("SELECT id, user_id, thematique FROM sources ORDER BY id")]
    resultat2 = migrer(conn)
    apres = [dict(r) for r in conn.execute("SELECT id, user_id, thematique FROM sources ORDER BY id")]
    assert avant == apres
    assert resultat2 == {"cosmetique_migrees": 0, "techcrunch_migree": 0, "ia_retaguees": 0}


def test_dry_run_ne_modifie_rien():
    conn = _db_avec_etat_constate()
    avant = [dict(r) for r in conn.execute("SELECT id, user_id, thematique FROM sources ORDER BY id")]
    migrer(conn, dry_run=True)
    conn.rollback()
    apres = [dict(r) for r in conn.execute("SELECT id, user_id, thematique FROM sources ORDER BY id")]
    assert avant == apres


def test_ne_touche_pas_aux_articles_ni_digests():
    conn = _db_avec_etat_constate()
    conn.execute(
        "INSERT INTO digests (user_id, thematique, date, texte_resume, nb_articles, created_at) "
        "VALUES ('public', '', '2026-07-23', 'resume', 23, '2026-07-23T00:00:00+00:00')")
    conn.commit()
    migrer(conn)
    r = conn.execute("SELECT user_id, thematique FROM digests WHERE date = '2026-07-23'").fetchone()
    assert r["user_id"] == "public"
    assert r["thematique"] == ""
```

- [ ] **Step 3: Run pour vérifier l'échec**

Run: `cd briques/veille-info/scripts && python -m pytest test_migration_20260727_consolidation_toussaint.py -v`
Expected: `ModuleNotFoundError: No module named 'migration_20260727_consolidation_toussaint'`.

- [ ] **Step 4: Implémenter `briques/veille-info/scripts/migration_20260727_consolidation_toussaint.py`**

```python
"""Migration ponctuelle (2026-07-27) : consolide sous le VRAI compte web de Toussaint les
sources RSS éparpillées sur 3 tenants distincts de veille-info, constaté en prod (HP,
docker exec workplace_veille_info, /data/veille_info.db) :

- `perso:Toussaint` (5 sources cosmétique, ids 12-16) : bucket créé HORS du parcours
  Keycloak (probablement des données de test/seed ajoutées via curl), jamais atteint par
  la vraie session web de Toussaint.
- `public` (1 source, id 8, TechCrunch AI) : tenant anonyme (aucune clé API présentée),
  conséquence du trou d'isolation d'atelier-veille corrigé par ailleurs (cf.
  docs/superpowers/plans/2026-07-27-atelier-veille-isolation-multiuser.md).
- `perso:f6541180-6751-4cb0-9ac8-dcf3c6a3f08e` (9 sources IA déjà en place, ids 2-7/9-11) :
  le VRAI compte web de Toussaint — son `sub` Keycloak (cf. core/auth.py::
  sub_session_optionnel). C'est la cible de consolidation.

Ne touche QUE la table `sources` — volontairement, pas `articles`/`digests` : ces derniers
n'ont aucune clé étrangère depuis `sources`, l'historique des anciens digests reste
orphelin mais inoffensif ; les FUTURS digests seront correctement rattachés puisque les
sources pointeront désormais toutes vers la cible.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

CIBLE = "perso:f6541180-6751-4cb0-9ac8-dcf3c6a3f08e"

_IDS_COSMETIQUE = (12, 13, 14, 15, 16)
_ID_TECHCRUNCH = 8


def migrer(conn: sqlite3.Connection, *, dry_run: bool = False) -> dict:
    """Applique la consolidation. Ne commite/rollback JAMAIS elle-même — laisse l'appelant
    (CLI ci-dessous, ou un test) décider. Idempotente : sur une base déjà migrée, les
    clauses WHERE ne matchent plus rien → tous les compteurs à 0."""
    c = conn.cursor()

    c.execute(
        f"UPDATE sources SET user_id = ?, thematique = 'Cosmétique' "
        f"WHERE id IN ({','.join('?' * len(_IDS_COSMETIQUE))}) AND user_id = 'perso:Toussaint'",
        (CIBLE, *_IDS_COSMETIQUE))
    cosmetique_migrees = c.rowcount

    c.execute(
        "UPDATE sources SET user_id = ?, thematique = 'IA' "
        "WHERE id = ? AND user_id = 'public'",
        (CIBLE, _ID_TECHCRUNCH))
    techcrunch_migree = c.rowcount

    c.execute(
        "UPDATE sources SET thematique = 'IA' WHERE user_id = ? AND thematique = ''",
        (CIBLE,))
    ia_retaguees = c.rowcount

    return {
        "cosmetique_migrees": cosmetique_migrees,
        "techcrunch_migree": techcrunch_migree,
        "ia_retaguees": ia_retaguees,
    }


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="/data/veille_info.db",
                        help="Chemin de la base SQLite (défaut : /data/veille_info.db, "
                             "le chemin DANS le conteneur workplace_veille_info).")
    parser.add_argument("--dry-run", action="store_true",
                        help="N'applique rien : affiche ce qui SERAIT fait puis ROLLBACK.")
    args = parser.parse_args()

    if not Path(args.db).exists():
        raise SystemExit(f"Base introuvable : {args.db}")

    conn = sqlite3.connect(args.db)
    try:
        resultat = migrer(conn, dry_run=args.dry_run)
        print(f"cosmetique_migrees={resultat['cosmetique_migrees']} "
             f"techcrunch_migree={resultat['techcrunch_migree']} "
             f"ia_retaguees={resultat['ia_retaguees']}")
        if args.dry_run:
            print("--dry-run : ROLLBACK (rien n'a été écrit).")
            conn.rollback()
        else:
            conn.commit()
            print("COMMIT effectué.")
    finally:
        conn.close()


if __name__ == "__main__":
    _cli()
```

- [ ] **Step 5: Run pour vérifier que les tests passent**

Run: `cd briques/veille-info/scripts && python -m pytest test_migration_20260727_consolidation_toussaint.py -v`
Expected: 7 passed.

- [ ] **Step 6: Run toute la suite de la brique pour vérifier l'absence de régression**

Run: `cd briques/veille-info && python -m pytest -v`
Expected: tous les tests passent (le nouveau dossier `scripts/` est indépendant du reste de la brique — aucune régression attendue).

- [ ] **Step 7: Commit**

```bash
git add briques/veille-info/scripts/
git commit -m "chore(veille-info): script de migration ponctuelle consolidation sources Toussaint"
```

---

## Exécution sur le HP (hors plan — manuelle, après merge + déploiement du code)

**Toujours commencer par le dry-run :**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 '
docker exec workplace_veille_info python3 scripts/migration_20260727_consolidation_toussaint.py --dry-run
'
```

Vérifier que la sortie affiche `cosmetique_migrees=5 techcrunch_migree=1 ia_retaguees=9`. Si les chiffres diffèrent, NE PAS continuer — l'état de la base a changé depuis la rédaction de ce plan (relire les tenants/ids réels avant d'exécuter pour de vrai, ne jamais lancer en aveugle sur une base de production).

**Puis, seulement si le dry-run est conforme, exécution réelle :**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 '
docker exec workplace_veille_info python3 scripts/migration_20260727_consolidation_toussaint.py
'
```

**Vérification finale :**

```bash
ssh -o BatchMode=yes debian@192.168.1.89 '
docker exec workplace_veille_info python3 -c "
import sqlite3
con = sqlite3.connect(\"/data/veille_info.db\")
for r in con.execute(\"SELECT user_id, thematique, count(*) FROM sources GROUP BY user_id, thematique\"):
    print(r)
"
'
```

Attendu : une seule valeur de `user_id` (`perso:f6541180-6751-4cb0-9ac8-dcf3c6a3f08e`), répartie en 2 groupes `thematique` (`Cosmétique` : 5, `IA` : 10).
