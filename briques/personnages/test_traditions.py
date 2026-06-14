"""Tests du moteur de traditions (S49) — fonctions pures, calculs vérifiables hors ligne.

On vérifie surtout que ce qui est étiqueté « calculé » l'est VRAIMENT, contre des ancrages
connus (4 Ahau du compte long maya, signe solaire aux bornes, animal chinois sexagénaire)."""
from datetime import date, datetime

import traditions as T


# ── Numérologie ──────────────────────────────────────────────────
def test_chemin_de_vie_et_nombres_maitres():
    assert T.chemin_de_vie(date(1990, 9, 5)) == 33      # 1+9+9+0+0+9+0+5 = 33 (maître)
    assert T.chemin_de_vie(date(2000, 1, 1)) == 4


def test_numerologie_nom_vide():
    assert T.numerologie_nom("", "") == {}
    n = T.numerologie_nom("Aria", "")
    assert set(n) == {"expression", "ame", "personnalite", "systeme"}


def test_numerologie_deux_systemes():
    """A=1…Z=26 (classique, défaut) ≠ pythagoricien (A=1…I=9) sur un même nom."""
    classique = T.numerologie_nom("Zoe", "", "classique")
    pyth = T.numerologie_nom("Zoe", "", "pythagoricien")
    assert classique["systeme"] == "classique"
    # Z vaut 26 en classique, 8 en pythagoricien → les totaux diffèrent
    assert classique["expression"] != pyth["expression"] or classique["ame"] != pyth["ame"]
    # vérif exacte classique : z(26)+o(15)+e(5)=46 → 4+6=10 → 1
    assert classique["expression"] == 1


# ── Signes occidental / chinois ──────────────────────────────────
def test_signe_solaire_aux_bornes():
    assert T.signe_solaire(3, 21)["nom"] == "Bélier"     # début du Bélier
    assert T.signe_solaire(3, 20)["nom"] == "Poissons"   # veille
    assert T.signe_solaire(1, 1)["nom"] == "Capricorne"  # début d'année


def test_signe_chinois_connu():
    assert T.signe_chinois(2000)["animal"] == "Dragon"
    assert T.signe_chinois(2008)["animal"] == "Rat"
    el = T.signe_chinois(1990)
    assert el["polarite"] == "Yang" and el["animal"] == "Cheval"


def test_animal_heure_tranches():
    assert T.animal_heure(23)["animal"] == "Rat"         # 23 h → Rat
    assert T.animal_heure(0)["animal"] == "Rat"
    assert T.animal_heure(1)["animal"] == "Buffle"
    assert T.animal_heure(12)["animal"] == "Cheval"


# ── Traditions par date (segments contigus, couverture complète) ─
def test_segments_couvrent_toute_lannee():
    """Aucune date de l'année ne doit tomber « hors segment » (égyptien/celte/totem)."""
    d = date(2001, 1, 1)
    while d.year == 2001:
        assert T.divinite_egyptienne(d.month, d.day)
        assert T.arbre_celte(d.month, d.day)
        assert T.totem_amerindien(d.month, d.day)
        d = d.fromordinal(d.toordinal() + 1)


def test_celte_chataignier_double_periode():
    """Le Châtaignier (gaulois) revient sur deux périodes : 15–24 mai ET 12–21 nov."""
    assert T.arbre_celte(5, 20) == "Châtaignier"
    assert T.arbre_celte(11, 15) == "Châtaignier"


def test_celte_jours_solstices():
    assert T.arbre_celte(3, 21) == "Chêne"               # équinoxe de printemps
    assert T.arbre_celte(6, 24) == "Bouleau"
    assert T.arbre_celte(12, 22) == "Hêtre"


def test_celte_a_cheval_nouvel_an():
    assert T.arbre_celte(12, 25) == "Pommier"            # 23/12 → 01/01
    assert T.arbre_celte(1, 1) == "Pommier"


def test_totem_amerindien_connu():
    assert T.totem_amerindien(4, 1) == "Faucon"          # 21/03 – 19/04
    assert T.totem_amerindien(1, 1) == "Oie"             # à cheval 22/12 – 19/01


