"""Tests du stockage SQLite du maillage spatial (mondes/cellules/placements) —
Sprint B. Même motif que test_stockage.py (DB temporaire posée par conftest.py)."""
import re
from pathlib import Path

import stockage
import stockage_spatial


def _extraire_ddl_enfants(chemin_module: str) -> str:
    """Extrait le bloc `CREATE TABLE IF NOT EXISTS enfants (...)` (colonnes incluses)
    du texte source d'un module — helper simple, pas un vrai parseur SQL : suffisant
    pour comparer les deux copies dupliquées de cette DDL (stockage.py et
    stockage_spatial.py) et détecter toute dérive entre elles."""
    texte = Path(chemin_module).read_text(encoding="utf-8")
    m = re.search(r"CREATE TABLE IF NOT EXISTS enfants\s*\((.*?)\)\"\"\"", texte, re.DOTALL)
    assert m, f"DDL 'enfants' introuvable dans {chemin_module}"
    return re.sub(r"\s+", " ", m.group(1)).strip()


def test_ddl_enfants_identique_a_stockage():
    """Correctif revue finale (Important) : la table `enfants` est dupliquée entre
    stockage.py et stockage_spatial.py (fix latent Task 2, duplication endossée par
    la revue — pas refactorée ici). Rien ne garantissait que les deux schémas restent
    identiques : ce test pince les deux DDL en synchro, il doit casser si l'une des
    deux copies dérive de l'autre."""
    ici = Path(__file__).parent
    ddl_stockage = _extraire_ddl_enfants(str(ici / "stockage.py"))
    ddl_spatial = _extraire_ddl_enfants(str(ici / "stockage_spatial.py"))
    assert ddl_stockage == ddl_spatial


def _cellules_factices(n=3):
    return [{"cellule_id": i, "x": float(i) * 10, "y": float(i) * 5, "biome": "plaine",
             "ressources": ["ble"], "voisins": [j for j in range(n) if j != i]}
            for i in range(n)]


def test_creer_monde_puis_lire():
    meta = stockage_spatial.creer_monde("cle-a", _cellules_factices(3), seed=42)
    assert isinstance(meta["id"], str) and meta["id"]
    assert meta["nb_cellules"] == 3
    assert meta["seed"] == 42
    assert meta["forked_from_id"] is None

    monde = stockage_spatial.lire_monde("cle-a", meta["id"])
    assert monde["id"] == meta["id"]
    assert len(monde["cellules"]) == 3
    assert monde["cellules"][0]["biome"] == "plaine"
    assert monde["cellules"][0]["ressources"] == ["ble"]
    assert monde["cellules"][0]["enfants"] == []


def test_lire_monde_introuvable_renvoie_none():
    assert stockage_spatial.lire_monde("cle-a", "id-inconnu") is None


def test_lire_monde_cloisonne_par_cle_api():
    meta = stockage_spatial.creer_monde("cle-b", _cellules_factices(3), seed=1)
    assert stockage_spatial.lire_monde("cle-b", meta["id"]) is not None
    assert stockage_spatial.lire_monde("autre-cle", meta["id"]) is None


def test_lister_mondes_cloisonne_et_ordonne():
    stockage_spatial.creer_monde("cle-c", _cellules_factices(3), seed=1)
    m2 = stockage_spatial.creer_monde("cle-c", _cellules_factices(3), seed=2)
    resultats = stockage_spatial.lister_mondes("cle-c")
    assert resultats[0]["id"] == m2["id"]  # plus récent d'abord
    assert "cellules" not in resultats[0]  # liste allégée
    assert stockage_spatial.lister_mondes("cle-vide") == []


def test_monde_existe():
    meta = stockage_spatial.creer_monde("cle-d", _cellules_factices(3), seed=1)
    assert stockage_spatial.monde_existe("cle-d", meta["id"]) is True
    assert stockage_spatial.monde_existe("autre-cle", meta["id"]) is False
    assert stockage_spatial.monde_existe("cle-d", "id-inconnu") is False


