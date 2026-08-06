"""Tests du métier pur (fraîcheur, validations) — aucune I/O, instant injecté."""
from datetime import datetime, timedelta, timezone

import pytest

import domaine

MAINTENANT = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


def _il_y_a(jours: int) -> str:
    return (MAINTENANT - timedelta(days=jours)).isoformat()


# ── Pastilles de fraîcheur (bornes exactes 30/90 jours) ──────────
def test_pastille_rouge_a_29_jours():
    assert domaine.pastille_fraicheur("entreprise", _il_y_a(29), MAINTENANT) == "rouge"


def test_pastille_orange_a_30_jours():
    assert domaine.pastille_fraicheur("entreprise", _il_y_a(30), MAINTENANT) == "orange"


def test_pastille_orange_a_89_jours():
    assert domaine.pastille_fraicheur("entreprise", _il_y_a(89), MAINTENANT) == "orange"


def test_pastille_bleu_a_90_jours():
    assert domaine.pastille_fraicheur("entreprise", _il_y_a(90), MAINTENANT) == "bleu"


def test_pastille_type_inconnu_utilise_les_regles_defaut():
    assert domaine.pastille_fraicheur("ovni", _il_y_a(10), MAINTENANT) == "rouge"


def test_pastille_sans_date_ou_date_illisible_reste_bleu():
    assert domaine.pastille_fraicheur("entreprise", None, MAINTENANT) == "bleu"
    assert domaine.pastille_fraicheur("entreprise", "pas-une-date", MAINTENANT) == "bleu"


def test_pastille_date_future_compte_comme_toute_fraiche():
    futur = (MAINTENANT + timedelta(days=3)).isoformat()
    assert domaine.pastille_fraicheur("entreprise", futur, MAINTENANT) == "rouge"


def test_pastille_date_sans_fuseau_est_acceptee():
    # Les dates Sirene sont souvent « AAAA-MM-JJ » nues : normalisées en UTC.
    assert domaine.pastille_fraicheur("entreprise", "2026-07-01", MAINTENANT) == "rouge"


# ── Filtre fraîcheur → borne de date ─────────────────────────────
def test_date_min_rouge_recule_de_30_jours():
    assert domaine.date_min_pour_fraicheur("entreprise", "rouge", MAINTENANT) == _il_y_a(30)


def test_date_min_bleu_ne_filtre_pas():
    assert domaine.date_min_pour_fraicheur("entreprise", "bleu", MAINTENANT) is None


def test_date_min_pastille_inconnue_leve():
    with pytest.raises(ValueError):
        domaine.date_min_pour_fraicheur("entreprise", "violet", MAINTENANT)


# ── Validations géométriques ─────────────────────────────────────
def test_valider_bbox_ok():
    assert domaine.valider_bbox("43.5, 2.0, 43.7, 2.4") == (43.5, 2.0, 43.7, 2.4)


def test_valider_bbox_malformee_leve():
    with pytest.raises(ValueError):
        domaine.valider_bbox("43.5,2.0,43.7")          # 3 nombres
    with pytest.raises(ValueError):
        domaine.valider_bbox("a,b,c,d")                # pas des nombres


def test_valider_bbox_inversee_leve():
    with pytest.raises(ValueError):
        domaine.valider_bbox("43.7,2.0,43.5,2.4")      # lat_min > lat_max


def test_valider_point_hors_bornes_leve():
    with pytest.raises(ValueError):
        domaine.valider_point(91.0, 0.0)
    with pytest.raises(ValueError):
        domaine.valider_point(0.0, -181.0)


# ── Conversion Lambert93 → WGS84 ─────────────────────────────────
def test_lambert93_vers_wgs84_sur_un_point_reel_carcassonne():
    # Coordonnées Lambert93 RÉELLES d'un DPE à Carcassonne (vérifié LIVE ADEME,
    # 2026-08-05, numero_dpe 2611E0031228S). Référence calculée avec pyproj
    # 3.7.2 (EPSG:2154 → EPSG:4326) : lat=43.21658904532542, lon=2.3590970608354813.
    latitude, longitude = domaine.lambert93_vers_wgs84(647889.49, 6235475.96)
    assert latitude == pytest.approx(43.21659, abs=1e-4)
    assert longitude == pytest.approx(2.35910, abs=1e-4)


def test_lambert93_vers_wgs84_entree_invalide_leve():
    # Note: (0, 0) actually converts to valid WGS84 (-5.98, -1.36).
    # Using NaN which produces NaN lat/lon that fail bounds validation.
    with pytest.raises(ValueError):
        domaine.lambert93_vers_wgs84(float('nan'), float('nan'))


# ── Normalisation d'un logement DPE ──────────────────────────────
PAYLOAD_DPE = {
    "numero_dpe": "2611E0067705R",
    "etiquette_dpe": "F",
    "adresse_ban": "8 Rue Petite Cote de la Cite 11000 Carcassonne",
    "nom_commune_ban": "Carcassonne",
    "code_postal_ban": "11000",
    "coordonnee_cartographique_x_ban": 648048.69,
    "coordonnee_cartographique_y_ban": 6234349.45,
    "date_etablissement_dpe": "2025-03-14",
    "periode_construction": "avant 1948",
    "surface_habitable_logement": 88.7,
    "type_batiment": "maison",
}


def test_normaliser_logement_payload_reel():
    objet = domaine.normaliser_logement(PAYLOAD_DPE)
    assert objet["type"] == "logement"
    # Conversion Lambert93 (648048.69, 6234349.45) with pyproj 3.7.2
    assert objet["latitude"] == pytest.approx(43.20647, abs=1e-4)
    assert objet["longitude"] == pytest.approx(2.36117, abs=1e-4)
    assert objet["ref_externe"] == "2611E0067705R"
    assert objet["source"] == "dpe-ademe"
    assert objet["date_reference"] == "2025-03-14"
    assert objet["metadata"] == {
        "adresse": "8 Rue Petite Cote de la Cite 11000 Carcassonne",
        "commune": "Carcassonne", "code_postal": "11000", "grade_dpe": "F",
        "surface_m2": 88.7, "periode_construction": "avant 1948",
    }


def test_normaliser_logement_sans_numero_dpe_rend_none():
    sans_id = {**PAYLOAD_DPE, "numero_dpe": None}
    assert domaine.normaliser_logement(sans_id) is None


def test_normaliser_logement_sans_coordonnees_rend_none():
    sans_coords = {**PAYLOAD_DPE, "coordonnee_cartographique_x_ban": None}
    assert domaine.normaliser_logement(sans_coords) is None


def test_normaliser_logement_champs_optionnels_absents():
    minimal = {"numero_dpe": "X1", "etiquette_dpe": "G",
              "coordonnee_cartographique_x_ban": 648048.69,
              "coordonnee_cartographique_y_ban": 6234349.45}
    objet = domaine.normaliser_logement(minimal)
    assert objet["metadata"] == {"adresse": "", "commune": "", "code_postal": "",
                                 "grade_dpe": "G", "surface_m2": None,
                                 "periode_construction": None}
    assert objet["date_reference"] is None
