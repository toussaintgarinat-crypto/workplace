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