def test_lire_cellule():
    meta = stockage_spatial.creer_monde("cle-e", _cellules_factices(3), seed=1)
    cellule = stockage_spatial.lire_cellule("cle-e", meta["id"], 1)
    assert cellule["cellule_id"] == 1
    assert cellule["voisins"] == [0, 2]
    assert stockage_spatial.lire_cellule("cle-e", meta["id"], 99) is None
    assert stockage_spatial.lire_cellule("autre-cle", meta["id"], 1) is None


def test_voisins_cellule():
    meta = stockage_spatial.creer_monde("cle-f", _cellules_factices(3), seed=1)
    assert stockage_spatial.voisins_cellule(meta["id"], 0) == [1, 2]
    assert stockage_spatial.voisins_cellule(meta["id"], 99) is None


def test_nb_cellules_monde():
    meta = stockage_spatial.creer_monde("cle-g", _cellules_factices(5), seed=1)
    assert stockage_spatial.nb_cellules_monde(meta["id"]) == 5
    assert stockage_spatial.nb_cellules_monde("id-inconnu") is None


def test_proprietaire_monde():
    """Lookup par id seul (même motif que `nb_cellules_monde`) — utilisé par la
    migration transfrontière pour savoir à quel tenant transférer un émigrant."""
    meta = stockage_spatial.creer_monde("cle-proprio", _cellules_factices(2), seed=1)
    assert stockage_spatial.proprietaire_monde(meta["id"]) == "cle-proprio"
    assert stockage_spatial.proprietaire_monde("id-inconnu") is None


def test_placer_et_lire_avec_enfants():
    meta = stockage_spatial.creer_monde("cle-h", _cellules_factices(3), seed=1)
    eid = stockage.creer("cle-h", "Nova", "Test", None, None,
                          {"theme_complet": {}}, "d", {"resume": {}}, False)
    stockage_spatial.placer(meta["id"], eid, 1)
    assert stockage_spatial.placement_cellule(meta["id"], eid) == 1

    monde = stockage_spatial.lire_monde("cle-h", meta["id"])
    cellule_1 = next(c for c in monde["cellules"] if c["cellule_id"] == 1)
    assert cellule_1["enfants"] == [{"id": eid, "prenoms": "Nova", "nom": "Test"}]

    cellule = stockage_spatial.lire_cellule("cle-h", meta["id"], 1)
    assert cellule["enfants"] == [{"id": eid, "prenoms": "Nova", "nom": "Test"}]


def test_placement_cellule_absent_renvoie_none():
    meta = stockage_spatial.creer_monde("cle-i", _cellules_factices(3), seed=1)
    assert stockage_spatial.placement_cellule(meta["id"], "enfant-inconnu") is None


def test_placer_remplace_le_placement_precedent():
    meta = stockage_spatial.creer_monde("cle-j", _cellules_factices(3), seed=1)
    eid = stockage.creer("cle-j", "Nova", "", None, None,
                          {"theme_complet": {}}, "d", {"resume": {}}, False)
    stockage_spatial.placer(meta["id"], eid, 0)
    stockage_spatial.placer(meta["id"], eid, 2)
    assert stockage_spatial.placement_cellule(meta["id"], eid) == 2


def test_forker_monde_copie_cellules_et_placements():
    meta = stockage_spatial.creer_monde("cle-k", _cellules_factices(3), seed=1)
    eid = stockage.creer("cle-k", "Nova", "", None, None,
                          {"theme_complet": {}}, "d", {"resume": {}}, False)
    stockage_spatial.placer(meta["id"], eid, 1)

    fork = stockage_spatial.forker_monde("cle-k", meta["id"])
    assert fork["forked_from_id"] == meta["id"]
    assert fork["id"] != meta["id"]
    assert fork["nb_cellules"] == 3
    assert fork["seed"] == 1
    assert stockage_spatial.placement_cellule(fork["id"], eid) == 1

    monde_fork = stockage_spatial.lire_monde("cle-k", fork["id"])
    assert len(monde_fork["cellules"]) == 3


