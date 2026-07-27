# Sélection de la thématique lors de la création d'un digest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter, dans l'onglet Digests de l'atelier-veille, la possibilité de déclencher un digest pour une seule thématique choisie (y compris en pause, avec fetch RSS forcé), en plus du bouton existant qui traite tout le foyer.

**Architecture:** Un paramètre optionnel `thematique` traverse la pile de bout en bout : `front.html` (select + bouton) → proxy `POST /veille/digest/executer` (atelier-veille) → `POST /digest/executer` (veille-info) → `digest.executer_digest_quotidien(thematique=...)` → deux nouvelles fonctions `stockage` qui ignorent l'état `enabled` pour permettre le fetch forcé d'une thématique en pause. Sans le paramètre, tous les chemins existants sont bit-à-bit inchangés (paramètre additif, valeur par défaut `None`).

**Tech Stack:** FastAPI + Pydantic + SQLite (`briques/veille-info`), FastAPI proxy + HTML/JS vanilla sans framework (`briques/atelier-veille`), pytest + `fastapi.testclient.TestClient`.

## Global Constraints

- Spec de référence : `docs/superpowers/specs/2026-07-27-selection-thematique-digest-design.md`.
- Sélection d'**une seule** thématique à la fois (pas de multi-select).
- Périmètre inchangé : tout le foyer, filtré sur la thématique choisie (pas de scoping par tenant).
- Une thématique en pause reste sélectionnable ; sa sélection force le fetch RSS de ses sources malgré `enabled=0`.
- La règle « 1 digest par thématique et par jour » (idempotence) reste inchangée, y compris pour la génération ponctuelle.
- Le bouton existant « Générer le digest maintenant (pour tout le foyer) » reste inchangé (comportement et code).
- Aucune nouvelle capacité exposée à l'assistant/LLM — fonctionnalité 100% humaine (UI seule).
- Tests exécutés via `cd briques/<brique> && python3 -m pytest -q` (motif du `Makefile` racine).

---

### Task 1: `stockage.py` — fonctions ignorant la pause pour la génération forcée

**Files:**
- Modify: `briques/veille-info/stockage.py:213-222` (juste après `basculer_pause_thematique`, avant la section `# ── Articles ──`)
- Test: `briques/veille-info/test_stockage.py` (nouvelles fonctions ajoutées en fin de fichier)

**Interfaces:**
- Produces: `stockage.lister_sources_thematique(user_id: str, thematique: str) -> list[dict]` (même forme de dict que `lister_sources` : `id`, `nom`, `url`, `thematique`, `enabled`, `created_at`)
- Produces: `stockage.lister_user_ids_thematique(thematique: str) -> list[str]`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à la fin de `briques/veille-info/test_stockage.py` :

```python
def test_lister_sources_thematique_inclut_les_sources_en_pause():
    s1 = stockage.creer_source("forcee-alice", "Flux A", "https://a-forcee.example/rss",
                               thematique="Tech")
    s2 = stockage.creer_source("forcee-alice", "Flux B", "https://b-forcee.example/rss",
                               thematique="Tech")
    stockage.basculer_pause_thematique("forcee-alice", "Tech", en_pause=True)

    sources = stockage.lister_sources_thematique("forcee-alice", "Tech")
    assert {s["id"] for s in sources} == {s1["id"], s2["id"]}
    assert all(s["enabled"] is False for s in sources)


def test_lister_sources_thematique_isole_par_user_et_thematique():
    stockage.creer_source("forcee-bob", "Flux Cuisine", "https://cuisine-forcee.example/rss",
                          thematique="Cuisine")
    assert stockage.lister_sources_thematique("forcee-bob", "Tech") == []


def test_lister_user_ids_thematique_inclut_meme_si_toutes_en_pause():
    stockage.creer_source("forcee-carol", "Flux", "https://carol-forcee.example/rss",
                          thematique="Tech")
    stockage.basculer_pause_thematique("forcee-carol", "Tech", en_pause=True)

    ids = stockage.lister_user_ids_thematique("Tech")
    assert "forcee-carol" in ids
    # lister_user_ids_actifs, lui, exclurait carol (aucune source active) :
    assert "forcee-carol" not in stockage.lister_user_ids_actifs()


def test_lister_user_ids_thematique_thematique_inexistante_vide():
    assert stockage.lister_user_ids_thematique("Inexistante-XYZ") == []
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/veille-info && python3 -m pytest test_stockage.py -k thematique -v`
Expected: FAIL — `AttributeError: module 'stockage' has no attribute 'lister_sources_thematique'` (et pareil pour `lister_user_ids_thematique`)