# ── Maya Tzolkin (ancrage GMT) ───────────────────────────────────
def test_tzolkin_ancrage_4_ahau():
    """21/12/2012 = 4 Ahau (fin du 13e baktun) — vérifie la corrélation 584283."""
    t = T.tzolkin(date(2012, 12, 21))
    assert t == {"glyphe": "Ahau", "tonalite": 4}


def test_tzolkin_cycle_260():
    """Deux dates espacées de 260 jours ont le même jour Tzolkin."""
    from datetime import timedelta
    base = date(1990, 6, 15)
    assert T.tzolkin(base) == T.tzolkin(base + timedelta(days=260))


# ── Thème astral exact ───────────────────────────────────────────
def test_theme_astral_soleil_coherent_avec_signe_solaire():
    """Le Soleil calculé doit tomber dans le même signe que la table de bornes."""
    dt = datetime(1990, 9, 5, 14, 30)
    ta = T.theme_astral(dt, utc_offset_h=2.0, latitude=43.6, longitude=1.44)
    assert ta["soleil"]["signe"] == "Vierge"
    assert set(ta) >= {"soleil", "ascendant", "milieu_du_ciel", "maisons"}
    assert len(ta["maisons"]) == 12


def test_lune_contre_exemple_meeus():
    """Ancrage gold : exemple de Meeus (12/04/1992 0h) → longitude lunaire 133,163°."""
    lon = T.lune_longitude(datetime(1992, 4, 12, 0, 0), 0.0)
    assert abs(lon - 133.162655) < 0.05      # série abrégée : tolérance large mais serrée


def test_lune_avance_chaque_jour():
    """La Lune progresse d'environ 13°/jour (mouvement moyen) — teste la mécanique."""
    from datetime import timedelta
    d0 = datetime(2000, 6, 1, 0, 0)
    a = T.lune_longitude(d0, 0.0)
    b = T.lune_longitude(d0 + timedelta(days=1), 0.0)
    assert 11 < (b - a) % 360 < 15


def test_nakshatra_borne():
    """Nakshatra = 27 maisons de 13°20' depuis 0° sidéral ; pada ∈ {1..4}."""
    nk = T.nakshatra(13.0, 2000)             # ~tout début, après ajustement ayanamsa → recule
    assert nk["nakshatra"] in T.NAKSHATRAS
    assert 1 <= nk["pada"] <= 4


def test_calculer_lune_sans_coordonnees():
    """Le signe lunaire + nakshatra apparaissent dès qu'on a date + heure (sans lieu)."""
    out = T.calculer({"date_naissance": "1992-04-12", "heure_naissance": "00:00"})
    assert out["signe_lunaire"]["signe"] == "Lion"     # 133° → Lion
    assert "nakshatra" in out
    assert "theme_astral" not in out                   # pas de coordonnées → désactivé


def test_vedique_decale_par_ayanamsa():
    """Le rashi sidéral recule (souvent d'un signe) par rapport au tropical."""
    lon_tropicale = 5.0          # tout début du Bélier en tropical
    r = T.rashi_vedique(lon_tropicale, 1990)
    assert r["rashi"] == "Poissons"     # 5° − ~24° → fin des Poissons
    assert r["ayanamsa"] > 23


# ── Synthèse calculer() : repli honnête ──────────────────────────
def test_calculer_date_seule():
    out = T.calculer({"date_naissance": "1990-09-05"})
    assert out["signe_solaire"]["nom"] == "Vierge"
    assert "maya" in out and "egyptien" in out
    assert "theme_astral" not in out          # pas d'heure/coordonnées → désactivé


def test_calculer_complet():
    out = T.calculer({
        "prenoms": "Aria", "nom": "Solis", "date_naissance": "1990-09-05",
        "heure_naissance": "14:30", "latitude": 43.6, "longitude": 1.44, "utc_offset": 2.0,
    })
    assert "theme_astral" in out and "vedique" in out
    assert "numerologie_nom" in out and "animal_heure" in out


def test_calculer_date_invalide_ne_leve_pas():
    assert T.calculer({"date_naissance": "pas-une-date"}) == {}
    assert T.calculer({}) == {}
