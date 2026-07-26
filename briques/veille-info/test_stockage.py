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


def test_articles_non_digestes_isole_par_user_id():
    s = stockage.creer_source("frank", "Flux", "https://example.com/frank-rss")
    stockage.inserer_article("frank", s["id"], "Titre", "https://frank.example/1", "")
    assert len(stockage.articles_non_digestes("frank")) == 1
    assert stockage.articles_non_digestes("grace") == []


def test_marquer_articles_digestes_les_exclut_ensuite():
    s = stockage.creer_source("henri", "Flux", "https://example.com/henri-rss")
    stockage.inserer_article("henri", s["id"], "Titre", "https://henri.example/1", "")
    articles = stockage.articles_non_digestes("henri")
    assert len(articles) == 1
    stockage.marquer_articles_digestes([a["id"] for a in articles])
    assert stockage.articles_non_digestes("henri") == []


def test_digest_idempotent_par_user_et_date():
    assert stockage.digest_existe("heidi") is False
    stockage.inserer_digest("heidi", "Résumé du jour.", 3)
    assert stockage.digest_existe("heidi") is True


def test_lister_et_lire_digest_isole_par_user_id():
    d = stockage.inserer_digest("ivan", "Résumé.", 2)
    assert len(stockage.lister_digests("ivan")) == 1
    assert stockage.digest_get("ivan", d["id"])["texte_resume"] == "Résumé."
    assert stockage.digest_get("judy", d["id"]) is None


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