- [ ] **Step 3: Implémenter les deux fonctions**

Dans `briques/veille-info/stockage.py`, insérer juste après `basculer_pause_thematique` (ligne 221, avant le commentaire `# ── Articles ──` ligne 224) :

```python
def lister_sources_thematique(user_id: str, thematique: str) -> list[dict]:
    """Sources d'une thématique donnée pour cet utilisateur, actives OU en pause — utilisé
    pour forcer le fetch d'une thématique explicitement choisie (génération ponctuelle,
    S200), contrairement à lister_sources(actives_seulement=True) qui ne verrait rien si
    toutes les sources de la thématique sont en pause."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM sources WHERE user_id = ? AND thematique = ?",
            (user_id, thematique)).fetchall()
    return [_source_dict(r) for r in rows]


def lister_user_ids_thematique(thematique: str) -> list[str]:
    """Utilisateurs ayant au moins une source (active ou en pause) dans cette thématique.
    Contrairement à lister_user_ids_actifs(), n'exclut pas quelqu'un dont la seule
    thématique concernée est en pause (S200 — génération ponctuelle forcée)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT user_id FROM sources WHERE thematique = ?",
            (thematique,)).fetchall()
    return [r["user_id"] for r in rows]
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `cd briques/veille-info && python3 -m pytest test_stockage.py -v`
Expected: PASS (tous les tests du fichier, y compris les 4 nouveaux)

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/stockage.py briques/veille-info/test_stockage.py
git commit -m "feat(veille-info): lister_sources_thematique/lister_user_ids_thematique ignorent la pause"
```

---

### Task 2: `digest.py` — paramètre `thematique` pour cibler/forcer une génération

**Files:**
- Modify: `briques/veille-info/digest.py:76-147`
- Test: `briques/veille-info/test_digest.py` (nouveaux tests en fin de fichier)

**Interfaces:**
- Consumes: `stockage.lister_sources_thematique(user_id, thematique) -> list[dict]`, `stockage.lister_user_ids_thematique(thematique) -> list[str]` (Task 1)
- Produces: `digest.executer_digest_quotidien(user_ids: list[str] | None = None, thematique: str | None = None) -> dict` (signature élargie, rétrocompatible)
- Produces (interne) : `digest._traiter_utilisateur(user_id: str, thematique_forcee: str | None = None) -> int`, `digest._traiter_utilisateur_sans_planter(user_id: str, thematique_forcee: str | None = None) -> int`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à la fin de `briques/veille-info/test_digest.py` :

