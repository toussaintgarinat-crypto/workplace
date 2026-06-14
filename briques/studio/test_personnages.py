"""Tests — Distribution (personnages structurés) du Studio, repris hors Oria (S51).

Fonctions pures : pas de DB ni de Gateway.
  • la distribution ALIMENTE les prompts d'écriture (_distribution_texte) ;
  • elle FIGE la voix de chaque personnage au casting (_assigner_voix / _caster)."""
import studio as A


def _serie(persos):
    return {"titre": "T", "bible": {}, "episodes": [], "personnages": persos}


# ── Clé de rapprochement script ⇄ fiche ──────────────────────────
def test_cle_perso_normalise_casse_et_espaces():
    assert A._cle_perso("Aria") == "ARIA"
    assert A._cle_perso("  le  GARDIEN ") == "LE GARDIEN"
    assert A._cle_perso(None) == ""


# ── Bloc DISTRIBUTION injecté dans les prompts ───────────────────
def test_distribution_texte_vide_si_aucun_perso():
    assert A._distribution_texte({"personnages": []}) == ""
    assert A._distribution_texte({}) == ""


def test_distribution_texte_liste_noms_roles_descriptions():
    txt = A._distribution_texte(_serie([
        {"id": "p1", "nom": "Aria", "role": "héroïne", "description": "courageuse"},
        {"id": "p2", "nom": "Vorn", "role": "antagoniste", "description": ""},
    ]))
    assert "DISTRIBUTION" in txt
    assert "Aria — héroïne : courageuse" in txt
    assert "Vorn — antagoniste" in txt
    assert "EXACTEMENT" in txt


def test_tache_scenariste_injecte_la_distribution():
    serie = _serie([{"id": "p1", "nom": "Aria", "role": "héroïne", "description": "brave"}])
    tache = A._tache_scenariste(serie, 1, "ouverture", "", finale=False)
    assert "Aria" in tache and "DISTRIBUTION" in tache


# ── Épinglage déterministe des voix (_assigner_voix) ─────────────
def test_assigner_voix_affecte_des_voix_distinctes():
    serie = _serie([{"id": "p1", "nom": "A"}, {"id": "p2", "nom": "B"}])
    modifie = A._assigner_voix(serie, "fr", ["Thomas", "Marie", "Jacques"])
    assert modifie is True
    v = [p["voix"]["fr"] for p in serie["personnages"]]
    assert v == ["Thomas", "Marie"]


def test_assigner_voix_idempotent():
    serie = _serie([{"id": "p1", "nom": "A"}])
    A._assigner_voix(serie, "fr", ["Thomas", "Marie"])
    assert A._assigner_voix(serie, "fr", ["Thomas", "Marie"]) is False


def test_assigner_voix_respecte_un_choix_manuel():
    serie = _serie([{"id": "p1", "nom": "A", "voix": {"fr": "Marie"}},
                    {"id": "p2", "nom": "B"}])
    A._assigner_voix(serie, "fr", ["Thomas", "Marie", "Jacques"])
    assert serie["personnages"][0]["voix"]["fr"] == "Marie"
    assert serie["personnages"][1]["voix"]["fr"] == "Thomas"


def test_assigner_voix_round_robin_si_pool_trop_petit():
    serie = _serie([{"id": "p1", "nom": "A"}, {"id": "p2", "nom": "B"},
                    {"id": "p3", "nom": "C"}])
    A._assigner_voix(serie, "fr", ["Thomas", "Marie"])
    v = [p["voix"]["fr"] for p in serie["personnages"]]
    assert v == ["Thomas", "Marie", "Thomas"]


def test_assigner_voix_par_langue_independante():
    serie = _serie([{"id": "p1", "nom": "A", "voix": {"fr": "Thomas"}}])
    A._assigner_voix(serie, "es", ["Juan", "Diego"])
    assert serie["personnages"][0]["voix"] == {"fr": "Thomas", "es": "Juan"}


def test_assigner_voix_pool_vide_ne_fait_rien():
    serie = _serie([{"id": "p1", "nom": "A"}])
    assert A._assigner_voix(serie, "fr", []) is False
    assert serie["personnages"][0].get("voix", {}) == {}


# ── Casting d'un script (_caster) ────────────────────────────────
def test_caster_voix_figee_pour_les_personnages_connus():
    serie = _serie([{"id": "p1", "nom": "Aria"}, {"id": "p2", "nom": "Vorn"}])
    pool = ["Thomas", "Marie", "Jacques"]
    audibles = [("ARIA", "salut"), ("VORN", "grr"), ("ARIA", "encore")]
    casting = A._caster(serie, "fr", audibles, pool)
    assert casting["ARIA"] == "Thomas"
    assert casting["VORN"] == "Marie"
    assert serie["personnages"][0]["voix"]["fr"] == "Thomas"


def test_caster_stable_dun_episode_a_lautre():
    """Le cœur du sprint d'origine : un perso garde SA voix même rappelé sur un autre script."""
    serie = _serie([{"id": "p1", "nom": "Aria"}, {"id": "p2", "nom": "Vorn"}])
    pool = ["Thomas", "Marie", "Jacques"]
    A._caster(serie, "fr", [("VORN", "x")], pool)
    casting2 = A._caster(serie, "fr", [("ARIA", "y"), ("VORN", "z")], pool)
    assert casting2["VORN"] == "Marie"
    assert casting2["ARIA"] == "Thomas"


def test_caster_narrateur_inconnu_recoit_une_voix_libre():
    serie = _serie([{"id": "p1", "nom": "Aria"}])
    pool = ["Thomas", "Marie", "Jacques"]
    casting = A._caster(serie, "fr", [("ARIA", "a"), ("NARRATEUR", "il était une fois")], pool)
    assert casting["ARIA"] == "Thomas"
    assert casting["NARRATEUR"] != "Thomas"
    assert casting["NARRATEUR"] in pool


def test_caster_sans_distribution_pur_round_robin():
    serie = _serie([])
    pool = ["Thomas", "Marie"]
    casting = A._caster(serie, "fr", [("A", "1"), ("B", "2"), ("C", "3")], pool)
    assert casting == {"A": "Thomas", "B": "Marie", "C": "Thomas"}


def test_caster_match_insensible_a_la_casse():
    serie = _serie([{"id": "p1", "nom": "Le Gardien"}])
    casting = A._caster(serie, "fr", [("LE GARDIEN", "halte")], ["Thomas", "Marie"])
    assert casting["LE GARDIEN"] == "Thomas"
