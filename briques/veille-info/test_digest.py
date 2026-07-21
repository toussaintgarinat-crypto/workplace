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
    assert len(stockage.articles_non_digestes("digest-erin")) == 1


def test_echec_inattendu_stockage_ne_bloque_pas_le_lot(monkeypatch):
    """Une panne inattendue (ex. `stockage.lister_sources` qui lève, hors des deux chemins
    déjà gardés dans `_traiter_utilisateur`) doit être rattrapée par
    `_traiter_utilisateur_sans_planter` : comptée comme 0 digest pour cette personne, sans
    jamais faire planter `executer_digest_quotidien` ni le lot."""
    stockage.creer_source("digest-frank", "Flux", "https://frank.example/rss")

    lister_sources_original = stockage.lister_sources
    def _lister_sources_qui_casse(user_id, *args, **kwargs):
        if user_id == "digest-frank":
            raise RuntimeError("panne disque")
        return lister_sources_original(user_id, *args, **kwargs)
    monkeypatch.setattr(digest.stockage, "lister_sources", _lister_sources_qui_casse)

    resultat = digest.executer_digest_quotidien(user_ids=["digest-frank"])
    assert resultat == {"utilisateurs_traites": 1, "digests_crees": 0}


def test_articles_non_digeres_recuperes_au_prochain_passage(monkeypatch):
    """Le vrai scénario du bug corrigé : panne LLM un jour (article stocké, pas
    résumé) puis, le lendemain, aucun nouvel article RSS — l'article laissé de côté
    doit quand même être repris et digéré, pas perdu silencieusement."""
    stockage.creer_source("digest-henri", "Flux", "https://henri.example/rss")
    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "<flux/>")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article J1", "url": "https://henri.example/1", "published_at": ""},
    ])

    def _llm_echoue(prompt, system=""):
        raise RuntimeError("Gateway indisponible")
    monkeypatch.setattr(digest, "llm_complete", _llm_echoue)
    resultat = digest.executer_digest_quotidien(user_ids=["digest-henri"])
    assert resultat["digests_crees"] == 0

    # Passage suivant : Gateway rétablie, mais AUCUN nouvel article RSS.
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé de rattrapage.")
    resultat = digest.executer_digest_quotidien(user_ids=["digest-henri"])
    assert resultat["digests_crees"] == 1
    digests = stockage.lister_digests("digest-henri")
    assert len(digests) == 1
    assert digests[0]["nb_articles"] == 1
