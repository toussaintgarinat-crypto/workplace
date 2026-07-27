"""Migration ponctuelle (2026-07-27) : consolide les sources RSS éparpillées sur 3
tenants (perso:Toussaint, public, perso:<uuid>) sous le VRAI compte web de Toussaint.
État constaté en prod documenté dans le docstring du module de migration lui-même."""
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

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
