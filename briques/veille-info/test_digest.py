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

    # Simule le passage au lendemain : l'article stocké hier ne doit PAS dépendre de
    # created_at == aujourd'hui pour être repris (c'est exactement le bug corrigé —
    # sans ce backdatage, ce test passerait aussi contre l'ancien code date-scopé).
    with stockage._conn() as c:
        c.execute("UPDATE articles SET created_at = '2020-01-01T00:00:00+00:00' "
                 "WHERE user_id = 'digest-henri'")

    # Passage suivant : Gateway rétablie, mais AUCUN nouvel article RSS.
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé de rattrapage.")
    resultat = digest.executer_digest_quotidien(user_ids=["digest-henri"])
    assert resultat["digests_crees"] == 1
    digests = stockage.lister_digests("digest-henri")
    assert len(digests) == 1
    assert digests[0]["nb_articles"] == 1


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


def test_echec_stockage_audio_ne_bloque_pas_le_comptage_du_digest(monkeypatch):
    """Le trou trouvé en revue : si stockage.inserer_audio_digest lève (ex. DB verrouillée),
    ça ne doit PAS faire remonter jusqu'au filet du lot — le digest texte, déjà créé, doit
    toujours compter comme créé."""
    stockage.creer_source("digest-laura", "Flux", "https://laura.example/rss")
    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "<flux/>")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article", "url": "https://laura.example/1", "published_at": ""},
    ])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé du jour.")

    class _Rep:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"url": "https://voix.example/episodes/x.mp3", "duree": 10.0}
    monkeypatch.setattr(digest.httpx, "post", lambda *a, **k: _Rep())

    def _inserer_audio_qui_casse(*a, **k):
        raise RuntimeError("DB verrouillée")
    monkeypatch.setattr(digest.stockage, "inserer_audio_digest", _inserer_audio_qui_casse)

    resultat = digest.executer_digest_quotidien(user_ids=["digest-laura"])
    assert resultat == {"utilisateurs_traites": 1, "digests_crees": 1}
    d = stockage.lister_digests("digest-laura")[0]
    assert d["texte_resume"] == "Résumé du jour."
    assert d["audio_url"] is None  # l'écriture audio a échoué, pas de ligne digest_audio


def test_echec_marquage_articles_ne_bloque_pas_le_comptage_du_digest(monkeypatch):
    """Le trou restant trouvé en revue finale : si stockage.marquer_articles_digestes lève
    (ex. verrou SQLite transitoire), ça ne doit PAS faire remonter jusqu'au filet du lot —
    le digest, déjà créé par stockage.inserer_digest juste avant, doit toujours compter
    comme créé et rester en base."""
    stockage.creer_source("digest-marie", "Flux", "https://marie.example/rss")
    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "<flux/>")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article", "url": "https://marie.example/1", "published_at": ""},
    ])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé du jour.")

    def _marquer_qui_casse(article_ids):
        raise RuntimeError("DB verrouillée")
    monkeypatch.setattr(digest.stockage, "marquer_articles_digestes", _marquer_qui_casse)

    resultat = digest.executer_digest_quotidien(user_ids=["digest-marie"])
    assert resultat == {"utilisateurs_traites": 1, "digests_crees": 1}
    digests = stockage.lister_digests("digest-marie")
    assert len(digests) == 1
    assert digests[0]["texte_resume"] == "Résumé du jour."


def test_digest_pousse_un_resume_dans_memoire(monkeypatch):
    stockage.creer_source("digest-frank", "Flux F", "https://f.example/rss")
    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "<flux/>")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article", "url": "https://f.example/1", "published_at": ""},
    ])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé du jour.")
    captes = {}

    def _post(url, json=None, headers=None, timeout=None):
        assert url.endswith("/retenir")
        captes["json"] = json
        captes["headers"] = headers
        class _Rep:
            status_code = 200
            def raise_for_status(self):
                pass
        return _Rep()

    monkeypatch.setattr(digest.httpx, "post", _post)
    resultat = digest.executer_digest_quotidien(user_ids=["digest-frank"])
    assert resultat["digests_crees"] == 1
    assert captes["json"]["espace"] == "veille"
    assert captes["json"]["wing"] == "veille-info"
    assert captes["json"]["contenu"] == "Résumé du jour."
    assert captes["headers"]["X-User-Id"] == "digest-frank"


def test_digest_memoire_recoit_x_user_id_sans_prefixe_perso(monkeypatch):
    """Le seam trouvé en revue finale : `user_id` est le tenant INTERNE tel que produit par
    `tenant_actuel` (forme réelle `perso:claire`, jamais une simple chaîne comme
    `digest-frank`), mais `memoire` isole par personne sur le X-User-Id BRUT (sans préfixe)
    que lui envoie le Cœur. Sans le retrait du préfixe, le résumé atterrit dans un espace
    (`veille-perso:claire`) que le chemin de rappel du Cœur ne lit jamais (il envoie
    `X-User-Id: claire`, cf. core/contexte_tenant.py)."""
    stockage.creer_source("perso:claire", "Flux C", "https://c-claire.example/rss")
    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "<flux/>")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article", "url": "https://c-claire.example/1", "published_at": ""},
    ])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé du jour.")
    captes = {}

    def _post(url, json=None, headers=None, timeout=None):
        assert url.endswith("/retenir")
        captes["headers"] = headers
        class _Rep:
            status_code = 200
            def raise_for_status(self):
                pass
        return _Rep()

    monkeypatch.setattr(digest.httpx, "post", _post)
    resultat = digest.executer_digest_quotidien(user_ids=["perso:claire"])
    assert resultat["digests_crees"] == 1
    assert captes["headers"]["X-User-Id"] == "claire"
    # Le tenant interne complet ("perso:claire") reste, lui, utilisé tel quel côté stockage :
    assert len(stockage.lister_digests("perso:claire")) == 1


def test_digest_memoire_injoignable_najamais_bloquant(monkeypatch):
    stockage.creer_source("digest-grace", "Flux G", "https://g.example/rss")
    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "<flux/>")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article", "url": "https://g.example/1", "published_at": ""},
    ])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé.")

    def _post(url, json=None, headers=None, timeout=None):
        raise ConnectionError("memoire down")

    monkeypatch.setattr(digest.httpx, "post", _post)
    resultat = digest.executer_digest_quotidien(user_ids=["digest-grace"])
    assert resultat["digests_crees"] == 1   # le digest texte n'est PAS affecté
    assert len(stockage.lister_digests("digest-grace")) == 1