```python
def test_thematique_forcee_fetch_meme_si_en_pause(monkeypatch):
    """Cœur de la génération ponctuelle (S200) : une thématique en pause n'est PAS ignorée
    quand elle est explicitement demandée — ses sources sont fetchées de force, contrairement
    au chemin normal (thematiques_actives) qui les ignore totalement."""
    stockage.creer_source("digest-force-alice", "Flux Tech", "https://tech-force.example/rss",
                          thematique="Tech")
    stockage.basculer_pause_thematique("digest-force-alice", "Tech", en_pause=True)

    monkeypatch.setattr(digest.rss, "fetcher", lambda url: "<flux/>")
    monkeypatch.setattr(digest.rss, "parser_items", lambda texte: [
        {"titre": "Article", "url": "https://tech-force.example/1", "published_at": ""},
    ])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé forcé.")

    resultat = digest.executer_digest_quotidien(user_ids=["digest-force-alice"], thematique="Tech")
    assert resultat == {"utilisateurs_traites": 1, "digests_crees": 1}
    digests = stockage.lister_digests("digest-force-alice")
    assert digests[0]["texte_resume"] == "Résumé forcé."
    assert digests[0]["thematique"] == "Tech"


def test_thematique_choisie_ignore_les_autres_thematiques_actives(monkeypatch):
    stockage.creer_source("digest-force-bob", "Flux Tech", "https://tech-bob-force.example/rss",
                          thematique="Tech")
    stockage.creer_source("digest-force-bob", "Flux Cuisine",
                          "https://cuisine-bob-force.example/rss", thematique="Cuisine")

    monkeypatch.setattr(digest.rss, "fetcher", lambda url: url)
    monkeypatch.setattr(digest.rss, "parser_items",
                        lambda texte: [{"titre": "Article", "url": texte + "/1", "published_at": ""}])
    monkeypatch.setattr(digest, "llm_complete", lambda prompt, system="": "Résumé Tech.")

    resultat = digest.executer_digest_quotidien(user_ids=["digest-force-bob"], thematique="Tech")
    assert resultat["digests_crees"] == 1
    digests = stockage.lister_digests("digest-force-bob")
    assert {d["thematique"] for d in digests} == {"Tech"}  # Cuisine jamais traitée


def test_thematique_choisie_idempotente_si_digest_deja_fait(monkeypatch):
    stockage.creer_source("digest-force-carol", "Flux Tech",
                          "https://tech-carol-force.example/rss", thematique="Tech")
    stockage.inserer_digest("digest-force-carol", "Déjà fait.", 1, thematique="Tech")

    appele = {"llm": False}
    def _llm(prompt, system=""):
        appele["llm"] = True
        return "Ne devrait jamais être appelé."
    monkeypatch.setattr(digest, "llm_complete", _llm)

    resultat = digest.executer_digest_quotidien(user_ids=["digest-force-carol"], thematique="Tech")
    assert resultat["digests_crees"] == 0
    assert appele["llm"] is False


def test_thematique_choisie_decouvre_les_cibles_via_lister_user_ids_thematique(monkeypatch):
    """Sans `user_ids` explicite (chemin réel emprunté par la route HTTP), les cibles sont
    calculées via `stockage.lister_user_ids_thematique`, pas `lister_user_ids_actifs` — donc
    quelqu'un dont la thématique choisie est en pause est bien inclus."""
    monkeypatch.setattr(stockage, "lister_user_ids_thematique",
                        lambda thematique: ["digest-force-decouverte"] if thematique == "Tech" else [])
    monkeypatch.setattr(stockage, "lister_sources_thematique", lambda user_id, thematique: [])

    resultat = digest.executer_digest_quotidien(thematique="Tech")
    assert resultat == {"utilisateurs_traites": 1, "digests_crees": 0}


def test_thematique_inconnue_ne_traite_personne():
    resultat = digest.executer_digest_quotidien(thematique="Inexistante-XYZ-123")
    assert resultat == {"utilisateurs_traites": 0, "digests_crees": 0}
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/veille-info && python3 -m pytest test_digest.py -k thematique_forcee -v`
Expected: FAIL — `TypeError: executer_digest_quotidien() got an unexpected keyword argument 'thematique'`

- [ ] **Step 3: Implémenter le paramètre `thematique`**

Remplacer dans `briques/veille-info/digest.py` les trois fonctions `_traiter_utilisateur`, `_traiter_utilisateur_sans_planter` et `executer_digest_quotidien` (lignes 76-147) par :