def test_forker_monde_independant_de_loriginal():
    meta = stockage_spatial.creer_monde("cle-l", _cellules_factices(3), seed=1)
    fork = stockage_spatial.forker_monde("cle-l", meta["id"])
    eid = stockage.creer("cle-l", "Nouveau", "", None, None,
                          {"theme_complet": {}}, "d", {"resume": {}}, False)
    stockage_spatial.placer(fork["id"], eid, 0)  # placement APRÈS le fork, sur le fork seul
    assert stockage_spatial.placement_cellule(fork["id"], eid) == 0
    assert stockage_spatial.placement_cellule(meta["id"], eid) is None  # jamais propagé à l'original


def test_forker_monde_introuvable_renvoie_none():
    assert stockage_spatial.forker_monde("cle-m", "id-inconnu") is None


def test_supprimer_monde_cascade():
    meta = stockage_spatial.creer_monde("cle-n", _cellules_factices(3), seed=1)
    eid = stockage.creer("cle-n", "Nova", "", None, None,
                          {"theme_complet": {}}, "d", {"resume": {}}, False)
    stockage_spatial.placer(meta["id"], eid, 0)

    assert stockage_spatial.supprimer_monde("cle-n", meta["id"]) is True
    assert stockage_spatial.lire_monde("cle-n", meta["id"]) is None
    assert stockage_spatial.voisins_cellule(meta["id"], 0) is None
    assert stockage_spatial.placement_cellule(meta["id"], eid) is None


def test_supprimer_monde_introuvable_renvoie_false():
    assert stockage_spatial.supprimer_monde("cle-n", "id-inconnu") is False


def test_supprimer_monde_cloisonne_par_cle_api():
    meta = stockage_spatial.creer_monde("cle-o", _cellules_factices(3), seed=1)
    assert stockage_spatial.supprimer_monde("autre-cle", meta["id"]) is False
    assert stockage_spatial.lire_monde("cle-o", meta["id"]) is not None


def test_migration_alter_table_enfants_from_legacy_schema(monkeypatch, tmp_path):
    """Correctif revue finale (Important) : la branche `ALTER TABLE ADD COLUMN` de
    `_ajouter_colonne()` était jamais testée dans stockage_spatial.py non plus —
    `conftest.py` détruit+recrée la DB fraîche à chaque test, donc `CREATE TABLE IF NOT EXISTS`
    crée toujours la table complète avec `sexe` déjà présent.

    Ce test simule une DB legacy (Sprint A/B) SANS la colonne `sexe` ni les tables spatiales,
    puis vérifie que la migration via `_conn()` crée/ajoute correctement les colonnes."""
    import sqlite3

    # Créer une DB legacy avec l'ancien schéma (SANS sexe, sans tables spatiales)
    legacy_db = tmp_path / "legacy_spatial.db"
    legacy_conn = sqlite3.connect(str(legacy_db))

    # Créer uniquement la table enfants (sans sexe) — pas les tables spatiales encore
    legacy_conn.execute("""CREATE TABLE enfants (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, prenoms TEXT, nom TEXT,
        parent_a_id TEXT, parent_b_id TEXT, donnees TEXT NOT NULL, cree_le TEXT)""")
    legacy_conn.execute("INSERT INTO enfants (id, cle_api, prenoms, nom, parent_a_id, "
                        "parent_b_id, donnees, cree_le) VALUES (?,?,?,?,?,?,?,?)",
                        ("legacy-enfant", "legacy-spatial-cle", "LegacyChild", "Parent", None, None,
                         '{"theme": {}, "description_genome": "legacy", "heredite": {}, "mutation_survenue": false}',
                         "2026-01-01T00:00:00+00:00"))
    legacy_conn.commit()
    legacy_conn.close()

    # Rediriger stockage_spatial.DB_PATH vers la legacy DB
    original_db_path = stockage_spatial.DB_PATH
    monkeypatch.setattr(stockage_spatial, "DB_PATH", str(legacy_db))

    try:
        # Appeler `lire_monde()` qui passe par `_conn()` → migration exécutée
        # Même si le monde n'existe pas, _conn() crée/migre les tables
        result = stockage_spatial.lire_monde("legacy-spatial-cle", "nonexistent-monde")
        assert result is None, "Monde n'existe pas, mais tables sont migrées"

        # Créer un monde → cela utilise la DB migrée
        meta = stockage_spatial.creer_monde("legacy-spatial-cle", _cellules_factices(2), seed=99)
        assert meta["id"], "Monde créé avec succès"

        # Créer un enfant via stockage (qui partage la même DB)
        # Mais nous ne pouvons pas importer stockage ici sans risquer les chemins
        # À la place, vérifier que les tables spatiales existent et que sexe est prêt
        with stockage_spatial._conn() as c:
            # Vérifier que sexe colonne existe maintenant
            infos = c.execute("PRAGMA table_info(enfants)").fetchall()
            colonnes = {row[1] for row in infos}
            assert "sexe" in colonnes, "colonne sexe doit exister après migration"

            # Vérifier qu'on peut lire l'ancien enfant legacy
            old_row = c.execute("SELECT * FROM enfants WHERE id=?", ("legacy-enfant",)).fetchone()
            assert old_row is not None, "Enfant legacy doit être accessible"
            assert old_row["sexe"] is None, "sexe legacy doit être None"

    finally:
        # Restaurer le DB_PATH original
        monkeypatch.setattr(stockage_spatial, "DB_PATH", original_db_path)


