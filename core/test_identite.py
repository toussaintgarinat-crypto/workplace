"""Tests S48 — dérivations de la fiche d'identité (fonctions pures, stdlib only).

Date de référence figée pour des tests déterministes (pas de date.today() réel).
"""
from datetime import date, datetime

import identite as I


REF = date(2026, 6, 13)                 # « aujourd'hui » des tests
TOUSSAINT = {
    "prenoms": "Toussaint Michel Rémi", "nom": "Garinat",
    "date_naissance": "1990-09-05", "heure_naissance": "11:05",
    "lieu_naissance": "Toulouse", "latitude": 43.6045, "longitude": 1.4442,
    "utc_offset": 2,                    # CEST le 5 septembre 1990
}


# ── Signe solaire ────────────────────────────────────────────────
def test_signe_solaire_bornes():
    assert I.signe_solaire(9, 5)["nom"] == "Vierge"
    assert I.signe_solaire(9, 23)["nom"] == "Balance"   # premier jour Balance
    assert I.signe_solaire(9, 22)["nom"] == "Vierge"    # dernier jour Vierge
    assert I.signe_solaire(1, 1)["nom"] == "Capricorne"
    assert I.signe_solaire(12, 25)["nom"] == "Capricorne"


def test_signe_solaire_element():
    assert I.signe_solaire(9, 5)["element"] == "Terre"  # Vierge = Terre
    assert I.signe_solaire(3, 25)["element"] == "Feu"   # Bélier = Feu


# ── Signe chinois ────────────────────────────────────────────────
def test_signe_chinois_cheval_metal_yang():
    c = I.signe_chinois(1990)
    assert c["animal"] == "Cheval"
    assert c["element"] == "Métal"
    assert c["polarite"] == "Yang"


def test_signe_chinois_cycle():
    assert I.signe_chinois(2008)["animal"] == "Rat"      # 2008 = Rat
    assert I.signe_chinois(2000)["animal"] == "Dragon"   # 2000 = Dragon


# ── Génération / saison / pierre / fleur ─────────────────────────
def test_generation():
    assert "Millennial" in I.generation(1990)
    assert I.generation(1970) == "Génération X"


def test_saison_hemispheres():
    assert I.saison(9, 5) == "été"
    assert I.saison(9, 5, "sud") == "hiver"
    assert I.saison(1, 10) == "hiver"


def test_pierre_et_fleur():
    assert I.PIERRES[9] == "Saphir"
    assert I.FLEURS[9] == "Aster"


# ── Âge / anniversaire / jours vécus ─────────────────────────────
def test_age():
    a = I.age(date(1990, 9, 5), REF)
    assert a["ans"] == 35              # 5 sept 1990 → 13 juin 2026 : 35 ans
    assert a["mois"] == 9              # +9 mois (sept→juin)
    assert a["jours"] == 8             # 5 → 13


def test_age_avant_anniversaire_dans_le_mois():
    a = I.age(date(2000, 6, 20), date(2026, 6, 13))
    assert a["ans"] == 25              # anniv pas encore passé ce mois


def test_prochain_anniversaire():
    an = I.prochain_anniversaire(date(1990, 9, 5), REF)
    assert an["date"] == "2026-09-05"
    assert an["dans_jours"] == (date(2026, 9, 5) - REF).days


def test_anniversaire_aujourdhui():
    an = I.prochain_anniversaire(date(1990, 6, 13), REF)
    assert an["dans_jours"] == 0       # c'est aujourd'hui


def test_jours_vecus_et_jalon():
    jv = I.jours_vecus(date(1990, 9, 5), REF)
    assert jv["jours"] == (REF - date(1990, 9, 5)).days
    assert jv["prochain_jalon"] % 1000 == 0
    assert jv["prochain_jalon"] > jv["jours"]


# ── Numérologie ──────────────────────────────────────────────────
def test_reduire_garde_nombres_maitres():
    assert I._reduire(38) == 11        # 3+8 = 11, conservé
    assert I._reduire(29) == 11        # 2+9 = 11
    assert I._reduire(19) == 1         # 1+9=10 → 1


def test_chemin_de_vie():
    # 1990-09-05 : 1+9+9+0+0+9+0+5 = 33 (nombre maître conservé)
    assert I.chemin_de_vie(date(1990, 9, 5)) == 33


def test_numerologie_nom_ignore_accents_et_espaces():
    n = I.numerologie_nom("Rémi", "")
    n2 = I.numerologie_nom("remi", "")
    assert n == n2                     # accents neutralisés
    assert 1 <= n["expression"] <= 33


# ── Mini-thème astral ────────────────────────────────────────────
def test_theme_soleil_en_vierge():
    th = I.theme_astral(datetime(1990, 9, 5, 11, 5), 2, 43.6045, 1.4442)
    assert th["soleil"]["signe"] == "Vierge"        # cohérent avec le signe solaire
    assert 150 <= th["soleil"]["longitude"] < 180   # secteur Vierge de l'écliptique


def test_theme_ascendant_et_maisons():
    th = I.theme_astral(datetime(1990, 9, 5, 11, 5), 2, 43.6045, 1.4442)
    asc = th["ascendant"]
    assert asc["signe"] in [s[0] for s in I.SIGNES]
    assert 0 <= asc["longitude"] < 360
    # 12 maisons, la 1re = signe de l'ascendant.
    assert len(th["maisons"]) == 12
    assert th["maisons"][0]["signe"] == asc["signe"]
    assert th["heure_utc"] == 9.08                  # 11h05 CEST → 09h05 UTC


# ── Synthèse ─────────────────────────────────────────────────────
def test_deriver_complet():
    d = I.deriver(TOUSSAINT, REF)
    assert d["signe_solaire"]["nom"] == "Vierge"
    assert d["signe_chinois"]["animal"] == "Cheval"
    assert d["age"]["ans"] == 35
    assert d["chemin_de_vie"] == 33
    assert "theme_astral" in d          # heure + coordonnées présentes
    assert "numerologie_nom" in d


def test_deriver_robuste_champs_manquants():
    # Date seule : pas de thème astral, pas d'erreur.
    d = I.deriver({"date_naissance": "1990-09-05"}, REF)
    assert "signe_solaire" in d
    assert "theme_astral" not in d
    # Fiche vide : dict vide, aucune exception.
    assert I.deriver({}, REF) == {}
    # Date invalide tolérée.
    assert I.deriver({"date_naissance": "pas-une-date"}, REF) == {}


def test_resume_texte_etiquette_divertissement():
    txt = I.resume_texte(TOUSSAINT, REF)
    assert "Vierge" in txt
    assert "divertissement" in txt      # honnêteté : astro ≠ fait
    assert "35 ans" in txt