```python
def _traiter_utilisateur(user_id: str, thematique_forcee: str | None = None) -> int:
    """Traite un utilisateur : fetch ses sources actives, résume PAR THÉMATIQUE s'il y a du
    nouveau (S199 — une thématique = un groupe de sources partageant `sources.thematique`,
    "" = thématique par défaut). Renvoie le nombre de digests créés (0, 1, ou plusieurs).

    `thematique_forcee` (S200 — génération ponctuelle depuis l'atelier) : si fourni, ne
    traite QUE cette thématique — et fetche ses sources même si elles sont en pause
    (`stockage.lister_sources_thematique`, pas `lister_sources(actives_seulement=True)`),
    pour ne pas produire un digest vide sur une thématique en pause depuis longtemps."""
    if thematique_forcee is not None:
        thematiques = [thematique_forcee]
        sources = stockage.lister_sources_thematique(user_id, thematique_forcee)
    else:
        thematiques = stockage.thematiques_actives(user_id)
        sources = stockage.lister_sources(user_id, actives_seulement=True)

    if thematiques and all(stockage.digest_existe(user_id, thematique=t) for t in thematiques):
        return 0  # tout est déjà fait aujourd'hui : pas la peine de fetcher (motif historique)

    for source in sources:
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


def _traiter_utilisateur_sans_planter(user_id: str, thematique_forcee: str | None = None) -> int:
    """Enrobe `_traiter_utilisateur` : une panne inattendue (ex. un appel `stockage.*` qui
    lève, en dehors des chemins déjà gardés dans `_traiter_utilisateur`) est journalisée
    et compte 0 digest créé pour cette personne, jamais propagée."""
    try:
        return _traiter_utilisateur(user_id, thematique_forcee)
    except Exception as e:  # noqa: BLE001 — une personne en échec inattendu ne doit jamais arrêter le lot
        logger.warning("Veille-info échec inattendu (user=%s) : %s", user_id, e)
        return 0


def executer_digest_quotidien(user_ids: list[str] | None = None,
                              thematique: str | None = None) -> dict:
    """Point d'entrée appelé par l'horloge du Cœur (ou à la main). Traite TOUTES les
    personnes ayant au moins une source active, ou seulement `user_ids` si fourni.

    `thematique` (S200 — génération ponctuelle depuis l'atelier) : si fourni SANS `user_ids`,
    les cibles sont calculées via `stockage.lister_user_ids_thematique` (inclut les personnes
    dont cette thématique est en pause), pas `lister_user_ids_actifs`. `user_ids` reste
    prioritaire quand fourni (chemin réservé aux tests, cf. commentaire historique) — la
    route HTTP de `main.py` ne le fournit JAMAIS."""
    if user_ids is not None:
        cibles = user_ids
    elif thematique is not None:
        cibles = stockage.lister_user_ids_thematique(thematique)
    else:
        cibles = stockage.lister_user_ids_actifs()
    digests_crees = sum(_traiter_utilisateur_sans_planter(uid, thematique) for uid in cibles)
    return {"utilisateurs_traites": len(cibles), "digests_crees": digests_crees}
```

- [ ] **Step 4: Lancer toute la suite du fichier, vérifier qu'elle passe**

Run: `cd briques/veille-info && python3 -m pytest test_digest.py -v`
Expected: PASS (tous les tests, anciens et nouveaux — la modification est additive, aucun test existant ne doit changer de comportement)

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/digest.py briques/veille-info/test_digest.py
git commit -m "feat(veille-info): executer_digest_quotidien(thematique=...) force une thématique même en pause"
```

---

### Task 3: `briques/veille-info/main.py` — corps optionnel `{"thematique": ...}` sur `POST /digest/executer`

**Files:**
- Modify: `briques/veille-info/main.py:224-226`
- Modify: `briques/veille-info/test_main.py:80-96` (mettre à jour les 2 lambdas existants)
- Test: `briques/veille-info/test_main.py` (2 nouveaux tests)

**Interfaces:**
- Consumes: `digest.executer_digest_quotidien(thematique: str | None = None) -> dict` (Task 2)
- Produces: route `POST /digest/executer` acceptant un corps optionnel `{"thematique": str | None}` (défaut : absent = comportement actuel)

- [ ] **Step 1: Mettre à jour les 2 tests existants (leurs mocks doivent accepter le nouveau kwarg) et écrire les 2 nouveaux tests**

Dans `briques/veille-info/test_main.py`, remplacer les lignes 80-96 :

```python
def test_digest_executer_ouvert_si_pas_de_cle_configuree(monkeypatch):
    monkeypatch.setattr(main.digest, "executer_digest_quotidien",
                        lambda thematique=None: {"utilisateurs_traites": 0, "digests_crees": 0})
    r = client.post("/digest/executer")
    assert r.status_code == 200
    assert "utilisateurs_traites" in r.json()


def test_digest_executer_gate_si_cle_configuree(monkeypatch):
    monkeypatch.setattr(main.digest, "executer_digest_quotidien",
                        lambda thematique=None: {"utilisateurs_traites": 0, "digests_crees": 0})
    monkeypatch.setenv("VEILLE_INFO_KEY", "secret-horloge")
    r = client.post("/digest/executer")
    assert r.status_code == 401
    r = client.post("/digest/executer", headers={"Authorization": "Bearer secret-horloge"})
    assert r.status_code == 200