def test_placer_avec_ne_au_tick_et_population_vivante():
    monde = stockage_spatial.creer_monde("cle-tick1", _cellules_factices(2), seed=1)
    stockage.creer("cle-tick1", "Ana", "X", None, None, {"theme": {}}, "d", {}, False, sexe="F")
    eid = stockage.lister("cle-tick1")[0]["id"]
    stockage_spatial.placer(monde["id"], eid, 0, ne_au_tick=3)
    pop = stockage_spatial.population_vivante_cellule(monde["id"], 0)
    assert pop == [{"id": eid, "sexe": "F", "ne_au_tick": 3}]


def test_placer_defaut_ne_au_tick_zero():
    monde = stockage_spatial.creer_monde("cle-tick2", _cellules_factices(2), seed=1)
    stockage.creer("cle-tick2", "Bo", "X", None, None, {"theme": {}}, "d", {}, False, sexe="M")
    eid = stockage.lister("cle-tick2")[0]["id"]
    stockage_spatial.placer(monde["id"], eid, 0)
    pop = stockage_spatial.population_vivante_cellule(monde["id"], 0)
    assert pop[0]["ne_au_tick"] == 0


def test_marquer_mort_exclut_de_la_population_vivante():
    monde = stockage_spatial.creer_monde("cle-tick3", _cellules_factices(2), seed=1)
    stockage.creer("cle-tick3", "Cy", "X", None, None, {"theme": {}}, "d", {}, False, sexe="M")
    eid = stockage.lister("cle-tick3")[0]["id"]
    stockage_spatial.placer(monde["id"], eid, 0)
    stockage_spatial.marquer_mort(monde["id"], eid, tick=7)
    assert stockage_spatial.population_vivante_cellule(monde["id"], 0) == []


def test_deplacer_placement_change_de_cellule():
    monde = stockage_spatial.creer_monde("cle-tick4", _cellules_factices(2), seed=1)
    stockage.creer("cle-tick4", "Do", "X", None, None, {"theme": {}}, "d", {}, False, sexe="F")
    eid = stockage.lister("cle-tick4")[0]["id"]
    stockage_spatial.placer(monde["id"], eid, 0)
    stockage_spatial.deplacer_placement(monde["id"], eid, 1)
    assert stockage_spatial.population_vivante_cellule(monde["id"], 0) == []
    assert stockage_spatial.population_vivante_cellule(monde["id"], 1)[0]["id"] == eid


def test_ressources_stock_lire_ecrire():
    monde = stockage_spatial.creer_monde("cle-tick5", _cellules_factices(2), seed=1)
    stock = stockage_spatial.lire_ressources_stock(monde["id"], 0)
    assert stock == {"ble": 50.0}  # cellule factice a ["ble"] comme ressources, stock initial demi-plafond
    stockage_spatial.ecrire_ressources_stock(monde["id"], 0, {"ble": 12.5})
    assert stockage_spatial.lire_ressources_stock(monde["id"], 0) == {"ble": 12.5}


