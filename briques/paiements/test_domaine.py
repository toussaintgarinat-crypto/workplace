"""Tests du sous-domaine PUR : Argent, commission plateforme, transitions d'état. Rapides (0 I/O)."""
import pytest

import domaine
from domaine import Argent


def test_argent_soustraction_et_devise():
    assert Argent(1000).moins(Argent(250)).cents == 750
    with pytest.raises(ValueError):
        Argent(100, "EUR").moins(Argent(50, "USD"))


def test_commission_en_points_de_base_arrondie_au_centime_inferieur():
    r = domaine.calculer_commission(1000, commission_bps=250)      # 2,5 %
    assert r == {"brut": 1000, "commission": 25, "net": 975}
    # 999 × 2,5 % = 24,975 → tronqué à 24 (on ne sur-prélève jamais le vendeur).
    assert domaine.calculer_commission(999, commission_bps=250)["commission"] == 24


def test_commission_montant_fixe_prioritaire():
    r = domaine.calculer_commission(1000, commission_bps=250, commission_cents=300)
    assert r == {"brut": 1000, "commission": 300, "net": 700}


def test_commission_bornee_jamais_negative_ni_superieure_au_brut():
    assert domaine.calculer_commission(1000, commission_cents=5000)["commission"] == 1000  # plafonnée
    assert domaine.calculer_commission(1000, commission_cents=-50)["commission"] == 0       # plancher
    assert domaine.calculer_commission(-200, commission_bps=250)["brut"] == 0               # montant ≥ 0


def test_transitions_paiement():
    assert domaine.transition_paiement_permise(domaine.PAIEMENT_CREE, domaine.PAIEMENT_PAYE)
    assert domaine.transition_paiement_permise(domaine.PAIEMENT_PAYE, domaine.PAIEMENT_REMBOURSE)
    assert not domaine.transition_paiement_permise(domaine.PAIEMENT_REMBOURSE, domaine.PAIEMENT_PAYE)
    assert not domaine.transition_paiement_permise(domaine.PAIEMENT_CREE, domaine.PAIEMENT_REMBOURSE)


def test_compte_peut_encaisser_seulement_si_actif():
    assert domaine.compte_peut_encaisser(domaine.COMPTE_ACTIF)
    assert not domaine.compte_peut_encaisser(domaine.COMPTE_INCOMPLET)
    assert not domaine.compte_peut_encaisser(domaine.COMPTE_CREE)
