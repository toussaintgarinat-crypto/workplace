import archetypes as A
import stockage as S
import zones as Z
import tick as T


def test_executer_tick_resout_zones_et_groupes():
    Z.seed_zones()
    A.seed_zones_archetype()
    S.assurer_joueur("cleT", "Tick")
    p = S.creer_personnage("cleT", "Tock", {"date_naissance": "1990-01-01"},
                           {"traditions": {"signe_solaire": {"nom": "Bélier"}},
                            "portrait": {"stats": {"Combativité": 300, "Énergie": 300}}})
    belier = next(z for z in Z.lister_zones() if z["signe_natif"] == "Bélier")
    S.assigner_zone("cleT", p["id"], belier["id"])
    resultat = T.executer_tick()
    assert "zones" in resultat and "groupes" in resultat
    assert any(r["zone_id"] == belier["id"] and r["etat_resultant"] == "vaincue"
              for r in resultat["zones"])


def test_executer_tick_sans_rien_a_resoudre_ne_plante_pas():
    Z.seed_zones()
    A.seed_zones_archetype()
    resultat = T.executer_tick()
    assert resultat["zones"] == [] or all(r["etat_resultant"] == "en_cours" for r in resultat["zones"])
    assert resultat["groupes"] == []