def test_niveau_technologie_lire_ecrire_defaut_zero():
    monde = stockage_spatial.creer_monde("cle-tick6", _cellules_factices(2), seed=1)
    assert stockage_spatial.lire_niveau_technologie(monde["id"], 0) == 0.0
    stockage_spatial.ecrire_niveau_technologie(monde["id"], 0, 2.5)
    assert stockage_spatial.lire_niveau_technologie(monde["id"], 0) == 2.5


def test_forker_monde_copie_ressources_stock_et_technologie():
    monde = stockage_spatial.creer_monde("cle-tick7", _cellules_factices(2), seed=1)
    stockage_spatial.ecrire_niveau_technologie(monde["id"], 0, 3.0)
    stockage_spatial.ecrire_ressources_stock(monde["id"], 0, {"ble": 7.0})
    fork = stockage_spatial.forker_monde("cle-tick7", monde["id"])
    assert stockage_spatial.lire_niveau_technologie(fork["id"], 0) == 3.0
    assert stockage_spatial.lire_ressources_stock(fork["id"], 0) == {"ble": 7.0}


def test_forker_monde_copie_placements_avec_ne_au_tick_et_vivant():
    monde = stockage_spatial.creer_monde("cle-tick8", _cellules_factices(2), seed=1)
    stockage.creer("cle-tick8", "Eu", "X", None, None, {"theme": {}}, "d", {}, False, sexe="F")
    eid = stockage.lister("cle-tick8")[0]["id"]
    stockage_spatial.placer(monde["id"], eid, 0, ne_au_tick=4)
    fork = stockage_spatial.forker_monde("cle-tick8", monde["id"])
    pop_fork = stockage_spatial.population_vivante_cellule(fork["id"], 0)
    assert pop_fork == [{"id": eid, "sexe": "F", "ne_au_tick": 4}]


# --- Correctifs revue finale Sprint C : accès en lot (Critical, perf du tick) ---

def test_population_vivante_monde_groupe_par_cellule_et_exclut_les_morts():
    """Correctif revue finale (Critical) : accesseur en lot remplaçant N appels à
    `population_vivante_cellule` (un par cellule) dans `horloge_moteur.executer_tick`."""
    monde = stockage_spatial.creer_monde("cle-lot1", _cellules_factices(3), seed=1)
    a = stockage.creer("cle-lot1", "A", "X", None, None, {}, "d", {}, False, sexe="F")
    b = stockage.creer("cle-lot1", "B", "X", None, None, {}, "d", {}, False, sexe="M")
    mort = stockage.creer("cle-lot1", "C", "X", None, None, {}, "d", {}, False, sexe="M")
    stockage_spatial.placer(monde["id"], a, 0, ne_au_tick=2)
    stockage_spatial.placer(monde["id"], b, 2, ne_au_tick=5)
    stockage_spatial.placer(monde["id"], mort, 0)
    stockage_spatial.marquer_mort(monde["id"], mort, tick=9)

    par_cellule = stockage_spatial.population_vivante_monde(monde["id"])
    assert par_cellule == {0: [{"id": a, "sexe": "F", "ne_au_tick": 2}],
                            2: [{"id": b, "sexe": "M", "ne_au_tick": 5}]}
    # cellule 1 vide ⇒ absente du dict (l'appelant fait .get(cid, []))
    assert 1 not in par_cellule


def test_population_vivante_monde_cloisonnee_au_monde():
    monde_a = stockage_spatial.creer_monde("cle-lot2", _cellules_factices(2), seed=1)
    monde_b = stockage_spatial.creer_monde("cle-lot2", _cellules_factices(2), seed=1)
    eid = stockage.creer("cle-lot2", "A", "X", None, None, {}, "d", {}, False, sexe="F")
    stockage_spatial.placer(monde_a["id"], eid, 0)
    assert stockage_spatial.population_vivante_monde(monde_b["id"]) == {}


