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


# ── Fiches cosmiques enregistrées ────────────────────────────────
def test_fiche_creer_lire_snapshot():
    donnees = {"portrait": {"archetype": "Le Sage"}, "contexte": {"prenoms": "Aria"},
               "empreinte": [{"cle": "Soleil"}], "lecture_approfondie": "texte IA"}
    f = S.creer_fiche("cleA", "Aria Solis", donnees)
    assert f["archetype"] == "Le Sage"           # résumé déduit du portrait
    relu = S.lire_fiche("cleA", f["id"])
    assert relu["nom"] == "Aria Solis"
    assert relu["donnees"]["lecture_approfondie"] == "texte IA"   # snapshot complet conservé
    assert relu["donnees"]["empreinte"] == [{"cle": "Soleil"}]


def test_fiche_cloisonnement_par_cle():
    f = S.creer_fiche("cleA", "Privé", {"portrait": {"archetype": "X"}})
    assert S.lire_fiche("cleB", f["id"]) is None
    assert all(x["id"] != f["id"] for x in S.lister_fiches("cleB"))


def test_fiche_supprimer():
    f = S.creer_fiche("cleA", "Jetable", {})
    assert S.supprimer_fiche("cleA", f["id"]) is True
    assert S.supprimer_fiche("cleA", f["id"]) is False
    assert S.lire_fiche("cleA", f["id"]) is None


def test_fiche_garde_nom_naissance_a_la_creation():
    f = S.creer_fiche("cleA", "Lyssandre", {"portrait": {"archetype": "Le Sage"}})
    assert f["nom"] == f["nom_naissance"] == "Lyssandre"   # les deux à la création
    relu = S.lire_fiche("cleA", f["id"])
    assert relu["nom_naissance"] == "Lyssandre"


def test_fiche_renommer_garde_origine_et_donnees():
    donnees = {"portrait": {"archetype": "Le Sage"}, "lecture_approfondie": "texte IA"}
    f = S.creer_fiche("cleA", "Lyssandre", donnees)
    out = S.renommer_fiche("cleA", f["id"], "  Aria  ")     # nom de scène (trim attendu)
    assert out["nom"] == "Aria"                             # étiquette changée
    assert out["nom_naissance"] == "Lyssandre"             # nom cosmique figé
    relu = S.lire_fiche("cleA", f["id"])
    assert relu["nom"] == "Aria" and relu["nom_naissance"] == "Lyssandre"
    assert relu["donnees"]["lecture_approfondie"] == "texte IA"   # données intactes


def test_fiche_renommer_refuse_vide_et_cloisonne():
    f = S.creer_fiche("cleA", "Lyssandre", {})
    assert S.renommer_fiche("cleA", f["id"], "   ") is None       # nom vide refusé
    assert S.renommer_fiche("cleB", f["id"], "Aria") is None      # autre tenant : rien
    assert S.lire_fiche("cleA", f["id"])["nom"] == "Lyssandre"    # inchangé
