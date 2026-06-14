"""Tests de la couche stockage (SQLite, cloisonnement par clé API)."""
import stockage as S


def test_creer_et_lire():
    d = S.creer("cleA", titre="Saga", langue="fr", premisse="un désert")
    relu = S.lire("cleA", d["id"])
    assert relu["titre"] == "Saga" and relu["personnages"] == []


def test_cloisonnement_par_cle():
    d = S.creer("cleA", titre="Privée")
    assert S.lire("cleB", d["id"]) is None        # un autre tenant ne voit rien
    assert all(x["id"] != d["id"] for x in S.lister("cleB"))


def test_maj_personnages():
    d = S.creer("cleA")
    S.maj("cleA", d["id"], {"personnages": [{"id": "p1", "nom": "Aria"}]})
    assert S.lire("cleA", d["id"])["personnages"][0]["nom"] == "Aria"


def test_supprimer():
    d = S.creer("cleA")
    assert S.supprimer("cleA", d["id"]) is True
    assert S.supprimer("cleA", d["id"]) is False   # déjà parti
    assert S.lire("cleA", d["id"]) is None


def test_lister_resume_compte_les_persos():
    d = S.creer("cleC")
    S.maj("cleC", d["id"], {"personnages": [{"nom": "A"}, {"nom": "B"}]})
    item = next(x for x in S.lister("cleC") if x["id"] == d["id"])
    assert item["personnages"] == 2