def test_digest_executer_relaie_la_thematique_au_pipeline(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    captes = {}
    def _executer(thematique=None):
        captes["thematique"] = thematique
        return {"utilisateurs_traites": 1, "digests_crees": 1}
    monkeypatch.setattr(main.digest, "executer_digest_quotidien", _executer)

    r = client.post("/digest/executer", headers={"Authorization": "Bearer cle-coeur"},
                    json={"thematique": "Tech"})
    assert r.status_code == 200
    assert captes["thematique"] == "Tech"


def test_digest_executer_sans_corps_passe_thematique_none(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "cle-coeur")
    captes = {}
    def _executer(thematique=None):
        captes["thematique"] = thematique
        return {"utilisateurs_traites": 0, "digests_crees": 0}
    monkeypatch.setattr(main.digest, "executer_digest_quotidien", _executer)

    r = client.post("/digest/executer", headers={"Authorization": "Bearer cle-coeur"})
    assert r.status_code == 200
    assert captes["thematique"] is None
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/veille-info && python3 -m pytest test_main.py -k digest_executer -v`
Expected: FAIL sur les 2 nouveaux tests — `captes` reste `{}` car la route actuelle appelle `digest.executer_digest_quotidien()` sans kwarg et ignore tout corps envoyé. (Les 2 tests mis à jour, eux, doivent déjà passer : `lambda thematique=None: ...` reste appelable sans argument.)

- [ ] **Step 3: Implémenter le corps optionnel**

Dans `briques/veille-info/main.py`, remplacer les lignes 224-226 par :

```python
class ExecuterDigestBody(BaseModel):
    thematique: str | None = None


@app.post("/digest/executer", tags=["digest"])
def executer_digest_route(body: ExecuterDigestBody | None = None,
                          _: None = Depends(verifier_cle_horloge)):
    return digest.executer_digest_quotidien(thematique=body.thematique if body else None)
```

- [ ] **Step 4: Lancer toute la suite du fichier, vérifier qu'elle passe**

Run: `cd briques/veille-info && python3 -m pytest test_main.py -v`
Expected: PASS (tous les tests)

- [ ] **Step 5: Commit**

```bash
git add briques/veille-info/main.py briques/veille-info/test_main.py
git commit -m "feat(veille-info): POST /digest/executer accepte un corps optionnel {thematique}"
```

---

### Task 4: `briques/atelier-veille/main.py` — le proxy relaie la thématique choisie

**Files:**
- Modify: `briques/atelier-veille/main.py:328-344`
- Test: `briques/atelier-veille/test_composition.py` (1 nouveau test, après `test_executer_digest_refuse_relaie_lerreur` ligne 163-167)

**Interfaces:**
- Consumes: `POST {VEILLE_INFO_URL}/digest/executer` avec corps optionnel `{"thematique": ...}` (Task 3)
- Produces: route `POST /veille/digest/executer` acceptant un corps optionnel `{"thematique": str | None}`, relayé tel quel vers veille-info (le jeton `VEILLE_INFO_KEY` reste injecté côté serveur, inchangé)

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter dans `briques/atelier-veille/test_composition.py`, juste après `test_executer_digest_refuse_relaie_lerreur` (ligne 167) :

```python
def test_executer_digest_relaie_la_thematique_choisie(monkeypatch):
    monkeypatch.setenv("VEILLE_INFO_KEY", "jeton-horloge")
    import importlib
    importlib.reload(M)
    Faux = _client_json({"utilisateurs_traites": 1, "digests_crees": 1})
    monkeypatch.setattr(M.httpx, "AsyncClient", Faux)

    r = TestClient(M.app).post("/veille/digest/executer", json={"thematique": "Tech"})
    assert r.status_code == 200
    _, url, headers, corps = Faux.dernier_appel
    assert url == f"{M.VEILLE_INFO_URL}/digest/executer"
    assert headers == {"Authorization": "Bearer jeton-horloge"}
    assert corps == {"thematique": "Tech"}
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

Run: `cd briques/atelier-veille && python3 -m pytest test_composition.py -k relaie_la_thematique -v`
Expected: FAIL — `TypeError: executer_digest() got an unexpected keyword argument 'thematique'` (la route actuelle n'accepte aucun corps)

- [ ] **Step 3: Implémenter le relais du corps**

Dans `briques/atelier-veille/main.py`, remplacer les lignes 328-344 par :

```python
class ExecuterDigest(BaseModel):
    thematique: str | None = None


@app.post("/veille/digest/executer", tags=["veille"])
async def executer_digest(body: ExecuterDigest | None = None):
    """Déclenche le digest quotidien pour TOUT le foyer (motif horloge, pas un compte
    personnel) — gardé côté veille-info par un jeton de SERVICE, jamais l'identité du
    navigateur. `body.thematique` (S200), si fourni, cible une seule thématique, y compris
    en pause (fetch forcé côté veille-info)."""
    jeton = os.environ.get("VEILLE_INFO_KEY", "")
    entetes = {"Authorization": f"Bearer {jeton}"}
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{VEILLE_INFO_URL}/digest/executer", headers=entetes,
                             json=body.model_dump() if body else None)
        corps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"veille-info injoignable ({VEILLE_INFO_URL}) : {str(e)[:150]}")
    if r.status_code >= 400:
        detail = corps.get("detail") if isinstance(corps, dict) else None
        raise HTTPException(r.status_code, detail or f"veille-info a refusé la requête ({r.status_code}).")
    return corps
```

- [ ] **Step 4: Lancer toute la suite du fichier, vérifier qu'elle passe**

Run: `cd briques/atelier-veille && python3 -m pytest test_composition.py -v`
Expected: PASS (tous les tests, y compris `test_executer_digest_utilise_le_jeton_de_service_pas_lidentite_navigateur` et `test_executer_digest_sans_cle_configuree_envoie_bearer_vide`, qui postent sans corps et doivent continuer à fonctionner)

- [ ] **Step 5: Commit**

```bash
git add briques/atelier-veille/main.py briques/atelier-veille/test_composition.py
git commit -m "feat(atelier-veille): proxy POST /veille/digest/executer relaie {thematique}"
```

---

### Task 5: `front.html` — sélecteur de thématique dans l'onglet Digests

**Files:**
- Modify: `briques/atelier-veille/front.html:61-72` (markup) et `:88-347` (script)
- Test: `briques/atelier-veille/test_front.py` (1 nouveau test, après `test_front_avertit_que_la_generation_est_pour_tout_le_foyer` ligne 54-56)

**Interfaces:**
- Consumes: `GET /veille/thematiques` (existant, renvoie `[{thematique, nb_sources, en_pause}]`), `POST /veille/digest/executer` avec corps `{"thematique": str}` (Task 4)
- Produces: fonctions JS globales `chargerThematiquesDigest()`, `genererDigestThematique()`, élément `#select-thematique-digest`

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter dans `briques/atelier-veille/test_front.py`, après `test_front_avertit_que_la_generation_est_pour_tout_le_foyer` (ligne 56) :

```python
def test_front_couvre_la_selection_de_thematique_pour_le_digest():
    html = client.get("/").text
    for marqueur in ("chargerThematiquesDigest", "genererDigestThematique",
                     "select-thematique-digest"):
        assert marqueur in html
```

- [ ] **Step 2: Lancer le test, vérifier qu'il échoue**

Run: `cd briques/atelier-veille && python3 -m pytest test_front.py -k selection_de_thematique -v`
Expected: FAIL — les 3 marqueurs sont absents de `front.html`

- [ ] **Step 3: Ajouter le markup dans l'onglet Digests**

Dans `briques/atelier-veille/front.html`, remplacer les lignes 68-69 :

```html
    <p style="color:var(--mut);font-size:.82rem">Ce bouton déclenche le digest pour TOUT le
      foyer d'un coup (comme l'horloge quotidienne), pas seulement pour toi.</p>
```

par :

```html
    <p style="color:var(--mut);font-size:.82rem">Ce bouton déclenche le digest pour TOUT le
      foyer d'un coup (comme l'horloge quotidienne), pas seulement pour toi.</p>
    <div style="margin-top:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <label for="select-thematique-digest" style="color:var(--mut);font-size:.85rem">Générer pour une thématique précise :</label>
      <select id="select-thematique-digest" style="padding:8px;border-radius:8px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)"></select>
      <button id="btn-generer-digest-thematique" onclick="genererDigestThematique()" style="padding:8px 16px;border-radius:8px;border:1px solid var(--accent);background:transparent;color:var(--accent);font-weight:600;cursor:pointer">
        Générer pour cette thématique
      </button>
    </div>
```

- [ ] **Step 4: Ajouter les fonctions JS**

Dans `briques/atelier-veille/front.html`, remplacer la fonction `genererDigest` (lignes 233-247) par elle-même suivie des deux nouvelles fonctions :

```html
async function genererDigest() {
  const bouton = document.getElementById('btn-generer-digest');
  const erreur = document.getElementById('erreur-digests');
  erreur.textContent = '';
  bouton.disabled = true;
  try {
    const r = await fetch(`${API_BASE}/veille/digest/executer`, {method: 'POST'});
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    await chargerDigests();
  } catch (e) {
    erreur.textContent = String(e.message || e);
  } finally {
    bouton.disabled = false;
  }
}

async function chargerThematiquesDigest() {
  const select = document.getElementById('select-thematique-digest');
  try {
    const r = await fetch(`${API_BASE}/veille/thematiques`);
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    const thematiques = await r.json();
    if (!thematiques.length) {
      select.innerHTML = '<option value="" disabled selected>Aucune thématique — ajoute une source dans Sources RSS</option>';
      select.disabled = true;
      return;
    }
    select.disabled = false;
    select.innerHTML = thematiques.map(t => {
      const label = (t.thematique || 'Général') + (t.en_pause ? ' (en pause)' : '');
      return `<option value="${esc(t.thematique)}">${esc(label)}</option>`;
    }).join('');
  } catch (e) {
    select.innerHTML = '<option value="" disabled selected>Erreur de chargement</option>';
    select.disabled = true;
  }
}

async function genererDigestThematique() {
  const select = document.getElementById('select-thematique-digest');
  const bouton = document.getElementById('btn-generer-digest-thematique');
  const erreur = document.getElementById('erreur-digests');
  erreur.textContent = '';
  if (select.disabled) return;
  const thematique = select.value;
  bouton.disabled = true;
  try {
    const r = await fetch(`${API_BASE}/veille/digest/executer`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({thematique})
    });
    if (!r.ok) throw new Error((await r.json()).detail || 'Erreur');
    const resultat = await r.json();
    if (!resultat.digests_crees) {
      erreur.textContent = 'Rien à faire — déjà généré aujourd\'hui ou aucun nouvel article pour cette thématique.';
    }
    await chargerDigests();
  } catch (e) {
    erreur.textContent = String(e.message || e);
  } finally {
    bouton.disabled = false;
  }
}
```

- [ ] **Step 5: Brancher le chargement du select sur l'ouverture de l'onglet et le chargement initial**

Dans `briques/atelier-veille/front.html`, remplacer la ligne 97 :

```html
  if (nom === 'digests') chargerDigests();
```

par :

```html
  if (nom === 'digests') { chargerDigests(); chargerThematiquesDigest(); }
```

Puis remplacer les lignes 345-346 :

```html
chargerConfig();
chargerDigests();
```

par :

```html
chargerConfig();
chargerDigests();
chargerThematiquesDigest();
```

- [ ] **Step 6: Lancer toute la suite du fichier, vérifier qu'elle passe**

Run: `cd briques/atelier-veille && python3 -m pytest test_front.py -v`
Expected: PASS (tous les tests, y compris les marqueurs déjà couverts comme `genererDigest`, `/veille/digest/executer`)

- [ ] **Step 7: Lancer toute la suite de la brique (regression complète)**

Run: `cd briques/atelier-veille && python3 -m pytest -q`
Expected: PASS (aucune régression sur `test_composition.py`, `test_main.py`, `test_front.py`)

- [ ] **Step 8: Vérification manuelle dans le navigateur**

Lancer la brique (`docker compose up -d --build atelier-veille` ou équivalent local), ouvrir l'onglet Digests, vérifier :
- le select liste les thématiques existantes, avec « (en pause) » sur celles en pause
- cliquer « Générer pour cette thématique » sur une thématique en pause déclenche bien un fetch RSS et crée un digest s'il y a des articles
- le bouton « Générer le digest maintenant (pour tout le foyer) » se comporte exactement comme avant

- [ ] **Step 9: Commit**

```bash
git add briques/atelier-veille/front.html briques/atelier-veille/test_front.py
git commit -m "feat(atelier-veille): sélecteur de thématique dans l'onglet Digests"
```
