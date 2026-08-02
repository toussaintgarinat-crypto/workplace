"""Tests de la résolution de voie d'archétype par combat joué (S218) — remplace l'ancienne
résolution par comparaison de stats (`groupes.resoudre_groupes_actifs`, retirée)."""
import archetypes as A
import combat
import groupes as G
import mobs_archetype as MA
import stockage as S


def _personnage(cle, nom):
    S.assurer_joueur(cle, nom)
    return S.creer_personnage(cle, nom, {"date_naissance": "1990-01-01"},
                              {"traditions": {"signe_solaire": {"nom": "Lion"}},
                               "portrait": {"stats": {}}})


def _etape_fixture(archetype="Le Meneur Charismatique", ordre=1):
    A.seed_zones_archetype()
    MA.seed_mobs_archetype()
    return A.lister_etapes(archetype)[ordre - 1]


async def _rejoindre_et_tuer_le_boss(etape, personnage_id):
    gabarits = MA.lister_mobs_etape(etape["id"])
    inst = await combat.rejoindre(etape["id"], personnage_id, etape["archetype"], personnage_id,
                                  gabarits, contexte="archetype", cle_contribution=personnage_id)
    boss_id = next(mid for mid, m in inst.etat["mobs"].items() if m["role"] == "boss")
    inst.etat["mobs"][boss_id]["pv"] = 0
    inst.etat["mobs"][boss_id]["degats_recus_par_guilde"] = {personnage_id: 999}
    evenements = await combat.un_tick(inst, [], dt=0.1, competences={}, horodatage=0.0)
    return inst, evenements


async def test_boss_tue_avance_la_cible_et_debloque_competence():
    etape = _etape_fixture()
    A.seed_competences()
    p = _personnage("cleCA1", "Cible")
    G.creer_groupe(p["id"], etape["id"])
    _, evenements = await _rejoindre_et_tuer_le_boss(etape, p["id"])
    assert any(e["type"] == "boss_tue" for e in evenements)
    assert A.prochaine_etape(p["id"], etape["archetype"]) == A.lister_etapes(etape["archetype"])[1]["id"]
    assert len(A.lister_competences_debloquees(p["id"])) == 1


async def test_boss_tue_dissout_les_groupes_actifs_de_letape():
    etape = _etape_fixture()
    p = _personnage("cleCA2", "Cible2")
    g = G.creer_groupe(p["id"], etape["id"])
    await _rejoindre_et_tuer_le_boss(etape, p["id"])
    assert G.lire_groupe(g["id"])["etat"] == "dissous"


async def test_boss_tue_ne_fait_pas_progresser_un_carry_sans_sa_propre_etape():
    """Même garantie qu'avant S218 (ancien test_groupes.py::
    test_resoudre_groupes_actifs_carry_naide_pas_la_progression_de_laide) : un aide qui
    contribue au combat de l'étape 2 d'un autre, sans avoir complété sa propre étape 1, ne
    voit pas sa progression avancer."""
    etape1 = _etape_fixture()
    A.seed_competences()
    p = _personnage("cleCA3", "Cible3")
    aide = _personnage("cleCA3b", "Copain")
    await _rejoindre_et_tuer_le_boss(etape1, p["id"])
    etape2 = A.lister_etapes(etape1["archetype"])[1]
    G.creer_groupe(p["id"], etape2["id"])
    gabarits = MA.lister_mobs_etape(etape2["id"])
    inst = await combat.rejoindre(etape2["id"], p["id"], etape2["archetype"], p["id"], gabarits,
                                  contexte="archetype", cle_contribution=p["id"])
    inst = await combat.rejoindre(etape2["id"], aide["id"], etape2["archetype"], aide["id"],
                                  gabarits, contexte="archetype", cle_contribution=aide["id"])
    boss_id = next(mid for mid, m in inst.etat["mobs"].items() if m["role"] == "boss")
    inst.etat["mobs"][boss_id]["pv"] = 0
    inst.etat["mobs"][boss_id]["degats_recus_par_guilde"] = {p["id"]: 500, aide["id"]: 500}
    await combat.un_tick(inst, [], dt=0.1, competences={}, horodatage=0.0)
    assert A.prochaine_etape(p["id"], etape1["archetype"]) == A.lister_etapes(etape1["archetype"])[2]["id"]
    assert A.prochaine_etape(aide["id"], etape1["archetype"]) == etape1["id"]


async def test_idle_bonus_applique_a_lentree_reduit_les_pv_du_boss():
    etape = _etape_fixture()
    p = _personnage("cleCA4", "Fatigue")
    gabarits = MA.lister_mobs_etape(etape["id"])
    inst = await combat.rejoindre(etape["id"], p["id"], etape["archetype"], p["id"], gabarits,
                                  contexte="archetype", cle_contribution=p["id"])
    boss_id = next(mid for mid, m in inst.etat["mobs"].items() if m["role"] == "boss")
    pv_avant = inst.etat["mobs"][boss_id]["pv"]
    combat.appliquer_bonus_idle(inst, 20, p["id"])
    assert inst.etat["mobs"][boss_id]["pv"] == pv_avant - 20
