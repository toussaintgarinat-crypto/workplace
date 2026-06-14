"""Tests de la synthèse holistique (S49) — descendant (portrait) et montant (inverse).

On vérifie la cohérence des deux sens (le même dictionnaire de tags doit produire un
overlap quand on l'agrège puis qu'on l'inverse) et la robustesse des replis."""
import synthese as S
import traditions as T


# ── Mode descendant : stats / archétype / pierre ─────────────────
def test_stats_bornees_0_100():
    trad = T.calculer({"date_naissance": "1990-09-05", "prenoms": "Aria"})
    stats = S.stats_depuis_traditions(trad)
    assert set(stats) == set(S.STATS)
    assert all(0 <= v <= 100 for v in stats.values())
    assert max(stats.values()) == 100                 # dominante normalisée à 100


def test_portrait_structure_complete():
    trad = T.calculer({"date_naissance": "1990-09-05", "prenoms": "Aria", "nom": "Solis"})
    p = S.portrait(trad, nom="Aria")
    assert p["archetype"] in [a[0] for a in S._ARCHETYPES]
    assert len(p["forces"]) == 3
    assert p["faiblesse"] in S.STATS
    assert p["pierre_equilibrage"]["compense"] == p["faiblesse"]
    assert "divertissement" in p["recit"].lower()


def test_pierre_compense_la_faiblesse():
    """La pierre d'équilibrage est choisie en SORTIE selon la stat la plus faible."""
    trad = T.calculer({"date_naissance": "1985-04-10"})
    p = S.portrait(trad)
    faible = p["faiblesse"]
    assert p["stats"][faible] == min(p["stats"].values())   # bien la stat la plus faible (ex æquo tolérés)
    assert p["pierre_equilibrage"]["compense"] == faible
    assert p["pierre_equilibrage"]["pierre"] == S._EQUILIBRAGE[faible][0]


def test_scorpion_est_discret():
    """Garde-fou de cohérence : un Scorpion doit ressortir fort en Discrétion."""
    trad = T.calculer({"date_naissance": "1990-11-05"})    # Scorpion
    stats = S.stats_depuis_traditions(trad)
    assert stats["Discrétion"] >= 70


# ── Mode montant : description → pistes ───────────────────────────
def test_cibler_stats_reconnait_les_mots():
    cible = S.cibler_stats("un guerrier colérique mais profondément spirituel")
    assert cible["Combativité"] > 0
    assert cible["Sagesse"] > 0
    assert cible["Charisme"] == 0


def test_recherche_inverse_guerrier_spirituel():
    r = S.recherche_inverse("guerrier colérique mais spirituel et solitaire")
    assert r["signes"]                                  # au moins une piste
    assert r["archetype"] in [a[0] for a in S._ARCHETYPES]
    # le signe en tête doit charger Combativité ou Sagesse (les traits demandés)
    tete = r["signes"][0]["signe"]
    profil = S._profil_signe(tete)
    assert profil.get("Combativité", 0) + profil.get("Sagesse", 0) > 0


def test_recherche_inverse_propose_une_date_coherente():
    """La date proposée doit retomber dans le signe en tête (boucle descendant↔montant)."""
    r = S.recherche_inverse("artiste sensible et créatif")
    ex = r["exemple_date"]
    assert ex
    if len(ex) == 10 and ex[4] == "-":                  # une vraie date ISO
        from datetime import date
        d = date.fromisoformat(ex)
        assert T.signe_solaire(d.month, d.day)["nom"] == r["signes"][0]["signe"]


def test_toutes_traditions_votent():
    """Les tags égyptien/celte/totem/maya doivent contribuer (pas seulement signe+nombre)."""
    trad = T.calculer({"date_naissance": "1990-09-05"})
    base = S.stats_depuis_traditions(trad)
    # on retire les traditions « secondaires » → les stats doivent changer
    trad_min = {k: trad[k] for k in ("signe_solaire", "signe_chinois", "chemin_de_vie")}
    reduit = S.stats_depuis_traditions(trad_min)
    assert base != reduit


def test_anubis_charge_la_discretion():
    """Garde-fou : un profil sous Anubis (égyptien) doit pousser la Discrétion."""
    cible = {"Discrétion": 3, "Sagesse": 1}
    assert S._meilleur(S._TAGS_EGYPTE, cible) == "Anubis"


def test_recherche_inverse_propose_autres_traditions():
    r = S.recherche_inverse("mystérieux solitaire analytique et spirituel")
    at = r["autres_traditions"]
    assert at["egyptien"] and at["celte"] and at["amerindien"] and at["maya"]
    # un caractère secret/sage doit tomber sur Anubis côté Égypte
    assert at["egyptien"] == "Anubis"


def test_cibler_stats_tolere_les_fautes():
    """Champ lexical : un mot mal orthographié est rattrapé par similarité (difflib)."""
    cible = S.cibler_stats("un manipulteur sournois")     # « manipulteur » = faute
    assert cible["Discrétion"] >= 2


def test_cibler_stats_champ_lexical_large():
    """Synonymes variés couverts : intelligent→Sagesse, créatif→Créativité, etc."""
    assert S.cibler_stats("intelligent et cultivé")["Sagesse"] >= 1
    assert S.cibler_stats("excentrique et inventif")["Créativité"] >= 1
    assert S.cibler_stats("loyal et discipliné")["Stabilité"] >= 1
    assert S.cibler_stats("chaleureux et bienveillant")["Émotivité"] >= 1


def test_recherche_inverse_traits_sombres():
    """Régression : une description « sombre » (pervers narcissique) doit calculer un profil."""
    r = S.recherche_inverse("pervers narcissique manipulateur")
    assert r["signes"], "pervers narcissique devrait être reconnu"
    assert r["cible"].get("Charisme") and r["cible"].get("Discrétion")


def test_recherche_inverse_description_vide():
    r = S.recherche_inverse("xyzzy bla bla")
    assert r["signes"] == [] and r["nombres"] == []
    assert "Aucun trait" in r["note"]


def test_coherence_descendant_montant():
    """Le signe le plus « combatif » selon l'inverse doit l'être aussi en descendant."""
    r = S.recherche_inverse("combatif agressif fonceur")
    tete = r["signes"][0]["signe"]
    plage = T.SIGNE_PLAGES[tete][0]
    trad = T.calculer({"date_naissance": f"2000-{plage[0]:02d}-{plage[1]:02d}"})
    stats = S.stats_depuis_traditions(trad)
    assert stats["Combativité"] >= 60
