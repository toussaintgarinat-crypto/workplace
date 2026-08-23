"""Tests du stockage SQLite des enfants générés (couche persistance du Sprint A)."""
import stockage


def _theme_factice(signe="Vierge") -> dict:
    return {
        "traditions": {"signe_solaire": {"nom": signe}},
        "portrait": {"archetype": "Le Gardien", "forces": ["Sagesse", "Stabilité"]},
        "theme_complet": {
            "dominantes": {"planete": {"dominante": "Mercure"}, "signe": {"dominant": signe}},
            "dix_corps": {c: {"signe": signe} for c in
                          ["Soleil", "Lune", "Mercure", "Vénus", "Mars", "Jupiter",
                           "Saturne", "Uranus", "Neptune", "Pluton"]},
        },
    }


def test_creer_puis_lire():
    eid = stockage.creer("cle-a", "Nova", "Test", None, None,
                          _theme_factice(), "desc genome", {"resume": {"A": 5}}, False)
    assert isinstance(eid, str) and eid

    e = stockage.lire("cle-a", eid)
    assert e["id"] == eid
    assert e["prenoms"] == "Nova"
    assert e["nom"] == "Test"
    assert e["parent_a_id"] is None
    assert e["parent_b_id"] is None
    assert e["theme"]["theme_complet"]["dominantes"]["signe"]["dominant"] == "Vierge"
    assert e["description_genome"] == "desc genome"
    assert e["heredite"] == {"resume": {"A": 5}}
    assert e["mutation_survenue"] is False
    assert e["cree_le"]


def test_lire_introuvable_renvoie_none():
    assert stockage.lire("cle-a", "id-inconnu") is None


def test_lire_cloisonne_par_cle_api():
    eid = stockage.creer("cle-b", "Secret", "", None, None,
                          _theme_factice(), "d", {"resume": {}}, False)
    assert stockage.lire("cle-b", eid) is not None
    assert stockage.lire("autre-cle", eid) is None


def test_lister_cloisonne_et_ordonne():
    stockage.creer("cle-c", "Premier", "", None, None, _theme_factice(), "d", {"resume": {}}, False)
    eid2 = stockage.creer("cle-c", "Second", "", None, None, _theme_factice(), "d", {"resume": {}}, False)
    resultats = stockage.lister("cle-c")
    assert [e["prenoms"] for e in resultats] == ["Second", "Premier"]  # plus récent d'abord
    assert "theme" not in resultats[0]  # liste allégée, pas le snapshot complet
    assert resultats[0]["id"] == eid2
    assert stockage.lister("cle-vide") == []


def test_lister_expose_les_ids_parents():
    gp = stockage.creer("cle-d", "GrandParent", "", None, None, _theme_factice(), "d", {"resume": {}}, False)
    p = stockage.creer("cle-d", "Parent", "", gp, None, _theme_factice(), "d", {"resume": {}}, False)
    resultats = {e["id"]: e for e in stockage.lister("cle-d")}
    assert resultats[p]["parent_a_id"] == gp
    assert resultats[p]["parent_b_id"] is None


def test_supprimer():
    eid = stockage.creer("cle-e", "Nova", "", None, None, _theme_factice(), "d", {"resume": {}}, False)
    assert stockage.supprimer("cle-e", eid) is True
    assert stockage.lire("cle-e", eid) is None


def test_supprimer_introuvable_renvoie_false():
    assert stockage.supprimer("cle-e", "id-inconnu") is False


def test_supprimer_cloisonne_par_cle_api():
    eid = stockage.creer("cle-f", "Nova", "", None, None, _theme_factice(), "d", {"resume": {}}, False)
    assert stockage.supprimer("autre-cle", eid) is False   # ne supprime pas chez une autre clé
    assert stockage.lire("cle-f", eid) is not None          # toujours là


def test_creer_et_lire_persiste_le_sexe():
    eid = stockage.creer("cle-sexe", "Ana", "Dupont", None, None,
                          _theme_factice(), "desc", {"resume": {}}, False, sexe="F")
    enfant = stockage.lire("cle-sexe", eid)
    assert enfant["sexe"] == "F"


def test_creer_sans_sexe_reste_none():
    eid = stockage.creer("cle-sexe", "Bo", "Martin", None, None,
                          _theme_factice(), "desc", {"resume": {}}, False)
    enfant = stockage.lire("cle-sexe", eid)
    assert enfant["sexe"] is None


def test_migration_alter_table_from_legacy_schema(monkeypatch, tmp_path):
    """Correctif revue finale (Important) : la branche `ALTER TABLE ADD COLUMN` de
    `_ajouter_colonne()` était jamais testée — `conftest.py` détruit+recrée la DB fraîche
    à chaque test, donc `CREATE TABLE IF NOT EXISTS enfants` crée toujours la table avec
    `sexe` présent, et la migration est un no-op.

    Ce test simule une DB legacy (Sprint A/B) SANS la colonne `sexe`, puis vérifiée que
    la migration via `_conn()` l'ajoute réellement."""
    import sqlite3

    # Créer une DB legacy avec l'ancien schéma (SANS sexe)
    legacy_db = tmp_path / "legacy_enfants.db"
    legacy_conn = sqlite3.connect(str(legacy_db))
    legacy_conn.execute("""CREATE TABLE enfants (
        id TEXT PRIMARY KEY, cle_api TEXT NOT NULL, prenoms TEXT, nom TEXT,
        parent_a_id TEXT, parent_b_id TEXT, donnees TEXT NOT NULL, cree_le TEXT)""")
    legacy_conn.execute("INSERT INTO enfants (id, cle_api, prenoms, nom, parent_a_id, "
                        "parent_b_id, donnees, cree_le) VALUES (?,?,?,?,?,?,?,?)",
                        ("old-child-id", "legacy-cle", "Legacy", "Enfant", None, None,
                         '{"theme": {}, "description_genome": "old", "heredite": {}, "mutation_survenue": false}',
                         "2026-01-01T00:00:00+00:00"))
    legacy_conn.commit()
    legacy_conn.close()

    # Rediriger stockage.DB_PATH vers la legacy DB
    original_db_path = stockage.DB_PATH
    monkeypatch.setattr(stockage, "DB_PATH", str(legacy_db))

    try:
        # Appeler `lire()` qui passe par `_conn()` → migration exécutée
        enfant = stockage.lire("legacy-cle", "old-child-id")

        # Migration réussie : sexe doit être présent et lisible
        assert enfant is not None, "Enfant legacy doit être lisible après migration"
        assert "sexe" in enfant, "sexe doit être présent dans enfant"
        assert enfant["sexe"] is None, "sexe doit être None pour un enfant legacy"

        # Créer un nouvel enfant AVEC sexe pour vérifier la colonne est vraiment usable
        eid_new = stockage.creer("legacy-cle", "Nova", "Test", None, None,
                                 _theme_factice(), "new desc", {"resume": {}}, False, sexe="F")

        # Lire le nouvel enfant : sexe doit être "F"
        enfant_new = stockage.lire("legacy-cle", eid_new)
        assert enfant_new["sexe"] == "F", "Nouvel enfant avec sexe='F' doit être persisté correctement"

        # Lister tous les enfants de cette cle → vérifier sexe dans la liste
        enfants = stockage.lister("legacy-cle")
        assert len(enfants) >= 2, "Doit avoir au moins l'ancien et le nouveau enfant"
        nova = next(e for e in enfants if e["id"] == eid_new)
        assert nova["sexe"] == "F", "sexe doit être visible dans lister()"

    finally:
        # Restaurer le DB_PATH original
        monkeypatch.setattr(stockage, "DB_PATH", original_db_path)
