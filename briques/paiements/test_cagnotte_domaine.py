"""Tests du sous-domaine PUR de la cagnotte (S166) : reste, statut effectif, borne
anti-surpaiement. Rapides (0 I/O)."""
import domaine


def test_reste_borne_a_zero_meme_si_solde_depasse():
    assert domaine.reste_cagnotte(5000, 2000) == 3000
    assert domaine.reste_cagnotte(5000, 5000) == 0
    assert domaine.reste_cagnotte(5000, 6000) == 0     # caisse trop-perçue → jamais négatif
    assert domaine.reste_cagnotte(-100, -50) == 0      # entrées absurdes bornées


def test_statut_effectif_derive_du_reste():
    assert domaine.statut_effectif(domaine.CAGNOTTE_OUVERTE, 3000) == domaine.CAGNOTTE_OUVERTE
    assert domaine.statut_effectif(domaine.CAGNOTTE_OUVERTE, 0) == domaine.CAGNOTTE_ATTEINTE
    # « Annulée » prime toujours, même si le reste est nul.
    assert domaine.statut_effectif(domaine.CAGNOTTE_ANNULEE, 0) == domaine.CAGNOTTE_ANNULEE
    assert domaine.statut_effectif(domaine.CAGNOTTE_ANNULEE, 3000) == domaine.CAGNOTTE_ANNULEE


def test_contribution_bornee_au_reste():
    assert domaine.contribution_bornee(3000, 1000) == 1000     # sous le reste → tel quel
    assert domaine.contribution_bornee(3000, 5000) == 3000     # au-dessus → plafonné au reste
    assert domaine.contribution_bornee(0, 1000) == 0           # cagnotte pleine → rien
    assert domaine.contribution_bornee(3000, 0) == 0           # saisie vide → rien
    assert domaine.contribution_bornee(3000, -50) == 0         # négatif → rien
