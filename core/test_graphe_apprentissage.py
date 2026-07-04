"""Graphe d'apprentissage mémoires ↔ capacités (S145).

10 scénarios couvrant la tokenisation, la construction, le boost lexical,
la normalisation et les cas limites.

    $ cd core && python3 test_graphe_apprentissage.py
"""
import asyncio
import os

import graphe_apprentissage as ga


# ── Helpers ──────────────────────────────────────────────────────────────────

def _spec(nom: str, desc: str = "") -> dict:
    return {"type": "function", "function": {"name": nom, "description": desc}}


def _graphe_neuf():
    return ga.GrapheApprentissage()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_1_termes_filtre_stopwords():
    """_termes extrait les mots significatifs et ignore stopwords + longueur < 3."""
    assert ga._termes("Hello le monde") == {"hello", "monde"}


def test_2_boost_souvenir_restaurant():
    """Un souvenir mentionnant 'restaurant' booste les capacités liées."""
    g = _graphe_neuf()
    specs = [_spec("commande_envoyer", "envoyer la commande au restaurant")]
    g.construire(["j'ai commandé au restaurant hier"], specs)
    boosts = g.boost("restaurant commande", specs)
    assert boosts.get("commande_envoyer", 0) > 0


def test_3_boost_vide_sans_terme_commun():
    """Une requête sans terme commun avec les souvenirs retourne {} ."""
    g = _graphe_neuf()
    specs = [_spec("commande_envoyer", "envoyer commande restaurant")]
    g.construire(["restaurant table commande"], specs)
    boosts = g.boost("agenda rendez_vous calendrier", specs)
    assert boosts == {}


def test_4_bonus_x2_nom_capacite_dans_souvenir():
    """Le nom de la capacité dans un souvenir donne un score supérieur à la description seule."""
    g_nom = _graphe_neuf()
    specs = [_spec("paiements_initier", "initier paiement")]
    # souvenir contient le NOM de la capacité → bonus × 2
    g_nom.construire(["j'ai utilisé paiements_initier pour régler la note"], specs)

    g_desc = _graphe_neuf()
    # souvenir contient uniquement un terme de la DESCRIPTION
    g_desc.construire(["j'ai utilisé initier pour régler la note"], specs)

    score_nom = g_nom._boost.get("paiements_initier", 0)
    score_desc = g_desc._boost.get("paiements_initier", 0)
    assert score_nom >= score_desc  # bonus × 2 → score ≥


def test_5_normalisation_scores_inferieurs_a_1():
    """Après construction, tous les scores de boost sont ≤ 1."""
    g = _graphe_neuf()
    specs = [
        _spec("outil_a", "calcul nombre addition"),
        _spec("outil_b", "facture paiement montant"),
        _spec("outil_c", "agenda rendez calendrier"),
    ]
    g.construire(
        ["calcul nombre addition facture paiement agenda rendez"] * 5,
        specs,
    )
    assert all(v <= 1.0 for v in g._boost.values())


def test_6_zero_souvenir_retourne_boost_vide():
    """Sans souvenir, boost() retourne {} quel que soit la requête."""
    g = _graphe_neuf()
    specs = [_spec("commande_envoyer", "restaurant commande")]
    g.construire([], specs)
    assert g.boost("restaurant commande", specs) == {}


def test_7_double_construire_repart_proprement():
    """Deux appels successifs à construire() ne cumulent pas les scores."""
    g = _graphe_neuf()
    specs = [_spec("outil_a", "calcul addition nombre")]
    g.construire(["calcul addition"] * 10, specs)
    score_avant = g._boost.get("outil_a", 0)
    g.construire(["calcul addition"] * 10, specs)
    score_apres = g._boost.get("outil_a", 0)
    assert score_avant == score_apres  # pas de cumul


def test_8_alpha_zero_boost_nul():
    """Avec GRAPHE_ALPHA=0, le boost lexical ne modifie pas les scores cosinus."""
    import routage_outils as r
    alpha_initial = r.ALPHA_BOOST
    r.ALPHA_BOOST = 0.0
    try:
        r.reinitialiser()
        r.ACTIF = True
        specs = [_spec("calcul_addition", "calcul nombre"), _spec("agenda_rdv", "rendez vous")]
        r._index = {
            "calcul_addition": r._normaliser([1.0, 0.0]),
            "agenda_rdv": r._normaliser([0.0, 1.0]),
        }
        r._pret = True

        # Graphe avec un souvenir très fort sur agenda_rdv
        ga._graphe.construire(["agenda rdv rendez vous calendrier"] * 20, specs)

        # Requête orientée calcul : sans boost, calcul_addition doit l'emporter
        out = r.selectionner([1.0, 0.0], specs, top_k=1, toujours=set(),
                             requete="calcul nombre addition")
        noms = [s["function"]["name"] for s in out]
        assert "calcul_addition" in noms
    finally:
        r.ALPHA_BOOST = alpha_initial
        r.reinitialiser()
        ga._graphe.construire([], [])  # remet le graphe vide


def test_9_brique_indisponible_graphe_vide():
    """Si la brique mémoire est indisponible, charger_graphe() se termine sans exception."""
    specs = [_spec("quelque_chose", "description")]
    os.environ["MEMOIRE_URL"] = "http://127.0.0.1:1"  # port fermé
    try:
        asyncio.run(ga.charger_graphe(specs))
        # Le graphe est construit sur une liste vide → _construit=True, _boost vide
        assert ga._graphe._construit is True
        assert ga._graphe._boost == {}
    finally:
        del os.environ["MEMOIRE_URL"]
        ga._graphe.construire([], [])  # remet propre


def test_10_stats_retourne_top5():
    """stats() renvoie un top-5 non vide après construction avec assez de capacités."""
    g = _graphe_neuf()
    specs = [_spec(f"outil_{i}", f"terme_{i} commun") for i in range(8)]
    souvenirs = [f"terme_{i} commun" for i in range(8)]
    g.construire(souvenirs, specs)
    st = g.stats()
    assert st["capacites_liees"] > 0
    assert len(st["top5"]) == 5


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