def test_ecrire_ressources_et_technologie_monde_en_lot():
    monde = stockage_spatial.creer_monde("cle-lot3", _cellules_factices(3), seed=1)
    stockage_spatial.ecrire_ressources_et_technologie_monde(
        monde["id"], {0: ({"ble": 1.5}, 0.25), 2: ({"ble": 9.0}, 3.0)})
    assert stockage_spatial.lire_ressources_stock(monde["id"], 0) == {"ble": 1.5}
    assert stockage_spatial.lire_niveau_technologie(monde["id"], 0) == 0.25
    assert stockage_spatial.lire_ressources_stock(monde["id"], 2) == {"ble": 9.0}
    assert stockage_spatial.lire_niveau_technologie(monde["id"], 2) == 3.0
    # cellule 1 non citée ⇒ inchangée
    assert stockage_spatial.lire_niveau_technologie(monde["id"], 1) == 0.0


def test_marquer_morts_et_deplacer_placements_en_lot():
    monde = stockage_spatial.creer_monde("cle-lot4", _cellules_factices(3), seed=1)
    a = stockage.creer("cle-lot4", "A", "X", None, None, {}, "d", {}, False, sexe="F")
    b = stockage.creer("cle-lot4", "B", "X", None, None, {}, "d", {}, False, sexe="M")
    c = stockage.creer("cle-lot4", "C", "X", None, None, {}, "d", {}, False, sexe="M")
    for eid in (a, b, c):
        stockage_spatial.placer(monde["id"], eid, 0)

    stockage_spatial.marquer_morts(monde["id"], [a, b], tick=4)
    assert [h["id"] for h in stockage_spatial.population_vivante_cellule(monde["id"], 0)] == [c]

    stockage_spatial.deplacer_placements(monde["id"], [(c, 2)])
    assert stockage_spatial.population_vivante_cellule(monde["id"], 0) == []
    assert stockage_spatial.population_vivante_cellule(monde["id"], 2)[0]["id"] == c


def test_migration_legacy_seme_ressources_stock_au_lieu_de_le_laisser_vide(monkeypatch, tmp_path):
    """Correctif revue finale (Important) : `ALTER TABLE cellules ADD COLUMN
    ressources_stock ... DEFAULT '{}'` laissait les cellules d'un monde antérieur au
    Sprint C avec un stock VIDE — `horloge.cellule_saturee` les jugeait alors
    toujours saturées et `evoluer_ressources_et_technologie` court-circuitait, donc
    zéro progression technologique à jamais. Même motif de test que
    `test_migration_alter_table_enfants_from_legacy_schema`."""
    import json
    import sqlite3

    legacy_db = tmp_path / "legacy_cellules.db"
    legacy = sqlite3.connect(str(legacy_db))
    # Schéma `cellules` de Sprint B : ni ressources_stock ni niveau_technologie.
    legacy.execute("""CREATE TABLE cellules (
        monde_id TEXT NOT NULL, cellule_id INTEGER NOT NULL,
        x REAL NOT NULL, y REAL NOT NULL, biome TEXT NOT NULL,
        ressources TEXT NOT NULL, voisins TEXT NOT NULL,
        PRIMARY KEY (monde_id, cellule_id))""")
    legacy.executemany(
        "INSERT INTO cellules (monde_id, cellule_id, x, y, biome, ressources, voisins) "
        "VALUES (?,?,?,?,?,?,?)",
        [("monde-legacy", 0, 1.0, 2.0, "plaine", json.dumps(["ble", "betail"]), json.dumps([1])),
         ("monde-legacy", 1, 3.0, 4.0, "ocean", json.dumps([]), json.dumps([0]))])
    legacy.commit()
    legacy.close()

    original_db_path = stockage_spatial.DB_PATH
    monkeypatch.setattr(stockage_spatial, "DB_PATH", str(legacy_db))
    try:
        # N'importe quel appel passe par `_conn()` ⇒ migration + semis one-shot.
        stockage_spatial.lire_monde("cle-legacy", "monde-inexistant")

        stock_0 = stockage_spatial.lire_ressources_stock("monde-legacy", 0)
        assert stock_0 == {"ble": stockage_spatial.STOCK_INITIAL_PAR_RESSOURCE,
                            "betail": stockage_spatial.STOCK_INITIAL_PAR_RESSOURCE}, \
            "une cellule legacy doit être semée depuis sa liste qualitative `ressources`"
        # Cellule sans ressource qualitative : légitimement vide, jamais inventée.
        assert stockage_spatial.lire_ressources_stock("monde-legacy", 1) == {}

        # Le semis est one-shot : une écriture ultérieure n'est pas réécrasée par
        # une connexion suivante.
        stockage_spatial.ecrire_ressources_stock("monde-legacy", 0, {"ble": 1.0})
        assert stockage_spatial.lire_ressources_stock("monde-legacy", 0) == {"ble": 1.0}
    finally:
        monkeypatch.setattr(stockage_spatial, "DB_PATH", original_db_path)


