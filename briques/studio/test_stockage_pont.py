"""Tests — stockage_pont.py : le lien personnage Studio ↔ habitant world-engine, un
fichier JSON par série (même idiome que _profil_path/_journal_path de studio.py), séparé
de la fiche série ET de la fiche world-engine (voir design du pont)."""
import stockage_pont as P


def test_lire_pont_absent_renvoie_forme_vide():
    assert P.lire_pont("serie-inconnue") == {
        "serie_id": "serie-inconnue", "monde_id": None, "habitants": {}}


def test_fixer_monde_puis_lire():
    P.fixer_monde("s1", "monde-abc")
    assert P.lire_pont("s1")["monde_id"] == "monde-abc"


def test_lier_habitant_puis_lire():
    P.lier_habitant("s2", "ELARA", "eid-1", "Elara", "2026-08-26T00:00:00+00:00")
    pont = P.lire_pont("s2")
    assert pont["habitants"] == {
        "ELARA": {"eid": "eid-1", "nom_affiche": "Elara", "lie_le": "2026-08-26T00:00:00+00:00"}}


def test_detacher_habitant():
    P.lier_habitant("s3", "KAEL", "eid-2", "Kaël", "2026-08-26T00:00:00+00:00")
    P.detacher_habitant("s3", "KAEL")
    assert P.lire_pont("s3")["habitants"] == {}


def test_detacher_habitant_absent_noop():
    P.detacher_habitant("s4", "INCONNU")   # ne lève pas
    assert P.lire_pont("s4")["habitants"] == {}


def test_isolation_par_serie():
    P.lier_habitant("s5", "A", "eid-a", "A", "t")
    P.lier_habitant("s6", "B", "eid-b", "B", "t")
    assert "B" not in P.lire_pont("s5")["habitants"]
    assert "A" not in P.lire_pont("s6")["habitants"]
