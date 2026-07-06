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