def test_semis_legacy_survit_a_l_echec_du_bloc_appelant(monkeypatch, tmp_path):
    """Correctif 2e revue finale (Important) : le semis doit être commité TOUT DE
    SUITE, pas laissé dans la transaction de l'appelant.

    L'`ALTER TABLE` qui arme le semis est auto-commité immédiatement par le module
    `sqlite3` ; l'UPDATE de semis, lui, appartenait au `with _conn() as c:` de
    l'appelant. Si ce bloc lève (ou est annulé) juste après, l'ALTER survit mais le
    semis est perdu — et comme le déclencheur est one-shot (« la colonne vient
    d'être ajoutée »), il ne se représente JAMAIS : les cellules legacy restent à
    `ressources_stock={}` pour toujours, donc jugées saturées en permanence et
    figées technologiquement.

    On simule l'appelant qui échoue par un `rollback()` sur la connexion tout juste
    ouverte par `_conn()` — c'est exactement ce que fait un `with sqlite3` dont le
    bloc lève."""
    import json
    import sqlite3

    legacy_db = tmp_path / "legacy_semis_durable.db"
    legacy = sqlite3.connect(str(legacy_db))
    legacy.execute("""CREATE TABLE cellules (
        monde_id TEXT NOT NULL, cellule_id INTEGER NOT NULL,
        x REAL NOT NULL, y REAL NOT NULL, biome TEXT NOT NULL,
        ressources TEXT NOT NULL, voisins TEXT NOT NULL,
        PRIMARY KEY (monde_id, cellule_id))""")
    legacy.execute(
        "INSERT INTO cellules (monde_id, cellule_id, x, y, biome, ressources, voisins) "
        "VALUES (?,?,?,?,?,?,?)",
        ("monde-legacy", 0, 1.0, 2.0, "plaine", json.dumps(["ble"]), json.dumps([])))
    legacy.commit()
    legacy.close()

    original_db_path = stockage_spatial.DB_PATH
    monkeypatch.setattr(stockage_spatial, "DB_PATH", str(legacy_db))
    try:
        # 1re connexion = migration + semis one-shot, puis l'appelant « échoue ».
        c = stockage_spatial._conn()
        c.rollback()
        c.close()

        # 2e connexion : la colonne existe déjà, le semis ne se rejouera pas. Le
        # stock doit donc déjà être là — sinon il est perdu définitivement.
        assert stockage_spatial.lire_ressources_stock("monde-legacy", 0) == \
            {"ble": stockage_spatial.STOCK_INITIAL_PAR_RESSOURCE}, \
            "le semis legacy doit être durable même si le bloc appelant est annulé"
    finally:
        monkeypatch.setattr(stockage_spatial, "DB_PATH", original_db_path)


# --- Sprint D : champ `emigre` (distinct de la mort) ---

def test_marquer_emigre_exclut_de_la_population_vivante_sans_le_tuer():
    monde = stockage_spatial.creer_monde("cle-emig1", _cellules_factices(2), seed=1)
    stockage.creer("cle-emig1", "Em", "X", None, None, {}, "d", {}, False, sexe="F")
    eid = stockage.lister("cle-emig1")[0]["id"]
    stockage_spatial.placer(monde["id"], eid, 0, ne_au_tick=0)

    stockage_spatial.marquer_emigre(monde["id"], eid, tick=5, monde_id_destination="monde-dest")

    # exclu de la population vivante du pays d'origine...
    assert stockage_spatial.population_vivante_cellule(monde["id"], 0) == []
    assert stockage_spatial.population_vivante_monde(monde["id"]) == {}
    # ...mais la ligne existe toujours, vivant=1, mort_au_tick NULL (pas mort)
    with stockage_spatial._conn() as c:
        r = c.execute("SELECT * FROM placements WHERE monde_id=? AND enfant_id=?",
                       (monde["id"], eid)).fetchone()
    assert r["vivant"] == 1
    assert r["mort_au_tick"] is None
    assert r["emigre"] == 1
    assert r["emigre_au_tick"] == 5
    assert r["emigre_vers_monde_id"] == "monde-dest"


def test_placer_dans_nouveau_pays_reinitialise_emigre():
    monde_a = stockage_spatial.creer_monde("cle-emig2", _cellules_factices(2), seed=1)
    monde_b = stockage_spatial.creer_monde("cle-emig2", _cellules_factices(2), seed=2)
    stockage.creer("cle-emig2", "Em", "X", None, None, {}, "d", {}, False, sexe="F")
    eid = stockage.lister("cle-emig2")[0]["id"]
    stockage_spatial.placer(monde_a["id"], eid, 0, ne_au_tick=0)
    stockage_spatial.marquer_emigre(monde_a["id"], eid, tick=5, monde_id_destination=monde_b["id"])

    stockage_spatial.placer(monde_b["id"], eid, 1, ne_au_tick=3)

    assert stockage_spatial.population_vivante_cellule(monde_b["id"], 1) == [
        {"id": eid, "sexe": "F", "ne_au_tick": 3}]


def test_forker_monde_copie_le_statut_emigre():
    monde = stockage_spatial.creer_monde("cle-emig3", _cellules_factices(2), seed=1)
    stockage.creer("cle-emig3", "Em", "X", None, None, {}, "d", {}, False, sexe="F")
    eid = stockage.lister("cle-emig3")[0]["id"]
    stockage_spatial.placer(monde["id"], eid, 0)
    stockage_spatial.marquer_emigre(monde["id"], eid, tick=2, monde_id_destination="ailleurs")

    fork = stockage_spatial.forker_monde("cle-emig3", monde["id"])

    with stockage_spatial._conn() as c:
        r = c.execute("SELECT * FROM placements WHERE monde_id=? AND enfant_id=?",
                       (fork["id"], eid)).fetchone()
    assert r["emigre"] == 1
    assert r["emigre_au_tick"] == 2
    assert r["emigre_vers_monde_id"] == "ailleurs"


def test_lire_placement_par_enfant_absent():
    assert stockage_spatial.lire_placement_par_enfant("id-inconnu") is None


def test_lire_placement_par_enfant_vivant():
    monde = stockage_spatial.creer_monde("cle-a", _cellules_factices(3), seed=10)
    eid = stockage.creer("cle-a", "Nova", "", None, None, {"theme_complet": {}}, "desc", {}, False)
    stockage_spatial.placer(monde["id"], eid, 1, ne_au_tick=5)
    p = stockage_spatial.lire_placement_par_enfant(eid)
    assert p == {"monde_id": monde["id"], "cellule_id": 1, "ne_au_tick": 5,
                 "vivant": 1, "mort_au_tick": None}


def test_lire_placement_par_enfant_mort():
    monde = stockage_spatial.creer_monde("cle-a", _cellules_factices(3), seed=11)
    eid = stockage.creer("cle-a", "Nova", "", None, None, {"theme_complet": {}}, "desc", {}, False)
    stockage_spatial.placer(monde["id"], eid, 0, ne_au_tick=0)
    stockage_spatial.marquer_mort(monde["id"], eid, 7)
    p = stockage_spatial.lire_placement_par_enfant(eid)
    assert p["vivant"] == 0
    assert p["mort_au_tick"] == 7
